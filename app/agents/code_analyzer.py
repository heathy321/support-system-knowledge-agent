"""Code Analyzer: a bounded subagent with independent tasks and read-only tools.

This implementation is deterministic static analysis, not an LLM or PHP runtime.
Repository content is data: it never becomes executable commands or instructions.
"""
import re
from dataclasses import dataclass

from app.agents.repository import REPOSITORY_URL, CodeFile, RepositoryIndex, RepositoryStore, RepositoryUnavailable, valid_path
from app.retrieval import RepositoryTools, LocalSearchGateway
from app.models import AgentStep, AskResponse, Claim, CodeCitation, RepositoryInfo

AGENT_NAME = "Code Analyzer"
SCOPE = "Static code location and structure analysis at a pinned osTicket commit. No code execution, runtime verification or root-cause determination."
STOP_WORDS = set("osticket github com https http the where how does code find repository please explain analyze php a an is are of in at to for and or this that which what should i we you when with from source declaration declared defined locate location check inspect view read see related relevant returns returning error status received receiving implementation logic entry point entrypoint document documentation official requirement requirements".split())
CONCEPTS = {
    "login": ("login", "authenticate", "StaffAuthenticationBackend"),
    "authentication": ("authenticate", "authentication", "requireApiKey"),
    "authorization": ("requireApiKey", "getApiKey"),
    "ticket": ("ticket",),
    "creation": ("create",),
    "create": ("create",),
    "email": ("email", "mail"),
    "attachment": ("attachment",),
    "permission": ("permission", "hasPerm"),
    "database": ("db_query", "mysqli"),
    "routing": ("dispatcher", "url_post"),
    "scheduled": ("cron",),
    "session": ("session",),
    "password": ("password", "passwd"),
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
        trace.append(AgentStep(agent=self.name, action="accept_task", detail="Accept the code-analysis task delegated by the main agent"))

        def result(status, reason, message, **kwargs):
            return AskResponse(status=status, reason_code=reason, message=message, mode="static_code_analysis",
                               scope=SCOPE, delegated_to=self.name, agent_trace=trace.copy(), retrieval_backend=self.backend, **kwargs)

        requested = task.repository.removesuffix("/").removesuffix(".git")
        if requested.lower() != REPOSITORY_URL.lower():
            return result("insufficient_evidence", "repository_not_supported", "Only osTicket/osTicket is supported. Other repositories are not accessed automatically.")
        if task.file_path and not valid_path(task.file_path):
            return result("insufficient_evidence", "invalid_repository_path", "Use a repository-relative file path, such as scp/login.php.")
        try:
            summary = tools.describe_repository()
            info = summary["info"]
        except RepositoryUnavailable:
            if self.backend == "mcp_stdio":
                raise
            return result("upstream_error", "repository_index_unavailable", "The index is unavailable or does not match the pinned commit. Run python -m scripts.index_repository and try again.")
        trace.append(AgentStep(agent=self.name, action="load_repository_index", detail=f"Read {info.indexed_files} indexed files at commit {info.commit_sha[:12]}"))
        q = task.question.lower()
        # Normalize common support phrasing for retrieval only. Keep the original
        # question and exact source excerpts untouched.
        q = re.sub(r"\b(?:log[ -]?in|sign[ -]?in)\b", "login", q)
        if any(word in q for word in ("execute", "run code", "run the code", "delete files", "modify the repository", "commit changes", "shell command", "ignore previous")):
            return result("insufficient_evidence", "read_only_analysis", "The Code Analyzer performs static analysis only; it cannot execute or modify the target repository.", repository=info)
        if re.search(r"\b(airlines?|baggage|luggage|flights?|rebooking|peach)\b", q):
            return result("insufficient_evidence", "outside_project_scope", "Only osTicket code retrieval is supported. Travel policies are outside this project scope.", repository=info)

        sources = []
        claims = []

        def add(path, line, description):
            source = tools.read_file(path, line, limit=80, mode="symbol")
            if source:
                if source.context_kind == "complete_symbol":
                    description += f" The complete declaration of `{source.symbol_name}` is shown, based on lexical boundaries."
                elif source.context_kind == "partial_symbol":
                    description += " The declaration exceeds the excerpt budget; only part of the code around the match is shown."
                else:
                    description += " Function/class boundaries were not confirmed. This line window may omit relevant logic."
                sources.append(source)
                claims.append(Claim(text=description, citation_ids=[source.chunk_id]))
                trace.append(AgentStep(agent=self.name, action="read_file", detail=f"{path}:L{source.line_start}–L{source.line_end} · {source.context_kind}"))

        path_mentions = re.findall(r"[a-z0-9_./-]+\.(?:php|js|sql|md|txt|json)\b", task.question, re.I)
        requested_path = task.file_path or (path_mentions[0] if len(path_mentions) == 1 else None)
        if not task.file_path and len(path_mentions) > 1:
            return result("needs_clarification", "multiple_code_targets", "Please specify one code target at a time.", repository=info,
                          clarifying_questions=["Provide one file path, or ask for a repository overview."])
        overview = any(word in q for word in ("structure", "overview", "architecture")) and not requested_path
        preface = ""
        if requested_path:
            if not valid_path(requested_path):
                return result("insufficient_evidence", "invalid_repository_path", "The path is outside the readable repository scope.", repository=info)
            file = tools.get_file_info(requested_path)
            if not file:
                return result("insufficient_evidence", "file_not_indexed", "This file is not in the local index. It may still exist in the full repository.", repository=info)
            preface = f"File {file.path}: {file.line_count} lines, language {file.language}. Declaration or entry-point evidence follows.\n"
            # A file query presents declarations and literal dependencies, not a
            # speculative narrative about business behavior.
            line = file.entry_line
            add(file.path, line, f"A declaration or entry point in {file.path} appears near L{line}.")
        elif overview:
            trace.append(AgentStep(agent=self.name, action="describe_repository", detail="Summarize indexed file types and directories without inferring a runtime call graph"))
            languages = ", ".join(f"{name}: {count}" for name, count in sorted(summary["languages"].items(), key=lambda item: -item[1])[:5])
            directories = ", ".join(f"{name}: {count}" for name, count in sorted(summary["directories"].items(), key=lambda item: -item[1])[:6])
            preface = f"osTicket static overview (commit {info.commit_sha[:12]}):\nIndexed {summary['files']} text files. Languages: {languages}.\nFiles by directory: {directories}.\nEntry points located in the current source snapshot:\n"
            anchors = [("open.php", "Ticket::create"), ("scp/login.php", "StaffAuthenticationBackend::process"),
                       ("api/http.php", "url_post"), ("include/class.ticket.php", "class Ticket ")]
            for path, anchor in anchors:
                file = tools.get_file_info(path, anchor)
                if file and file.anchor_line:
                    number = file.anchor_line
                    add(path, number, f"{path}:L{number} contains `{anchor.strip()}`, a starting point for inspecting this entry point.")
        else:
            # Exact identifiers supplied by the user take precedence over the
            # English concept aliases; a missing symbol must not fall back to
            # a loosely related generic answer.
            clean_q = re.sub(r"https?://\S+", "", q)
            explicit = [term for term in re.findall(r"[a-z_][a-z_0-9]*|\b\d{3}\b", clean_q) if term not in STOP_WORDS]
            identifiers = [word.lower() for word in re.findall(r"[A-Za-z_][A-Za-z_0-9]*", task.question)
                           if word.lower() != "osticket" and (re.search(r"[a-z][A-Z]", word) or re.search(r"[a-z]_+[a-z]", word))]
            aliases = [term for concept, words in CONCEPTS.items() if re.search(r"\b" + concept + r"\b", q) for term in words]
            terms = identifiers or list(dict.fromkeys(explicit + aliases))
            if not terms:
                return result("needs_clarification", "missing_code_target", "A specific code-analysis target is required.", repository=info,
                              clarifying_questions=["Ask for a repository overview, login/ticket/API code locations, or provide a file path, function name or error text."])
            preferred = ()
            if "login" in q:
                preferred = ("scp/login.php", "include/class.auth.php", "login.php") if any(word in q for word in ("staff", "agent", "employee")) else ("login.php", "scp/login.php", "include/class.auth.php")
            elif "ticket" in q and any(word in q for word in ("creation", "new", "create")):
                preferred = ("open.php", "include/api.tickets.php", "include/class.ticket.php")
            elif "api" in q:
                preferred = ("include/class.api.php", "include/api.tickets.php", "api/http.php", "include/api.cron.php")
            hits = tools.search_code(terms, preferred_paths=preferred)
            trace.append(AgentStep(agent=self.name, action="search_code", detail=f"Search {len(terms)} identifiers/topic terms and find {len(hits)} candidate files"))
            for file, line in hits:
                add(file.path, line, f"{file.path}:L{line} matches a query identifier or topic term.")
            preface = "The following code and declaration matches do not establish the cause of a runtime failure.\n"
        if not sources:
            return result("insufficient_evidence", "no_code_evidence", "No sufficient code evidence was found in this index. Provide an exact file path, function name or error text.", repository=info)
        trace.append(AgentStep(agent=self.name, action="return_evidence", detail=f"Return {len(sources)} commit-pinned code excerpts with line numbers"))
        answer = preface + "\n".join(f"{i}. {claim.text}" for i, claim in enumerate(claims, 1))
        return result("answered", "code_evidence_found", "The Code Analyzer completed static retrieval. Expand the excerpts to inspect the evidence.", answer=answer, claims=claims, sources=sources, repository=info)
