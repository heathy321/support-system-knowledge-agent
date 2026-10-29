"""Preview by default. --live permits one call, or at most two with --task auto; no retries."""
import argparse
import json

from app.agents.code_analyzer import CodeAnalyzerAgent
from app.agents.customer_support import CustomerSupportAgent
from app.generation import GeminiClient, GeminiSettings, GenerationError
from app.models import AskRequest

DEFAULT_QUESTION = "Which fields are required to create a ticket through the API?"


def execute(question=DEFAULT_QUESTION, task="documentation", backend="local", live=False):
    # Validate before retrieval in live CLI runs. Dry runs never read a key.
    if live:
        try:
            GeminiSettings.from_env().validate()
        except GenerationError as exc:
            return {"live": True, "status": "configuration_error", "reason_code": exc.reason,
                    "model_requests": 0}, 1
    request = AskRequest(question=question, task=task, answer_mode="gemini" if live else "offline")
    result = CustomerSupportAgent(CodeAnalyzerAgent(backend=backend)).ask(request)
    if live:
        return {"live": True, "result": result.model_dump(),
                "limitations": "Live transport/output checks only; semantic correctness and billed cost require separate review."}, 0 if result.status == "answered" else 1
    preview = {"live": False, "model_requests": 0, "retrieval_status": result.status,
               "reason_code": result.reason_code, "citation_ids": [s.chunk_id for s in result.sources],
               "notice": "Dry run: no provider request, no key read; preview uses default model settings."}
    if result.status == "answered":
        try:
            payload = GeminiClient(GeminiSettings()).build_request(request, result)
            preview.update(payload_characters=len(json.dumps(payload, ensure_ascii=False)),
                           max_output_tokens=payload["generationConfig"]["maxOutputTokens"])
        except GenerationError as exc:
            preview["reason_code"] = exc.reason
            return preview, 1
    return preview, 0 if result.status == "answered" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Allow model calls: at most one, or two with --task auto")
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    parser.add_argument("--task", choices=["auto", "documentation", "code_analysis", "combined"], default="documentation")
    parser.add_argument("--backend", choices=["local", "mcp_stdio"], default="local")
    args = parser.parse_args()
    if not 2 <= len(args.question) <= 1500:
        parser.error("Question length must be 2–1500 characters")
    report, code = execute(args.question, args.task, args.backend, args.live)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
