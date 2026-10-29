"""Real MCP stdio client. Each analysis owns and closes its server subprocess.

The deterministic agent runs in an AnyIO worker; tool calls cross back into the
same async session. No nested event loops or fake in-process MCP shortcuts.
"""
import json
import logging
import sys
from datetime import timedelta
from functools import partial
from time import perf_counter
from urllib.parse import quote

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.exceptions import McpError
from pydantic import ValidationError

from app.agents.repository import MANIFEST, ROOT, REPOSITORY_URL
from app.mcp_contract import MAX_REPLY_BYTES, TOOLS, SearchFailure, ToolReply
from app.models import AgentStep, AskResponse, CodeCitation, RepositoryInfo
from app.retrieval import FileSummary

logger = logging.getLogger("support_system")


def server_parameters(store):
    # This configuration comes from application startup, never the /ask body.
    expected = store.expected_commit or json.loads(MANIFEST.read_text(encoding="utf-8"))["commit_sha"]
    return StdioServerParameters(command=sys.executable, args=["-m", "app.mcp_server"], cwd=str(ROOT),
                                 env={"PYTHONUTF8": "1", "FILE_SEARCH_INDEX_PATH": str(store.path.resolve()),
                                      "FILE_SEARCH_COMMIT": expected}), expected


class MCPGateway:
    def __init__(self, session, expected_commit, trace):
        self.session = session
        self.expected_commit = expected_commit
        self.trace = trace
        self.digest = None

    async def call(self, name, arguments):
        if name not in TOOLS:
            raise SearchFailure("mcp_tool_not_allowed")
        started = perf_counter()
        result = await self.session.call_tool(name, arguments)
        raw = result.structuredContent
        if raw is None:
            raise SearchFailure("mcp_tool_error" if result.isError else "mcp_invalid_response")
        serialized = json.dumps(raw, ensure_ascii=False)
        if len(serialized.encode("utf-8")) > MAX_REPLY_BYTES:
            raise SearchFailure("mcp_response_too_large")
        try:
            reply = ToolReply.model_validate(raw)
        except ValidationError as exc:
            raise SearchFailure("mcp_invalid_response") from exc
        if bool(result.isError) != reply.is_error:
            raise SearchFailure("mcp_invalid_response")
        if reply.is_error:
            raise SearchFailure(reply.error_type or "mcp_tool_error", reply.retryable)
        if reply.error_type or reply.commit_sha != self.expected_commit or not reply.index_sha256:
            raise SearchFailure("mcp_snapshot_mismatch")
        if self.digest is not None and reply.index_sha256 != self.digest:
            raise SearchFailure("mcp_snapshot_mismatch")
        self.digest = reply.index_sha256
        elapsed = round((perf_counter() - started) * 1000, 3)
        self.trace.append(AgentStep(agent="File Search MCP", action=f"mcp.tools/call:{name}",
                                   detail=f"stdio · {elapsed} ms · structured result: {len(serialized)} characters (not tokens)"))
        logger.info("mcp_tool=%s latency_ms=%s result_chars=%s", name, elapsed, len(serialized))
        return reply.data

    def _call(self, name, **arguments):
        return anyio.from_thread.run(self.call, name, arguments)

    def describe_repository(self):
        data = self._call("describe_repository")
        data["info"] = RepositoryInfo.model_validate(data["info"])
        if data["info"].commit_sha != self.expected_commit or data["info"].index_sha256 != self.digest:
            raise SearchFailure("mcp_snapshot_mismatch")
        return data

    def get_file_info(self, path, anchor=None):
        data = self._call("get_file_info", path=path, anchor=anchor)
        return FileSummary.model_validate(data["file"]) if data["file"] is not None else None

    def search_code(self, terms, limit=4, preferred_paths=()):
        data = self._call("search_code", terms=terms[:10], limit=limit, preferred_paths=list(preferred_paths))
        if len(data["hits"]) > limit:
            raise SearchFailure("mcp_invalid_response")
        return [(FileSummary.model_validate(hit["file"]), hit["line"]) for hit in data["hits"]]

    def read_file(self, path, line=1, limit=18, mode="lines"):
        data = self._call("read_file", path=path, line=line, limit=limit, mode=mode)
        if data["source"] is None:
            return None
        source = CodeCitation.model_validate(data["source"])
        if (source.commit_sha != self.expected_commit or source.repository != REPOSITORY_URL
                or source.file_path != path or not 1 <= source.line_start <= source.line_end
                or source.line_end - source.line_start + 1 > limit
                or len(source.evidence.split("\n")) != source.line_end - source.line_start + 1):
            raise SearchFailure("mcp_invalid_response")
        expected_url = f"{REPOSITORY_URL}/blob/{self.expected_commit}/{quote(path, safe='/')}#L{source.line_start}-L{source.line_end}"
        if source.url != expected_url or source.chunk_id != f"{path}:{source.line_start}-{source.line_end}":
            raise SearchFailure("mcp_invalid_response")
        if mode == "symbol":
            if (source.matched_line != line or not source.line_start <= line <= source.line_end
                    or len(source.evidence) > 12000):
                raise SearchFailure("mcp_invalid_response")
            if source.context_kind != "line_window":
                if (not source.symbol_name or source.symbol_line_start is None or source.symbol_line_end is None
                        or not 1 <= source.symbol_line_start <= source.line_start <= source.line_end <= source.symbol_line_end):
                    raise SearchFailure("mcp_invalid_response")
                complete = (source.line_start, source.line_end) == (source.symbol_line_start, source.symbol_line_end)
                if complete != (source.context_kind == "complete_symbol"):
                    raise SearchFailure("mcp_invalid_response")
        return source


