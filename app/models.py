from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Status = Literal["answered", "needs_clarification", "insufficient_evidence", "upstream_error"]
Fare = Literal["minimum", "standard", "standard_plus"]
Topic = Literal["carry_on", "checked_limits", "checked_allowance", "change", "cancel"]


class Context(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    airline: str | None = Field(default=None, min_length=1, max_length=60)
    fare_type: Fare | None = None
    reason: Literal["voluntary", "involuntary"] | None = None
    booking_channel: Literal["direct", "agency"] | None = None


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question: str = Field(min_length=2, max_length=1500)
    context: Context = Field(default_factory=Context)
    task: Literal["auto", "travel_policy", "code_analysis"] = "auto"
    repository: str | None = Field(default=None, max_length=250)
    file_path: str | None = Field(default=None, max_length=250)


class Citation(BaseModel):
    chunk_id: str
    title: str
    url: str
    section: str
    evidence: str
    evidence_kind: Literal["curated_paraphrase"] = "curated_paraphrase"
    reviewed_at: date


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


class RepositoryInfo(BaseModel):
    url: str
    commit_sha: str
    indexed_at: str
    indexed_files: int
    skipped_files: int
    index_sha256: str


class AskResponse(BaseModel):
    status: Status
    answer: str | None = None
    claims: list[Claim] = Field(default_factory=list)
    sources: list[Citation | CodeCitation] = Field(default_factory=list)
    clarifying_questions: list[str] = Field(default_factory=list)
    reason_code: str
    message: str
    scope: str = "Peach 公开政策摘要；仅供一般政策检索，不判定具体订单。"
    mode: Literal["offline_evidence", "static_code_analysis"] = "offline_evidence"
    context: Context = Field(default_factory=Context)
    latency_ms: float = 0
    request_id: str = ""
    corpus_version: str | None = None
    corpus_sha256: str | None = None
    agent: str = "客服协助代理"
    delegated_to: str | None = None
    agent_trace: list[AgentStep] = Field(default_factory=list)
    repository: RepositoryInfo | None = None
    retrieval_backend: Literal["local", "mcp_stdio"] | None = None
    retryable: bool | None = None
