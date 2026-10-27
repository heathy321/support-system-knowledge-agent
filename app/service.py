import logging
from datetime import datetime, timedelta, timezone
from time import perf_counter
from uuid import uuid4

from app.knowledge import KnowledgeStore, KnowledgeUnavailable, retrieve
from app.models import AskRequest, AskResponse, Citation, Claim
from app.router import route

logger = logging.getLogger("travel_ops")


def today_jst():
    return datetime.now(timezone(timedelta(hours=9))).date()


class KnowledgeAssistant:
    def __init__(self, store: KnowledgeStore | None = None, today=today_jst):
        self.store = store if store is not None else KnowledgeStore()
        self.today = today

    def ask(self, request: AskRequest) -> AskResponse:
        start = perf_counter()
        result = self._answer(request)
        result.latency_ms = round((perf_counter() - start) * 1000, 3)
        result.request_id = str(uuid4())
        # No question text, passenger details or exception strings in logs.
        logger.info("request_id=%s status=%s reason=%s latency_ms=%s corpus=%s", result.request_id,
                    result.status, result.reason_code, result.latency_ms, result.corpus_version)
        return result

    def _answer(self, request: AskRequest) -> AskResponse:
        decision = route(request)
        if decision.status:
            return AskResponse(status=decision.status, reason_code=decision.reason_code,
                               message=decision.message, clarifying_questions=list(decision.questions), context=decision.context)
        try:
            corpus, digest = self.store.load()
        except KnowledgeUnavailable:
            return AskResponse(status="upstream_error", reason_code="knowledge_unavailable",
                               message="知识库暂时不可用，请稍后重试。", context=decision.context)
        metadata = {"context": decision.context, "corpus_version": corpus.version, "corpus_sha256": digest}

        def insufficient(code, message):
            return AskResponse(status="insufficient_evidence", reason_code=code, message=message, **metadata)

        fare = decision.context.fare_type if decision.topic in {"checked_allowance", "change", "cancel"} else None
        evidence = retrieve(corpus, request.question, decision.topic, fare)
        if not evidence:
            return insufficient("no_matching_evidence", "当前知识库没有满足主题及适用条件的证据。")
        docs = {d.id: d for d in corpus.documents}
        ages = [(self.today() - docs[c.document_id].reviewed_at).days for c in evidence]
        if any(age < 0 or age > corpus.review_window_days for age in ages):
            return insufficient("evidence_needs_review", "相关资料尚未核对或已超过复核期限，需重新核对官方来源。")
        # Each (topic, fare) is one curated fact group. Divergent alternatives
        # require human review, even when the ranker strongly prefers one.
        if len({c.text for c in evidence}) > 1:
            return insufficient("conflicting_evidence", "相同适用条件下存在不同的证据摘要，需人工复核后才能回答。")
        chunk = evidence[0]
        document = docs[chunk.document_id]
        citation = Citation(chunk_id=chunk.id, title=document.title, url=document.url,
                            section=chunk.section, evidence=chunk.text, reviewed_at=document.reviewed_at)
        claim = Claim(text=chunk.text, citation_ids=[chunk.id])
        # Extractive mode uses precisely the reviewed paragraph: no invented
        # eligibility conclusion, generated number, or unlinked claim.
        return AskResponse(status="answered", answer=chunk.text, claims=[claim], sources=[citation],
                           reason_code="supported_by_evidence", message="已找到适用的一般政策摘要；请核对下方来源与适用边界。", **metadata)
