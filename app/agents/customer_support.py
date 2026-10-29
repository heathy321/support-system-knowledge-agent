"""Support-system agent: scope validation and explicit code-analyzer delegation."""
import logging
import re
from time import perf_counter
from uuid import uuid4

from app.agents.code_analyzer import CodeAnalysisTask, CodeAnalyzerAgent
from app.agents.repository import REPOSITORY_URL
from app.models import AgentStep, AskRequest, AskResponse, BranchStatus, GenerationInfo
from app.documentation import DocumentationRetriever, VERSION_WARNING
from app.generation import AnswerGeneration, GeminiClient
from app.intent_router import IntentRouter
from app.intent import has_doc_intent, has_code_intent, has_status_target, support_problem, needs_error_context
from app.support_checks import add_support_checks, continue_support_checks

logger = logging.getLogger("support_system")


class CustomerSupportAgent:
    name = "Support System Agent"

    def __init__(self, code_analyzer: CodeAnalyzerAgent | None = None, documentation: DocumentationRetriever | None = None, generation: AnswerGeneration | None = None, intent_router: IntentRouter | None = None):
        self.code_analyzer = code_analyzer or CodeAnalyzerAgent()
        self.documentation = documentation or DocumentationRetriever()
        self.generation = generation or AnswerGeneration()
        self.intent_router = intent_router or IntentRouter(self.generation.settings,
            self.generation.provider if isinstance(self.generation.provider, GeminiClient) else None)

    def ask(self, request: AskRequest) -> AskResponse:
        started = perf_counter()
        continued = continue_support_checks(request)
        if continued is not None:
            return self.finish(request, continued, list(continued.sources), started)
        intent_info = GenerationInfo()
        intent_trace = []
        q = request.question.lower()
        travel = bool(re.search(r"\b(peach|airlines?|baggage|luggage|flights?|airfare|rebooking)\b", q))
        code = bool(request.file_path or any(word in q for word in ("osticket", "source code", "code", "repository"))
                    or re.search(r"[a-z_/]+\.(?:php|js|sql)\b", q))
        if travel:
            result = AskResponse(
                status="needs_clarification" if code else "insufficient_evidence",
                reason_code="mixed_scope" if code else "outside_project_scope",
                message="This assistant supports osTicket documentation and code retrieval. Travel policies are outside its scope.",
                clarifying_questions=["Submit a separate osTicket code question or file path."] if code else [],
                agent_trace=[AgentStep(agent=self.name, action="scope_check", detail="The request is outside the support-system scope")])
        elif request.repository and request.repository.rstrip("/").removesuffix(".git").lower() != REPOSITORY_URL.lower():
            result = AskResponse(status="insufficient_evidence", reason_code="repository_not_supported", message="Only osTicket/osTicket is supported.")
        else:
            route = self.route(request)
            intent_result = None
            if route == "ambiguous":
                decision, intent_info, error = self.intent_router.decide(request)
                if error:
                    intent_trace.append(AgentStep(agent=self.name, action="intent_classification_failed", detail=error.reason))
                    intent_result = AskResponse(status="upstream_error", reason_code=error.reason, mode="routing",
                        message="Intent classification failed. Please retry manually later or contact the system maintainer.",
                        scope="No evidence retrieval or answer generation was performed.", retryable=error.retryable)
                elif decision:
                    intent_trace.append(AgentStep(agent=self.name, action="gemini_classify_intent",
                        detail=f"Validated allowlisted decision: {decision.decision}; no tools or query rewrites supplied by the model"))
                    if decision.decision in {"documentation", "code_analysis", "combined"}:
                        route = decision.decision
                    else:
                        clarify = decision.decision == "needs_clarification"
                        intent_result = AskResponse(status="needs_clarification" if clarify else "insufficient_evidence",
                            reason_code={"needs_clarification": "llm_intent_clarification", "outside_scope": "llm_outside_scope",
                                         "insufficient_evidence": "llm_topic_not_covered"}[decision.decision], mode="routing",
                            message="Please clarify what you mean." if clarify else (
                                "This assistant covers osTicket support cases, not booking or other external services."
                                if decision.decision == "outside_scope" else "The included knowledge does not cover this osTicket operation."),
                            clarifying_questions=[decision.clarification] if clarify else [],
                            scope="Model-assisted intent classification only. No documentation or code was retrieved; no policy or operational answer is established.")
            if intent_result is not None:
                result = intent_result
            elif route == "missing_error_context":
                result = AskResponse(status="needs_clarification", reason_code="missing_error_context", mode="routing",
                    message="The error code alone does not identify where the problem occurred.",
                    scope="Incident context clarification only. No documentation, code retrieval or model request is needed.",
                    clarifying_questions=["Where did the error appear, and what were you trying to do: signing in, creating a ticket through an integration, or another action? Include the full error message without API keys or customer information."],
                    agent_trace=[AgentStep(agent=self.name, action="clarify_error_context", detail="Ask for the affected workflow before retrieving possible error branches")])
            elif route == "ambiguous":
                result = AskResponse(status="needs_clarification", reason_code="ambiguous_intent", mode="routing",
                    message="I need a little more detail about the task or problem you are trying to solve.",
                    scope="Routing clarification only. No documentation or code tools have been called.",
                    clarifying_questions=["What were you trying to do, what happened, and what did you expect? Include the exact error message if available, without customer data or secrets."],
                    agent_trace=[AgentStep(agent=self.name, action="clarify_intent", detail="Insufficient routing signals; ask for clarification before retrieval")])
            elif route == "documentation" and request.file_path:
                result = AskResponse(status="needs_clarification", reason_code="conflicting_task", mode="documentation",
                    message="A code file was specified in documentation mode. Select combined retrieval or remove the file path.",
                    clarifying_questions=["Do you need documentation only, or both documentation and code?"])
            elif route == "code_analysis":
                result = self.ask_code(request)
            elif route == "documentation":
                result = self.documentation.ask(request.question, request.product_version)
                result.agent_trace.insert(0, AgentStep(agent=self.name, action="route_documentation", detail="Route the documentation intent to local reviewed summaries"))
            else:
                doc = self.documentation.ask(request.question, request.product_version)
                code_result = self.ask_code(request)
                branches = [BranchStatus(branch=name, status=r.status, reason_code=r.reason_code)
                            for name, r in [("documentation", doc), ("code_analysis", code_result)]]
                trace = [AgentStep(agent=self.name, action="route_combined", detail="Retrieve documentation and code independently; do not assume version alignment or mutual verification")]
                trace += doc.agent_trace + code_result.agent_trace
                common = dict(mode="combined", documentation=doc.documentation, repository=code_result.repository,
                    retrieval_backend=code_result.retrieval_backend, delegated_to=code_result.delegated_to,
                    branches=branches, warnings=[VERSION_WARNING], agent_trace=trace,
                    scope="Document summaries and pinned source excerpts are independent evidence. Version alignment is unverified; no production root cause is established.")
                if doc.status == code_result.status == "answered":
                    result = AskResponse(status="answered", reason_code="combined_evidence_found",
                        message="Both branches returned evidence. Check each source and its version independently.",
                        answer=doc.answer + "\n\nCode evidence:\n" + code_result.answer,
                        claims=doc.claims + code_result.claims, sources=doc.sources + code_result.sources, **common)
                else:
                    failures = [r for r in (doc, code_result) if r.status != "answered"]
                    priority = {"upstream_error": 0, "needs_clarification": 1, "insufficient_evidence": 2}
                    failure = min(failures, key=lambda r: priority[r.status])
                    result = AskResponse(status=failure.status, reason_code="combined_incomplete",
                        message="Combined retrieval could not satisfy the whole request. Check branch statuses and narrow the question before resubmitting.",
                        clarifying_questions=[q for r in failures for q in r.clarifying_questions], retryable=failure.retryable, **common)
        result.intent_generation = intent_info
        result.agent_trace = intent_trace + result.agent_trace
        retrieved_sources = list(result.sources)
        result = self.generation.apply(request, result)
        add_support_checks(request, result, retrieved_sources)
        return self.finish(request, result, retrieved_sources, started)

    def finish(self, request, result, retrieved_sources, started):
        result.agent = self.name
        result.request_id = result.request_id or str(uuid4())
        self.prepare_support_result(request, result, retrieved_sources)
        result.latency_ms = round((perf_counter() - started) * 1000, 3)
        logger.info("request_id=%s agent=support_system delegated=%s status=%s reason=%s latency_ms=%s",
                    result.request_id, bool(result.delegated_to), result.status, result.reason_code, result.latency_ms)
        return result

    @staticmethod
    def prepare_support_result(request: AskRequest, result: AskResponse, retrieved_sources):
        if result.resolution in {'checks_available', 'resolved_reported'}:
            return
        if result.reason_code == "llm_outside_scope":
            result.resolution = "unresolved"
            result.next_step = "Contact the provider responsible for the booking or service. This assistant cannot access it."
        elif result.status == "needs_clarification":
            result.resolution = "clarification_needed"
            result.next_step = "Add the requested details to your original question and submit again. Previous questions are not remembered."
        elif result.status == "answered" and (result.mode == "documentation" or (
                result.generation.status == "completed" and not support_problem(request.question)
                and not has_status_target(request.question))):
            result.resolution = "guidance_available"
            result.next_step = "Use the cited guidance after checking that it applies to your osTicket version. If the problem persists, share the evidence with an engineer."
        else:
            result.resolution = "engineering_review" if result.status == "answered" else "unresolved"
            result.next_step = result.next_step or ("Relevant code was found, but this does not confirm the cause or a fix. An engineer should review the evidence."
                                if result.status == "answered" else
                                "This question could not be resolved from the available evidence. Share the handoff details with an engineer or the system maintainer.")
            result.handoff = {
                "question": request.question, "request_id": result.request_id,
                "status": result.status, "reason_code": result.reason_code,
                "summary": result.next_step, "sources": [s.model_dump() for s in retrieved_sources],
                "evidence_note": "Retrieved references for investigation; not proof of a cause or fix. Generation may have failed or abstained.",
                "branches": [b.model_dump() for b in result.branches],
                "warnings": result.warnings, "scope": result.scope,
                "repository": result.repository.model_dump() if result.repository else None,
                "documentation": result.documentation.model_dump() if result.documentation else None,
                "agent_trace": [step.model_dump() for step in result.agent_trace],
                "details_to_add": ["Installed osTicket version", "Steps to reproduce and expected behavior",
                                   "Exact error and timestamp, with personal data and secrets removed"],
                "delivery": "Prepared locally; not sent to anyone.",
                "checks_offered": [c.model_dump() for c in result.support_checks],
                "escalation_reason": result.reason_code,
            }

    @staticmethod
    def route(request: AskRequest) -> str:
        if request.task != "auto":
            return request.task
        if needs_error_context(request.question, request.file_path):
            return "missing_error_context"
        if support_problem(request.question) and not re.search(r"\b(documentation|docs?|official)\b", request.question.lower()):
            return "code_analysis"
        doc = has_doc_intent(request.question)
        code = has_code_intent(request.question, request.file_path)
        if doc:
            return "combined" if code else "documentation"
        if code or has_status_target(request.question):
            return "code_analysis"
        return "ambiguous"

    def ask_code(self, request: AskRequest) -> AskResponse:
        task = CodeAnalysisTask(question=request.question, repository=request.repository or REPOSITORY_URL, file_path=request.file_path)
        result = self.code_analyzer.run(task)
        result.agent_trace.insert(0, AgentStep(agent=self.name, action="delegate_code_analysis", detail="Delegate the osTicket code question to the Code Analyzer"))
        result.agent_trace.append(AgentStep(agent=self.name, action="return_result", detail="Return the subagent status, evidence and execution trace"))
        return result
