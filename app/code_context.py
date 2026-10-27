"""Conservative PHP lexical boundaries, not an AST or runtime analysis.

Mask strings/comments before matching braces. Unsupported mixed templates,
heredocs and non-PHP files deliberately fall back to a bounded line window.
"""
import re
from bisect import bisect_right
from dataclasses import dataclass


@dataclass(frozen=True)
class CodeScope:
    name: str
    kind: str
    start: int
    end: int


def mask_php(text: str) -> str | None:
    out = list(text)
    state = "code"
    i = 0
    while i < len(text):
        char = text[i]
        pair = text[i:i + 2]
        if state == "line":
            if char == "\n":
                state = "code"
            else:
                out[i] = " "
        elif state == "block":
            if pair == "*/":
                out[i:i + 2] = "  "
                state = "code"
                i += 2
                continue
            if char != "\n":
                out[i] = " "
        elif state in {"'", '"', "`"}:
            if char != "\n":
                out[i] = " "
            if char == "\\":
                if i + 1 < len(text) and text[i + 1] != "\n":
                    out[i + 1] = " "
                i += 2
                continue
            if char == state:
                state = "code"
        else:
            if pair == "?>":
                if text[i + 2:].strip():
                    return None
                out[i:i + 2] = "  "
                i += 2
                continue
            if text[i:i + 3] == "<<<" or pair == "#[":
                return None
            if pair in {"//", "/*"}:
                out[i:i + 2] = "  "
                state = "line" if pair == "//" else "block"
                i += 2
                continue
            if char == "#":
                out[i] = " "
                state = "line"
            elif char in {"'", '"', "`"}:
                out[i] = " "
                state = char
        i += 1
    return "".join(out) if state in {"code", "line"} else None


def php_scopes(lines: list[str], language: str) -> list[CodeScope]:
    if language != "php":
        return []
    masked = mask_php("\n".join(lines))
    if masked is None:
        return []
    stack, pairs = [], {}
    for pos, char in enumerate(masked):
        if char == "{":
            stack.append(pos)
        elif char == "}":
            if not stack:
                return []
            pairs[stack.pop()] = pos
    if stack:
        return []
    newlines = [-1] + [match.start() for match in re.finditer("\n", masked)]
    scopes = []
    declaration = re.compile(r"\b(function|class|interface|trait|enum)\s+&?\s*([A-Za-z_][A-Za-z_0-9]*)\b")
    for match in declaration.finditer(masked):
        # Ignore anonymous expressions and abstract methods; only a body brace
        # outside signature parentheses/brackets can begin a named scope.
        depth = 0
        for pos in range(match.end(), len(masked)):
            char = masked[pos]
            if char in "([":
                depth += 1
            elif char in ")]":
                depth -= 1
            elif depth == 0 and char == ";":
                break
            elif depth == 0 and char == "{":
                if pos in pairs:
                    scopes.append(CodeScope(match[2], match[1], bisect_right(newlines, match.start()),
                                            bisect_right(newlines, pairs[pos])))
                break
            if depth < 0:
                break
    return scopes


def context_window(lines: list[str], focus: int, limit: int, scopes: list[CodeScope], max_chars: int = 12000):
    """Choose the smallest enclosing declaration; retain the hit under every cap."""
    scope = min((s for s in scopes if s.start <= focus <= s.end), key=lambda s: s.end - s.start, default=None)
    lower, upper = (scope.start, scope.end) if scope else (1, len(lines))
    budget = limit if scope else min(limit, 24)
    start = max(lower, focus - budget // 2)
    end = min(upper, start + budget - 1)
    start = max(lower, end - budget + 1)
    # Grow outwards from the hit by whole lines. No hidden string truncation.
    left = right = focus
    size = len(lines[focus - 1])
    while left > start or right < end:
        moved = False
        if left > start and size + len(lines[left - 2]) + 1 <= max_chars:
            left -= 1
            size += len(lines[left - 1]) + 1
            moved = True
        if right < end and size + len(lines[right]) + 1 <= max_chars:
            size += len(lines[right]) + 1
            right += 1
            moved = True
        if not moved:
            break
    kind = "complete_symbol" if scope and left == scope.start and right == scope.end else "partial_symbol" if scope else "line_window"
    return left, right, scope, kind
