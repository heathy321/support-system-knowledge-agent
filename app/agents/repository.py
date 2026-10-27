"""Read-only code index. Never read a query-supplied filesystem path."""
import hashlib
import json
import re
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, Field, model_validator

ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_URL = "https://github.com/osTicket/osTicket"
DEFAULT_INDEX = ROOT / "data" / "indexes" / "osticket.json"
MANIFEST = ROOT / "knowledge" / "repositories.json"
MAX_INDEX_BYTES = 40_000_000


class RepositoryUnavailable(Exception):
    pass


def valid_path(value: str) -> bool:
    path = PurePosixPath(value)
    return bool(value and not path.is_absolute() and "\\" not in value and ":" not in value
                and not any(part in {"..", ".git"} or part.startswith(".") for part in path.parts)
                and not any(ord(char) < 32 for char in value))


class Symbol(BaseModel):
    name: str
    kind: str
    line: int = Field(ge=1)


class CodeFile(BaseModel):
    path: str
    language: str
    lines: list[str] = Field(max_length=50000)
    symbols: list[Symbol]

    @model_validator(mode="after")
    def validate_source(self):
        if (not valid_path(self.path) or not self.lines or any(s.line > len(self.lines) for s in self.symbols)
                or any(len(line) > 2000 for line in self.lines)):
            raise ValueError("Invalid indexed source")
        return self


class RepositoryIndex(BaseModel):
    schema_version: int = 1
    repository: str
    commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    indexed_at: str
    skipped_files: int = Field(ge=0)
    files: list[CodeFile] = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def validate_repository(self):
        if self.schema_version != 1 or self.repository != REPOSITORY_URL or len({f.path for f in self.files}) != len(self.files):
            raise ValueError("Invalid repository index")
        return self


class RepositoryStore:
    def __init__(self, path: Path = DEFAULT_INDEX, expected_commit: str | None = None):
        self.path = path
        self.expected_commit = expected_commit
        self._cached = None
        self._stamp = None

    def load(self) -> tuple[RepositoryIndex, str]:
        try:
            expected = self.expected_commit or json.loads(MANIFEST.read_text(encoding="utf-8"))["commit_sha"]
            stat = self.path.stat()
            if stat.st_size > MAX_INDEX_BYTES:
                raise ValueError("Index exceeds size limit")
            stamp = (stat.st_mtime_ns, stat.st_size, expected)
            if self._cached is not None and self._stamp == stamp:
                return self._cached
            raw = self.path.read_bytes()
            index = RepositoryIndex.model_validate_json(raw)
            if index.commit_sha != expected:
                raise ValueError("Index commit differs from repository manifest")
            self._cached = (index, hashlib.sha256(raw).hexdigest())
            self._stamp = stamp
            return self._cached
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise RepositoryUnavailable("Code index unavailable") from exc


def extract_symbols(lines: list[str], language: str) -> list[dict]:
    """Lexical declaration scan; not an AST or complete symbol table."""
    pattern = re.compile(r"\b(class|interface|trait|function)\s+&?\s*([A-Za-z_][A-Za-z_0-9]*)")
    if language not in {"php", "js"}:
        return []
    result = []
    for number, line in enumerate(lines, 1):
        if line.lstrip().startswith(("//", "#", "*", "/*")):
            continue
        for match in pattern.finditer(line):
            result.append({"name": match[2], "kind": match[1], "line": number})
    return result
