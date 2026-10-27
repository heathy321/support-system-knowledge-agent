"""Integration regressions against the locally indexed, pinned osTicket commit."""
import json
import argparse
import hashlib
import re
from collections import Counter
from statistics import median
from pathlib import Path

from app.agents.customer_support import CustomerSupportAgent
from app.agents.code_analyzer import CodeAnalyzerAgent
from app.models import AskRequest

ROOT = Path(__file__).resolve().parent


def run(backend="local"):
    cases = json.loads((ROOT / "code_cases.json").read_text(encoding="utf-8"))
    agent = CustomerSupportAgent(code_analyzer=CodeAnalyzerAgent(backend=backend))
    index, digest = agent.code_analyzer.store.load()
    files = {file.path: file for file in index.files}
    rows = []
    citation_checks = []
    focus_checks = []
    context_counts = Counter()
    parity_checks = []
    comparison = CustomerSupportAgent(code_analyzer=CodeAnalyzerAgent(backend="local")) if backend == "mcp_stdio" else None
    for case in cases:
        response = agent.ask(AskRequest(question=case["question"], task="code_analysis", file_path=case.get("file_path")))
        paths = [source.file_path for source in response.sources]
        passed = response.status == case["expected_status"] and response.reason_code == case["expected_reason"]
        if case.get("first_file"):
            passed = passed and bool(paths) and paths[0] == case["first_file"]
        passed = passed and set(case.get("required_files", [])) <= set(paths)
        if response.status == "answered":
            passed = passed and bool(response.sources)
            for source in response.sources:
                valid = (source.file_path in files and source.evidence == "\n".join(files[source.file_path].lines[source.line_start - 1:source.line_end])
                         and source.commit_sha == index.commit_sha)
                focus = source.matched_line is not None and source.line_start <= source.matched_line <= source.line_end
                citation_checks.append(valid)
                focus_checks.append(focus)
                context_counts[source.context_kind] += 1
                passed = passed and valid and focus and len(source.evidence) <= 12000 and source.line_end - source.line_start < 80
                if case.get("all_sources_contain"):
                    passed = passed and bool(re.search(r"(?<!\w)" + re.escape(case["all_sources_contain"]) + r"(?!\w)", source.evidence))
            if case.get("first_symbol"):
                passed = passed and response.sources[0].symbol_name == case["first_symbol"]
            if case.get("first_range"):
                passed = passed and [response.sources[0].line_start, response.sources[0].line_end] == case["first_range"]
            if case.get("first_context_kind"):
                passed = passed and response.sources[0].context_kind == case["first_context_kind"]
            ids = {source.chunk_id for source in response.sources}
            passed = passed and all(claim.citation_ids and set(claim.citation_ids) <= ids for claim in response.claims)
        passed = passed and response.delegated_to == "代码分析器" and response.agent_trace[0].action == "delegate_code_analysis"
        if backend == "mcp_stdio":
            passed = passed and response.retrieval_backend == backend and any(s.action == "mcp.initialize+tools/list" for s in response.agent_trace)
            local = comparison.ask(AskRequest(question=case["question"], task="code_analysis", file_path=case.get("file_path")))
            exclude = {"latency_ms", "request_id", "agent_trace", "retrieval_backend"}
            parity = response.model_dump(exclude=exclude) == local.model_dump(exclude=exclude)
            parity_checks.append(parity)
            passed = passed and parity
        rows.append({"id": case["id"], "status": response.status, "reason": response.reason_code, "files": paths,
                     "passed": bool(passed), "latency_ms": response.latency_ms,
                     "evidence_chars": sum(len(s.evidence) for s in response.sources),
                     "contexts": [{"file": s.file_path, "kind": s.context_kind, "symbol": s.symbol_name,
                                   "line_start": s.line_start, "line_end": s.line_end, "matched_line": s.matched_line} for s in response.sources]})
    report = {"backend": backend, "repository": index.repository, "commit_sha": index.commit_sha, "index_sha256": digest,
              "cases": len(rows), "passed": sum(row["passed"] for row in rows), "results": rows,
              "cases_sha256": hashlib.sha256((ROOT / "code_cases.json").read_bytes()).hexdigest(),
              "citation_integrity": {"passed": sum(citation_checks), "total": len(citation_checks)},
              "hit_line_visible": {"passed": sum(focus_checks), "total": len(focus_checks)},
              "backend_parity": {"passed": sum(parity_checks), "total": len(parity_checks)} if comparison else None,
              "context_counts": dict(context_counts), "latency_p50_ms": median(row["latency_ms"] for row in rows),
              "limitations": "Hand-authored development regressions, not held-out evaluation. Lexical declaration boundaries are not AST validation. Context counts describe coverage, not correctness. Latency includes per-request process startup for MCP; parity comparison latency is excluded."}
    output = "code-mcp-latest.json" if backend == "mcp_stdio" else "code-latest.json"
    (ROOT / output).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=True))
    return 0 if all(row["passed"] for row in rows) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=["local", "mcp_stdio"], default="local")
    raise SystemExit(run(parser.parse_args().backend))
