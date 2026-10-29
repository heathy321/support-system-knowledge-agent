import os
from pathlib import Path

from fastapi import FastAPI, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.models import AskRequest, AskResponse, ResetConversation
from app.conversation import ClarificationMemory
from app.agents.customer_support import CustomerSupportAgent
from app.agents.code_analyzer import CodeAnalyzerAgent
from app.mcp_contract import TOOLS
from app.agents.repository import RepositoryUnavailable, REPOSITORY_URL
from app.documentation import DocumentUnavailable

STATIC = Path(__file__).resolve().parent / "static"
VERSION = "0.12.0"


def create_app(assistant: CustomerSupportAgent | None = None) -> FastAPI:
    app = FastAPI(title="Support System Knowledge Agent / Support System Agent", version=VERSION,
                  description="Ask one support question. Automatic evidence routing and operator-configured Gemini synthesis with engineering handoff.")
    app.state.assistant = assistant or CustomerSupportAgent(code_analyzer=CodeAnalyzerAgent(
        backend=os.environ.get("CODE_SEARCH_BACKEND", "mcp_stdio")))
    app.state.clarifications = ClarificationMemory()

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path == "/" or request.url.path.startswith("/static/"):
            response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
            response.headers["Cache-Control"] = "no-cache"
        return response

    def repository_status(health=False):
        base = {"app_version": VERSION, "mode": "static_code_analysis", "repository": REPOSITORY_URL,
                "retrieval_backend": app.state.assistant.code_analyzer.backend}
        try:
            info = app.state.assistant.code_analyzer.repository_info()
        except RepositoryUnavailable as exc:
            return JSONResponse(status_code=503, content={**base, "status": "degraded" if health else "upstream_error",
                "reason_code": getattr(exc, "error_type", "repository_index_unavailable"), "retryable": getattr(exc, "retryable", False)})
        return {**base, **info.model_dump(), "repository": info.url, "status": "ok" if health else "ready"}

    @app.get("/health")
    def health():
        """Independent branch readiness; a failed branch does not mask the other."""
        code = repository_status(health=True)
        code_ok = not isinstance(code, JSONResponse)
        docs = documentation_status()
        docs_ok = not isinstance(docs, JSONResponse)
        content = {"app_version": VERSION, "status": "ok" if code_ok and docs_ok else "degraded",
                   "retrieval_backend": app.state.assistant.code_analyzer.backend,
                   "components": {"code": "ready" if code_ok else "unavailable", "documentation": "ready" if docs_ok else "unavailable"}}
        if code_ok:
            content["commit_sha"] = code["commit_sha"]
        return JSONResponse(status_code=200 if code_ok and docs_ok else 503, content=content)

    def documentation_status():
        try:
            corpus, info = app.state.assistant.documentation.load()
            return {"status": "ready", **info.model_dump(), "sources": [s.model_dump() for s in corpus.sources]}
        except DocumentUnavailable:
            return JSONResponse(status_code=503, content={"status": "upstream_error", "reason_code": "document_corpus_unavailable"})

    @app.get("/documentation")
    def documentation():
        return documentation_status()

    @app.get("/generation")
    def generation():
        """Local configuration only: never pings or bills the model provider."""
        return {"default_answer_mode": "auto", "intent_fallback": "gemini_when_rules_are_ambiguous", "max_model_requests_per_question": 2, **app.state.assistant.generation.configuration()}

    @app.get("/agents")
    def agents():
        return {"main_agent": CustomerSupportAgent.name, "mode": "deterministic_tools", "intent_routing": "rules_first_optional_gemini_fallback", "routes": ["documentation", "code_analysis", "combined"], "documentation_backend": "local_reviewed_summaries", "subagents": [
            {"name": "Code Analyzer", "repository": REPOSITORY_URL, "tools": sorted(TOOLS), "read_only": True,
             "retrieval_backend": app.state.assistant.code_analyzer.backend,
             "mcp_server": "support-system-file-search" if app.state.assistant.code_analyzer.backend == "mcp_stdio" else None}]}

    @app.get("/repositories")
    def repositories():
        return repository_status()

    @app.post("/ask", response_model=AskResponse)
    def ask(payload: AskRequest, response: Response):
        result = app.state.clarifications.ask(payload, app.state.assistant)
        response.headers["X-Request-ID"] = result.request_id
        response.headers["Cache-Control"] = "no-store"
        if result.status == "upstream_error":
            response.status_code = 503
        return result

    @app.post("/conversation/reset")
    def reset_conversation(payload: ResetConversation, response: Response):
        app.state.clarifications.reset(payload.clarification_id)
        response.headers['Cache-Control'] = 'no-store'
        return {"status": "cleared"}

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


app = create_app()
