import os
from pathlib import Path

from fastapi import FastAPI, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.knowledge import DEFAULT_CORPUS, KnowledgeStore, KnowledgeUnavailable
from app.models import AskRequest, AskResponse
from app.service import KnowledgeAssistant
from app.agents.customer_support import CustomerSupportAgent
from app.agents.code_analyzer import CodeAnalyzerAgent
from app.mcp_contract import TOOLS
from app.agents.repository import RepositoryUnavailable, REPOSITORY_URL

STATIC = Path(__file__).resolve().parent / "static"


def create_app(assistant: KnowledgeAssistant | CustomerSupportAgent | None = None) -> FastAPI:
    app = FastAPI(title="Customer Support Agent / 客服协助代理", version="0.4.0",
                  description="Travel policy retrieval and delegated, read-only osTicket code analysis. No paid model required.")
    if isinstance(assistant, CustomerSupportAgent):
        app.state.assistant = assistant
    else:
        policy = assistant or KnowledgeAssistant(KnowledgeStore(Path(os.environ.get("TRAVEL_OPS_KNOWLEDGE_PATH", DEFAULT_CORPUS))))
        app.state.assistant = CustomerSupportAgent(policy=policy, code_analyzer=CodeAnalyzerAgent(
            backend=os.environ.get("CODE_SEARCH_BACKEND", "mcp_stdio")))

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path == "/" or request.url.path.startswith("/static/"):
            response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        return response

    @app.get("/health")
    def health():
        try:
            corpus, digest = app.state.assistant.store.load()
        except KnowledgeUnavailable:
            return JSONResponse(status_code=503, content={"status": "degraded", "reason_code": "knowledge_unavailable"})
        today = app.state.assistant.today()
        reviewed = all(0 <= (today - d.reviewed_at).days <= corpus.review_window_days for d in corpus.documents)
        return {"status": "ok" if reviewed else "review_required", "mode": "offline_evidence", "app_version": "0.4.0",
                "corpus_version": corpus.version, "corpus_sha256": digest, "chunks": len(corpus.chunks),
                "documents": len(corpus.documents), "reviewed_at": min(d.reviewed_at for d in corpus.documents) if corpus.documents else None,
                "review_window_days": corpus.review_window_days}

    @app.get("/agents")
    def agents():
        return {"main_agent": "客服协助代理", "mode": "deterministic_tools", "subagents": [
            {"name": "代码分析器", "repository": REPOSITORY_URL,
             "tools": sorted(TOOLS), "read_only": True,
             "retrieval_backend": app.state.assistant.code_analyzer.backend,
             "mcp_server": "travel-ops-file-search" if app.state.assistant.code_analyzer.backend == "mcp_stdio" else None}]}

    @app.get("/repositories")
    def repositories():
        try:
            info = app.state.assistant.code_analyzer.repository_info()
        except RepositoryUnavailable as exc:
            return JSONResponse(status_code=503, content={"status": "upstream_error", "reason_code": getattr(exc, "error_type", "repository_index_unavailable"),
                                                         "retryable": getattr(exc, "retryable", False), "repository": REPOSITORY_URL})
        return {"status": "ready", "repository": info.url, **info.model_dump(),
                "retrieval_backend": app.state.assistant.code_analyzer.backend}

    @app.get("/knowledge")
    def knowledge():
        try:
            corpus, digest = app.state.assistant.store.load()
        except KnowledgeUnavailable:
            return JSONResponse(status_code=503, content={"status": "upstream_error", "reason_code": "knowledge_unavailable"})
        return {"version": corpus.version, "sha256": digest, "documents": [d.model_dump(mode="json") for d in corpus.documents],
                "chunk_count": len(corpus.chunks), "review_window_days": corpus.review_window_days}

    @app.post("/ask", response_model=AskResponse)
    def ask(payload: AskRequest, response: Response):
        result = app.state.assistant.ask(payload)
        response.headers["X-Request-ID"] = result.request_id
        response.headers["Cache-Control"] = "no-store"
        if result.status == "upstream_error":
            response.status_code = 503
        return result

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


app = create_app()
