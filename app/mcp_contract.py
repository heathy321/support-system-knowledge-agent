"""Application error envelope inside standard MCP CallToolResult."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from app.agents.repository import RepositoryUnavailable

TOOLS = frozenset({"describe_repository", "search_code", "get_file_info", "read_file"})
MAX_REPLY_BYTES = 250_000


class ToolReply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_error: bool = False
    error_type: Literal["invalid_arguments", "repository_index_unavailable", "internal_error"] | None = None
    retryable: bool = False
    data: dict = Field(default_factory=dict)
    commit_sha: str | None = None
    index_sha256: str | None = None


class SearchFailure(RepositoryUnavailable):
    def __init__(self, error_type: str, retryable: bool = False):
        super().__init__(error_type)
        self.error_type = error_type
        self.retryable = retryable
