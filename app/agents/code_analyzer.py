"""代码分析器: a bounded subagent with independent tasks and read-only tools.

This implementation is deterministic static analysis, not an LLM or PHP runtime.
Repository content is data: it never becomes executable commands or instructions.
"""
import re
from dataclasses import dataclass

from app.agents.repository import REPOSITORY_URL, CodeFile, RepositoryIndex, RepositoryStore, RepositoryUnavailable, valid_path
from app.retrieval import RepositoryTools, LocalSearchGateway
from app.models import AgentStep, AskResponse, Claim, CodeCitation, RepositoryInfo

AGENT_NAME = "代码分析器"
SCOPE = "osTicket 固定提交的静态代码定位与结构分析；不执行代码，不验证运行时行为，也不确认故障根因。"
STOP_WORDS = {"osticket", "github", "com", "https", "http", "the", "where", "how", "does", "code", "find", "repository", "please", "explain", "analyze", "php"}
CONCEPTS = {
    "登录": ("login", "authenticate", "StaffAuthenticationBackend"),
    "认证": ("authenticate", "authentication", "requireApiKey"),
    "鉴权": ("requireApiKey", "getApiKey"),
    "工单": ("ticket",),
    "创建": ("create",),
    "新建": ("create",),
    "邮件": ("email", "mail"),
    "附件": ("attachment",),
    "权限": ("permission", "hasPerm"),
    "数据库": ("db_query", "mysqli"),
    "路由": ("dispatcher", "url_post"),
    "定时": ("cron",),
    "会话": ("session",),
    "密码": ("password", "passwd"),
}


@dataclass(frozen=True)
class CodeAnalysisTask:
    question: str
    repository: str = REPOSITORY_URL
    file_path: str | None = None


