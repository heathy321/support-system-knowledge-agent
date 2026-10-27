"""Local read-only retrieval engine, shared by direct and MCP transports."""
import re
from collections import Counter
from urllib.parse import quote
from app.agents.repository import CodeFile, RepositoryIndex, RepositoryStore, valid_path
from app.models import CodeCitation, RepositoryInfo
from app.agents.repository import Symbol
from pydantic import BaseModel, Field
from app.code_context import php_scopes, context_window


class FileSummary(BaseModel):
    path: str
    language: str
    line_count: int = Field(ge=1)
    symbols: list[Symbol]
    entry_line: int = Field(ge=1)
    anchor_line: int | None = None


def summarize(file: CodeFile, anchor: str | None = None, near: int | None = None) -> FileSummary:
    entry = file.symbols[0].line if file.symbols else next(
        (i for i, line in enumerate(file.lines, 1) if re.search(r"\b(?:require|include)(_once)?\b", line)), 1)
    anchor_line = next((i for i, line in enumerate(file.lines, 1)
                        if anchor and anchor in line and not line.lstrip().startswith(("//", "*"))), None)
    symbols = file.symbols[:8] if near is None else [s for s in file.symbols if max(1, near - 3) <= s.line < max(1, near - 3) + 18][:8]
    return FileSummary(path=file.path, language=file.language, line_count=len(file.lines),
                       symbols=symbols, entry_line=entry, anchor_line=anchor_line)


class LocalSearchGateway:
    """Bounded interface: file metadata and snippets, never the full index."""
    def __init__(self, store: RepositoryStore):
        self.store = store
        self.tools = None
        self.info = None

    def describe_repository(self) -> dict:
        index, digest = self.store.load()
        self.tools = RepositoryTools(index)
        self.info = RepositoryInfo(url=index.repository, commit_sha=index.commit_sha, indexed_at=index.indexed_at,
                                   indexed_files=len(index.files), skipped_files=index.skipped_files, index_sha256=digest)
        return {**self.tools.describe_repository(), "info": self.info}

    def get_file_info(self, path: str, anchor: str | None = None) -> FileSummary | None:
        file = self.tools.files.get(path) if valid_path(path) else None
        return summarize(file, anchor) if file else None

    def search_code(self, terms: list[str], limit: int = 4, preferred_paths: tuple[str, ...] = ()):
        return [(summarize(file, near=line), line) for file, line in self.tools.search_code(terms, limit, preferred_paths)]

    def read_file(self, path: str, line: int = 1, limit: int = 18, mode: str = "lines"):
        return self.tools.read_file(path, line, limit, mode)


class RepositoryTools:
    """Only an indexed file map is exposed, never arbitrary disk or network IO."""
    def __init__(self, index: RepositoryIndex):
        self.index = index
        self.files = {file.path: file for file in index.files}
        self._scopes = {}

    def describe_repository(self) -> dict:
        return {"languages": dict(Counter(f.language for f in self.index.files)),
                "directories": dict(Counter(f.path.split("/")[0] if "/" in f.path else "(root)" for f in self.index.files)),
                "files": len(self.index.files)}

    def read_file(self, path: str, line: int = 1, limit: int = 18, mode: str = "lines") -> CodeCitation | None:
        if mode not in {"lines", "symbol"} or not 1 <= limit <= (80 if mode == "symbol" else 24) or line < 1:
            raise ValueError("Invalid read window")
        if not valid_path(path) or path not in self.files:
            return None
        file = self.files[path]
        if line > len(file.lines):
            return None
        start = max(1, min(line, len(file.lines)))
        end = min(len(file.lines), start + limit - 1)
        scope, kind = None, "line_window"
        if mode == "symbol":
            if path not in self._scopes:
                self._scopes[path] = php_scopes(file.lines, file.language)
            start, end, scope, kind = context_window(file.lines, line, limit, self._scopes[path])
        excerpt = "\n".join(file.lines[start - 1:end])
        return CodeCitation(chunk_id=f"{path}:{start}-{end}", title=path,
                            url=f"{self.index.repository}/blob/{self.index.commit_sha}/{quote(path, safe='/')}#L{start}-L{end}",
                            section=f"{path} · L{start}–L{end}", evidence=excerpt,
                            repository=self.index.repository, commit_sha=self.index.commit_sha,
                            file_path=path, line_start=start, line_end=end, context_kind=kind,
                            matched_line=line if mode == "symbol" else None,
                            symbol_name=scope.name if scope else None, symbol_line_start=scope.start if scope else None,
                            symbol_line_end=scope.end if scope else None)

    def search_code(self, terms: list[str], limit: int = 4, preferred_paths: tuple[str, ...] = ()) -> list[tuple[CodeFile, int]]:
        results = []
        terms = list(dict.fromkeys(term.lower() for term in terms))[:10]
        patterns = [re.compile(r"(?<![a-z0-9_])" + re.escape(term) + r"(?![a-z0-9_])", re.I) for term in terms]
        required = {i for i, term in enumerate(terms) if term.isdigit()}
        for file in self.index.files:
            path_score = sum(1 for term in terms if term in file.path.lower())
            best_score, best_line = 0.0, 1
            matched_terms = set()
            for number, line in enumerate(file.lines, 1):
                hits = {i for i, pattern in enumerate(patterns) if pattern.search(line)}
                matched_terms.update(hits)
                # Prefer executable-looking declarations/uses over comments,
                # but do not claim this lexical heuristic is a PHP AST.
                comment = line.lstrip().startswith(("*", "//", "#", "/*"))
                score = len(hits) * (1 if comment else 3) + (2 if re.search(r"\b(?:function|class)\b", line) and hits else 0)
                # A status-code query must show the actual status-code hit,
                # rather than an unrelated declaration elsewhere in the file.
                if score > best_score and (not required or hits & required):
                    best_score, best_line = score, number
            if not matched_terms and not path_score:
                continue
            # If a query contains an exact status code, require that code in the
            # file. Generic API references cannot substantiate an unknown code.
            if not required <= matched_terms:
                continue
            score = best_score + len(matched_terms) * 2 + path_score * 2
            if file.language == "php":
                score += 2
            # For recognized workflows, present verified entry files before
            # supporting modules. A hint never bypasses actual query matching.
            priority = preferred_paths.index(file.path) if file.path in preferred_paths else len(preferred_paths)
            results.append((priority, score, file.path, file, best_line))
        results.sort(key=lambda row: (row[0], -row[1], row[2]))
        return [(file, line) for _, _, _, file, line in results[:limit]]


