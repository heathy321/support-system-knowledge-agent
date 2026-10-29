"""Opt-in live smoke suite, not an answer-quality benchmark. Dry-run default."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from app.main import VERSION
from scripts.try_gemini import execute, DEFAULT_QUESTION

CASES = [
    ("doc_fields", DEFAULT_QUESTION, "documentation"),
    ("code_401", "Which code should I inspect when the osTicket API returns 401?", "code_analysis"),
    ("combined_auth", "What authentication header does the documentation require? Locate the requireApiKey function as well.", "combined"),
]


def run(live=False, limit=1, backend="local"):
    if limit not in (1, 2, 3):
        raise ValueError("limit must be 1, 2 or 3")
    rows = []
    failed = False
    for case_id, question, task in CASES[:limit]:
        result, code = execute(question, task, backend, live)
        rows.append({"case": case_id, "operational_success": code == 0, **result})
        if code:
            failed = True
            break  # No automatic retries; stop spending after the first failure.
    report = {"app_version": VERSION, "created_at": datetime.now(timezone.utc).isoformat(),
              "live": live, "backend": backend, "request_ceiling": limit if live else 0,
              "completed_cases": len(rows), "results": rows,
              "semantic_quality": "unassessed", "billed_cost": "not_measured",
              "limitations": "Same-author smoke cases. Operational success is not semantic accuracy. Dry-run latency is not model latency."}
    if live:
        # Separate from offline and immutable acceptance reports. Ignored by Git.
        Path(__file__).with_name("gemini-live-latest.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return int(failed)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Permit potentially billable Gemini requests")
    parser.add_argument("--limit", type=int, choices=[1, 2, 3], default=1)
    parser.add_argument("--backend", choices=["local", "mcp_stdio"], default="local")
    args = parser.parse_args()
    raise SystemExit(run(args.live, args.limit, args.backend))
