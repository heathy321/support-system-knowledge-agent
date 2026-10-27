"""Run with python -m evals.run. Non-zero exit if a regression is found."""
import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path
from statistics import mean

from app.knowledge import KnowledgeStore, KnowledgeUnavailable
from app.models import AskRequest
from app.service import KnowledgeAssistant

ROOT = Path(__file__).resolve().parent
AS_OF = date(2026, 10, 26)
CASES = json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))


class ScenarioStore(KnowledgeStore):
    """Fault injection is test-only and is never exposed on the HTTP API."""
    def __init__(self, fault=None):
        super().__init__()
        self.fault = fault

    def load(self):
        if self.fault == "unavailable":
            raise KnowledgeUnavailable("Simulated store outage")
        corpus, digest = super().load()
        if self.fault == "stale":
            for doc in corpus.documents:
                doc.reviewed_at = date(2026, 1, 1)
        elif self.fault == "empty":
            corpus.chunks = []
        elif self.fault == "conflict":
            alternative = corpus.chunks[0].model_copy(update={"id": "test-conflict", "text": "测试冲突：重量要求不同。"})
            corpus.chunks.append(alternative)
        if self.fault:
            digest = hashlib.sha256(corpus.model_dump_json().encode()).hexdigest()
        return corpus, digest


def evaluate_case(case):
    result = KnowledgeAssistant(ScenarioStore(case.get("fault")), today=lambda: AS_OF).ask(
        AskRequest(question=case["question"], context=case["context"]))
    source_ids = {s.chunk_id for s in result.sources}
    status_ok = result.status == case["expected_status"]
    reason_ok = not case.get("expected_reason") or result.reason_code == case["expected_reason"]
    citations_ok = source_ids == set(case.get("expected_sources", []))
    contents_ok = all(text in (result.answer or "") for text in case.get("must_contain", []))
    links_ok = all(c.citation_ids and set(c.citation_ids) <= source_ids and
                   any(c.text == s.evidence and s.chunk_id in c.citation_ids for s in result.sources) for c in result.claims)
    contract_ok = bool(result.answer and result.claims and result.sources) if result.status == "answered" else not (result.answer or result.claims or result.sources)
    return {"id": case["id"], "expected": case["expected_status"], "actual": result.status,
            "reason_code": result.reason_code, "status_ok": status_ok, "reason_ok": reason_ok,
            "citations_ok": citations_ok, "contents_ok": contents_ok, "links_ok": links_ok,
            "contract_ok": contract_ok, "latency_ms": result.latency_ms,
            "passed": all([status_ok, reason_ok, citations_ok, contents_ok, links_ok, contract_ok])}


def run():
    results = [evaluate_case(case) for case in CASES]
    corpus, digest = KnowledgeStore().load()
    abstentions = [r for r in results if r["expected"] != "answered"]
    latencies = sorted(r["latency_ms"] for r in results)
    report = {
        "as_of": AS_OF.isoformat(), "corpus_version": corpus.version, "corpus_sha256": digest,
        "cases_sha256": hashlib.sha256((ROOT / "cases.json").read_bytes()).hexdigest(),
        "cases": len(results), "passed": sum(r["passed"] for r in results),
        "status_accuracy": mean(r["status_ok"] for r in results),
        "citation_id_accuracy": mean(r["citations_ok"] for r in results),
        "unsupported_answer_rate": mean(r["actual"] == "answered" for r in abstentions),
        "latency_p50_ms": latencies[len(latencies) // 2],
        "latency_p95_ms": latencies[min(len(latencies) - 1, int(len(latencies) * .95))],
        "expected_status_counts": dict(Counter(r["expected"] for r in results)),
        "limitations": "Hand-authored regression set, includes synthetic fault cases; not a held-out benchmark or semantic entailment assessment. Latency measures in-process execution only.",
        "results": results,
    }
    (ROOT / "latest.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "results"}, indent=2, ensure_ascii=False))
    for row in results:
        if not row["passed"]:
            print("FAIL", row)
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(run())