def classify(exc):
    if isinstance(exc, BaseExceptionGroup):
        errors = [classify(child) for child in exc.exceptions]
        return next((error for error in errors if not error.retryable), errors[0])
    if isinstance(exc, SearchFailure):
        return exc
    if isinstance(exc, (ValidationError, ValueError, KeyError, TypeError)):
        return SearchFailure("mcp_invalid_response")
    if isinstance(exc, TimeoutError):
        return SearchFailure("mcp_timeout", True)
    if isinstance(exc, McpError):
        if exc.error.code in {408, -32001}:
            return SearchFailure("mcp_timeout", True)
        if exc.error.code in {-32600, -32601, -32602}:
            return SearchFailure("mcp_protocol_error")
    return SearchFailure("mcp_unavailable", True)


async def with_gateway(store, operation, trace, timeout=25):
    """One retry for transport failures; invalid parameters/index errors never retry."""
    try:
        parameters, expected = server_parameters(store)
        with anyio.fail_after(timeout):
            for attempt in range(2):
                try:
                    async with stdio_client(parameters) as (read, write):
                        async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=5)) as session:
                            await session.initialize()
                            listed = await session.list_tools()
                            if not TOOLS <= {tool.name for tool in listed.tools}:
                                raise SearchFailure("mcp_required_tool_missing")
                            trace.append(AgentStep(agent="File Search MCP", action="mcp.initialize+tools/list",
                                                   detail=f"Real stdio session; discovered and allowed {len(TOOLS)} read-only tools; attempt {attempt + 1}"))
                            gateway = MCPGateway(session, expected, trace)
                            return await anyio.to_thread.run_sync(partial(operation, gateway))
                except Exception as exc:
                    failure = classify(exc)
                    if not failure.retryable or attempt == 1:
                        raise failure from exc
                    trace.append(AgentStep(agent="File Search MCP", action="mcp.retry", detail="Transport failure; reconnect the read-only session once"))
                    await anyio.sleep(0.1)
    except Exception as exc:
        raise classify(exc) from exc


def run_analysis(agent, task):
    trace = []
    try:
        result = anyio.run(with_gateway, agent.store, partial(agent._run, task), trace)
        # _run has a legacy local-index handler. Preserve the distinction for MCP.
        if result.reason_code == "repository_index_unavailable":
            result.message = "File Search MCP cannot read the pinned index. Run python -m scripts.index_repository."
    except SearchFailure as exc:
        trace.append(AgentStep(agent="File Search MCP", action="mcp.error", detail=f"{exc.error_type} · retryable={exc.retryable}"))
        result = AskResponse(status="upstream_error", reason_code=exc.error_type,
                             message="File Search MCP failed. Check dependencies, index and service logs. A tool failure is not an empty search result.",
                             mode="static_code_analysis", delegated_to=agent.name,
                             scope="Static code retrieval at the pinned osTicket commit.", retryable=exc.retryable, agent_trace=trace)
    result.retrieval_backend = "mcp_stdio"
    return result


def get_repository_info(store):
    return anyio.run(with_gateway, store, lambda gateway: gateway.describe_repository()["info"], [])
