from app.agents.repository import CodeFile, RepositoryIndex, REPOSITORY_URL, extract_symbols
from app.code_context import php_scopes
from app.retrieval import RepositoryTools
import pytest


def tools_for(text, language="php"):
    lines = text.splitlines()
    file = CodeFile(path=f"sample.{language}", language=language, lines=lines, symbols=extract_symbols(lines, language))
    return RepositoryTools(RepositoryIndex(repository=REPOSITORY_URL, commit_sha="a" * 40,
                                          indexed_at="2026-10-27", skipped_files=0, files=[file]))


def test_nested_method_returns_entire_body_not_its_class():
    text = """<?php
class Api {
    function check($x) {
        if ($x) {
            return 401;
        }
        return 200;
    }
    function next() { return 1; }
}
?>
"""
    tools = tools_for(text)
    source = tools.read_file("sample.php", 5, 80, "symbol")
    assert (source.line_start, source.line_end) == (3, 8)
    assert source.context_kind == "complete_symbol" and source.symbol_name == "check"
    assert source.matched_line == 5 and "function next" not in source.evidence
    assert source.evidence == "\n".join(text.splitlines()[2:8])


def test_braces_and_fake_declarations_in_strings_and_comments_do_not_define_scopes():
    lines = ["<?php", "/* function fake() { */", "function real() {",
             "  $text = 'escaped \\' quote } {';", '  $other = "function phantom() { }";',
             "  // }", "  # {", "  return 401;", "}"]
    scopes = php_scopes(lines, "php")
    assert [(s.name, s.start, s.end) for s in scopes] == [("real", 3, 9)]


def test_multiline_signature_and_abstract_method():
    text = """<?php
abstract class Api {
    abstract function missing($x);
    public function &check(
        $x = array('{' => '}')
    ): array
    {
        return array(401);
    }
}
"""
    source = tools_for(text).read_file("sample.php", 8, 80, "symbol")
    assert (source.line_start, source.line_end, source.symbol_name) == (4, 9, "check")
    assert "missing" not in source.evidence


@pytest.mark.parametrize("text,language", [
    ("<?php\nfunction a() {\nreturn 401;\n", "php"),
    ("<?php\nfunction a() { $s = <<<TXT\n401\nTXT;\n}\n", "php"),
    ("<?php function a() { return 401; } ?>\n<div>{</div>", "php"),
    ("<?php\n#[Attribute]\nfunction a() { return 401; }", "php"),
    ("function a() { return /[}]/.test('401'); }", "js"),
])
def test_unsupported_or_ambiguous_syntax_has_explicit_line_fallback(text, language):
    tools = tools_for(text, language)
    source = tools.read_file(f"sample.{language}", 1, 80, "symbol")
    assert source.context_kind == "line_window" and source.symbol_name is None
    assert source.line_end - source.line_start + 1 <= 24


def test_large_function_returns_partial_context_including_the_hit():
    text = "\n".join(["<?php", "function huge() {"] + ["  $x = 1;"] * 180 + ["  return 401;", "}"])
    source = tools_for(text).read_file("sample.php", 183, 80, "symbol")
    assert source.context_kind == "partial_symbol" and source.symbol_name == "huge"
    assert source.symbol_line_start == 2 and source.symbol_line_end == 184
    assert source.line_start <= 183 <= source.line_end
    assert source.line_end - source.line_start + 1 <= 80 and "401" in source.evidence


def test_character_budget_preserves_whole_lines_and_focus():
    text = "\n".join(["<?php", "function wide() {"] + ["  // " + "x" * 1800] * 20 + ["  return 401;", "}"])
    source = tools_for(text).read_file("sample.php", 15, 80, "symbol")
    assert source.context_kind == "partial_symbol"
    assert len(source.evidence) <= 12000
    assert source.line_start <= 15 <= source.line_end
    assert source.evidence == "\n".join(text.splitlines()[source.line_start - 1:source.line_end])


def test_status_query_focuses_on_status_hit_even_when_a_declaration_scores_higher():
    text = "\n".join(["<?php", "class Api {", "function api() { return 200; }"] + ["// padding"] * 50 +
                     ["function denied() {", "return 401;", "}", "}"])
    tools = tools_for(text)
    hits = tools.search_code(["api", "401"])
    assert len(hits) == 1
    file, line = hits[0]
    assert "401" in file.lines[line - 1]
    source = tools.read_file(file.path, line, 80, "symbol")
    assert "401" in source.evidence and source.symbol_name == "denied"


def test_unknown_line_is_not_silently_clamped_to_unrelated_code():
    tools = tools_for("<?php\nfunction a() {}")
    assert tools.read_file("sample.php", 999, 80, "symbol") is None
    with pytest.raises(ValueError):
        tools.read_file("sample.php", 1, 80, "lines")


def test_small_class_can_be_returned_as_complete_scope():
    tools = tools_for("<?php\nclass EmptyApi {\npublic $status = 401;\n}")
    source = tools.read_file("sample.php", 2, 80, "symbol")
    assert source.context_kind == "complete_symbol" and source.symbol_name == "EmptyApi"
    assert (source.line_start, source.line_end) == (2, 4)