class CodeAnalyzerAgent:
    name = AGENT_NAME

    def __init__(self, store: RepositoryStore | None = None, backend: str = "local"):
        if backend not in {"local", "mcp_stdio"}:
            raise ValueError("CODE_SEARCH_BACKEND must be local or mcp_stdio")
        self.store = store or RepositoryStore()
        self.backend = backend

    def run(self, task: CodeAnalysisTask) -> AskResponse:
        if self.backend == "mcp_stdio":
            from app.mcp_client import run_analysis
            return run_analysis(self, task)
        return self._run(task, LocalSearchGateway(self.store))

    def repository_info(self) -> RepositoryInfo:
        if self.backend == "mcp_stdio":
            from app.mcp_client import get_repository_info
            return get_repository_info(self.store)
        return LocalSearchGateway(self.store).describe_repository()["info"]

    def _run(self, task: CodeAnalysisTask, tools) -> AskResponse:
        trace = getattr(tools, "trace", [])
        trace.append(AgentStep(agent=self.name, action="accept_task", detail="接收主代理委派的代码分析任务"))

        def result(status, reason, message, **kwargs):
            return AskResponse(status=status, reason_code=reason, message=message, mode="static_code_analysis",
                               scope=SCOPE, delegated_to=self.name, agent_trace=trace.copy(), retrieval_backend=self.backend, **kwargs)

        requested = task.repository.removesuffix("/").removesuffix(".git")
        if requested.lower() != REPOSITORY_URL.lower():
            return result("insufficient_evidence", "repository_not_supported", "当前仅接入 osTicket/osTicket，不会自动访问其他仓库。")
        if task.file_path and not valid_path(task.file_path):
            return result("insufficient_evidence", "invalid_repository_path", "文件路径必须是仓库内的相对路径，例如 scp/login.php。")
        try:
            summary = tools.describe_repository()
            info = summary["info"]
        except RepositoryUnavailable:
            if self.backend == "mcp_stdio":
                raise
            return result("upstream_error", "repository_index_unavailable", "代码索引未准备好或与固定提交不一致，请运行 python -m scripts.index_repository 后重试。")
        trace.append(AgentStep(agent=self.name, action="load_repository_index", detail=f"读取固定提交 {info.commit_sha[:12]} 的 {info.indexed_files} 个文件"))
        q = task.question.lower()
        if any(word in q for word in ("执行", "运行代码", "删除文件", "修改仓库", "提交代码", "shell命令", "ignore previous")):
            return result("insufficient_evidence", "read_only_analysis", "代码分析器仅提供静态分析，无法执行或修改目标仓库。", repository=info)
        if any(word in q for word in ("航司", "行李", "退票", "改签", "peach")):
            return result("needs_clarification", "mixed_agent_task", "请把旅行政策与代码问题分开提问。", clarifying_questions=["本次要查询航空政策，还是分析 osTicket 代码？"], repository=info)

        sources = []
        claims = []

        def add(path, line, description):
            source = tools.read_file(path, line, limit=80, mode="symbol")
            if source:
                if source.context_kind == "complete_symbol":
                    description += f" 已返回 `{source.symbol_name}` 的完整声明体（词法边界识别）。"
                elif source.context_kind == "partial_symbol":
                    description += " 所属声明体超过片段预算，仅展示命中位置附近的部分代码。"
                else:
                    description += " 未确认函数/类边界，按行摘取；不代表完整逻辑。"
                sources.append(source)
                claims.append(Claim(text=description, citation_ids=[source.chunk_id]))
                trace.append(AgentStep(agent=self.name, action="read_file", detail=f"{path}:L{source.line_start}–L{source.line_end} · {source.context_kind}"))

        path_mentions = re.findall(r"[a-z0-9_./-]+\.(?:php|js|sql|md|txt|json)\b", task.question, re.I)
        requested_path = task.file_path or (path_mentions[0] if len(path_mentions) == 1 else None)
        if not task.file_path and len(path_mentions) > 1:
            return result("needs_clarification", "multiple_code_targets", "请一次分析一个明确目标。", repository=info,
                          clarifying_questions=["请指定一个文件路径，或改为查询整个仓库的结构。"])
        overview = any(word in q for word in ("架构", "结构", "概览", "overview", "architecture")) and not requested_path
        preface = ""
        if requested_path:
            if not valid_path(requested_path):
                return result("insufficient_evidence", "invalid_repository_path", "路径不在可读取的仓库范围内。", repository=info)
            file = tools.get_file_info(requested_path)
            if not file:
                return result("insufficient_evidence", "file_not_indexed", "该文件未包含在本地索引中；不代表它一定不存在于完整仓库。", repository=info)
            preface = f"文件 {file.path}，{file.line_count} 行，类型 {file.language}。以下展示声明或加载入口的代码证据。\n"
            # A file query presents declarations and literal dependencies, not a
            # speculative narrative about business behavior.
            line = file.entry_line
            add(file.path, line, f"{file.path} 的声明或加载入口位于 L{line} 附近。")
        elif overview:
            trace.append(AgentStep(agent=self.name, action="describe_repository", detail="统计已索引文件类型与目录；不推断运行时调用图"))
            languages = ", ".join(f"{name}: {count}" for name, count in sorted(summary["languages"].items(), key=lambda item: -item[1])[:5])
            directories = ", ".join(f"{name}: {count}" for name, count in sorted(summary["directories"].items(), key=lambda item: -item[1])[:6])
            preface = f"osTicket 静态结构概览（提交 {info.commit_sha[:12]}）：\n已索引 {summary['files']} 个文本文件；类型分布：{languages}。\n目录文件数：{directories}。\n以下入口依据当前快照中的实际代码定位：\n"
            anchors = [("open.php", "Ticket::create"), ("scp/login.php", "StaffAuthenticationBackend::process"),
                       ("api/http.php", "url_post"), ("include/class.ticket.php", "class Ticket ")]
            for path, anchor in anchors:
                file = tools.get_file_info(path, anchor)
                if file and file.anchor_line:
                    number = file.anchor_line
                    add(path, number, f"{path}:L{number} 包含 `{anchor.strip()}`，可作为阅读该入口的起点。")
        else:
            # Exact identifiers supplied by the user take precedence over the
            # bilingual concept aliases; a missing symbol must not fall back to
            # a loosely related generic answer.
            clean_q = re.sub(r"https?://\S+", "", q)
            explicit = [term for term in re.findall(r"[a-z_][a-z_0-9]*|\b\d{3}\b", clean_q) if term not in STOP_WORDS]
            aliases = [term for concept, words in CONCEPTS.items() if concept in q for term in words]
            terms = explicit or aliases
            if not terms:
                return result("needs_clarification", "missing_code_target", "需要具体的代码分析目标。", repository=info,
                              clarifying_questions=["可以询问仓库结构、登录/工单/API 代码位置，或提供文件路径、函数名、错误文本。"])
            preferred = ()
            if "登录" in q or "login" in q:
                preferred = ("scp/login.php", "include/class.auth.php", "login.php") if any(word in q for word in ("客服", "员工", "staff", "agent")) else ("login.php", "scp/login.php", "include/class.auth.php")
            elif ("工单" in q or "ticket" in q) and any(word in q for word in ("创建", "新建", "create")):
                preferred = ("open.php", "include/api.tickets.php", "include/class.ticket.php")
            elif "api" in q:
                preferred = ("include/class.api.php", "include/api.tickets.php", "api/http.php", "include/api.cron.php")
            hits = tools.search_code(terms, preferred_paths=preferred)
            trace.append(AgentStep(agent=self.name, action="search_code", detail=f"按 {len(terms)} 个标识符/主题词检索，找到 {len(hits)} 个候选文件"))
            for file, line in hits:
                add(file.path, line, f"{file.path}:L{line} 命中查询标识符或主题词。")
            preface = "以下是代码检索与声明定位结果，不能据此断定具体故障原因。\n"
        if not sources:
            return result("insufficient_evidence", "no_code_evidence", "当前索引中没有找到足够的代码证据，请提供准确的文件路径、函数名或错误文本。", repository=info)
        trace.append(AgentStep(agent=self.name, action="return_evidence", detail=f"返回 {len(sources)} 段提交固定、带行号的代码证据"))
        answer = preface + "\n".join(f"{i}. {claim.text}" for i, claim in enumerate(claims, 1))
        return result("answered", "code_evidence_found", "代码分析器已完成静态检索，展开代码片段可核对结果。", answer=answer, claims=claims, sources=sources, repository=info)
