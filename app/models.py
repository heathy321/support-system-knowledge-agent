from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

Status = Literal["answered", "needs_clarification", "insufficient_evidence", "upstream_error"]
class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question: str = Field(min_length=2, max_length=1500)
    task: Literal["auto", "code_analysis", "documentation", "combined"] = "auto"
    repository: str | None = Field(default=None, max_length=250)
    file_path: str | None = Field(default=None, max_length=250)
    product_version: str | None = Field(default=None, max_length=30)
    answer_mode: Literal["auto", "offline", "gemini"] = "auto"
    clarification_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{43}$")
    _clarification_history: list[dict] = PrivateAttr(default_factory=list)
    _support_context: dict | None = PrivateAttr(default=None)


class ConversationInfo(BaseModel):
    state: Literal["complete", "awaiting_reply", "retry", "expired", "limit_reached", "unavailable", "busy"] = "complete"
    clarification_id: str | None = None
    user_turns: int = 1
    expires_in_seconds: int | None = None
    context_used: bool = False


class ResetConversation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    clarification_id: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")


class Claim(BaseModel):
    text: str
    citation_ids: list[str]


class CodeCitation(BaseModel):
    chunk_id: str
    title: str
    url: str
    section: str
    evidence: str
    evidence_kind: Literal["code_excerpt"] = "code_excerpt"
    repository: str
    commit_sha: str
    file_path: str
    line_start: int
    line_end: int
    context_kind: Literal["complete_symbol", "partial_symbol", "line_window"] = "line_window"
    matched_line: int | None = None
    symbol_name: str | None = None
    symbol_line_start: int | None = None
    symbol_line_end: int | None = None


class AgentStep(BaseModel):
    agent: str
    action: str
    detail: str


class DocumentCitation(BaseModel):
    chunk_id: str
    title: str
    url: str
    section: str
    evidence: str
    evidence_kind: Literal["curated_document_summary"] = "curated_document_summary"
    document_version: str
    reviewed_at: str
    fetched_at: str
    source_sha256: str


class DocumentInfo(BaseModel):
    corpus_version: str
    corpus_sha256: str
    document_version: str
    reviewed_at: str
    pages: int
    chunks: int
    code_version_relation: Literal["unverified"] = "unverified"


class BranchStatus(BaseModel):
    branch: Literal["documentation", "code_analysis"]
    status: Status
    reason_code: str


class RepositoryInfo(BaseModel):
    url: str
    commit_sha: str
    indexed_at: str
    indexed_files: int
    skipped_files: int
    index_sha256: str


class GenerationInfo(BaseModel):
    backend: Literal["offline", "gemini"] = "offline"
    status: Literal["not_requested", "skipped", "completed", "abstained", "error"] = "not_requested"
    model: str | None = None
    latency_ms: float = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    thought_tokens: int | None = None
    total_tokens: int | None = None


class AskResponse(BaseModel):
    status: Status
    answer: str | None = None
    claims: list[Claim] = Field(default_factory=list)
    sources: list[CodeCitation | DocumentCitation] = Field(default_factory=list)
    clarifying_questions: list[str] = Field(default_factory=list)
    reason_code: str
    message: str
    scope: str = "Static retrieval of public osTicket code. No code execution or runtime root-cause determination."
    mode: Literal["static_code_analysis", "documentation", "combined", "routing"] = "static_code_analysis"
    latency_ms: float = 0
    request_id: str = ""
    agent: str = "Support System Agent"
    delegated_to: str | None = None
    agent_trace: list[AgentStep] = Field(default_factory=list)
    repository: RepositoryInfo | None = None
    retrieval_backend: Literal["local", "mcp_stdio"] | None = None
    retryable: bool | None = None
    documentation: DocumentInfo | None = None
    warnings: list[str] = Field(default_factory=list)
    branches: list[BranchStatus] = Field(default_factory=list)
    generation: GenerationInfo = Field(default_factory=GenerationInfo)
    intent_generation: GenerationInfo = Field(default_factory=GenerationInfo)
    conversation: ConversationInfo = Field(default_factory=ConversationInfo)
    resolution: Literal["guidance_available", "checks_available", "resolved_reported", "clarification_needed", "engineering_review", "unresolved"] = "unresolved"
    support_checks: list[Claim] = Field(default_factory=list)
    follow_up_questions: list[str] = Field(default_factory=list)
    support_playbook: str | None = None
    next_step: str = ""
    handoff: dict | None = None
