"""Small reviewed document corpus. No network, model, or code execution at query time."""
import hashlib
import re
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.intent import normalize, has_doc_intent, required_fields_intent, key_setup_intent
from app.models import AgentStep, AskResponse, Claim, DocumentCitation, DocumentInfo

DEFAULT_CORPUS = Path(__file__).resolve().parents[1] / "knowledge" / "osticket-docs.json"
VERSION_WARNING = "Documentation targets v1.17.7. Its relationship to the indexed code commit is unverified; deployed behavior may differ."
DOC_SCOPE = "Reviewed English summaries of official osTicket v1.17.7 API documentation. Limited to included topics; no ticket operations or live behavior verification."
PAGE_PATHS = {
    "/en/v1.17.7/Developer%20Documentation/API%20Docs.html",
    "/en/v1.17.7/Developer%20Documentation/API/Tickets.html",
    "/en/v1.17.7/Admin/Manage/API%20Keys.html",
}
TOPICS = {"doc-auth", "doc-key-setup", "doc-endpoint", "doc-fields", "doc-response", "doc-capabilities"}
class DocumentUnavailable(Exception):
    pass


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str
    url: str
    document_version: str
    fetched_at: str
    reviewed_at: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_url(self):
        u = urlsplit(self.url)
        if (u.scheme != "https" or u.netloc != "docs.osticket.com" or u.path not in PAGE_PATHS
                or u.query or u.fragment or self.document_version != "v1.17.7"):
            raise ValueError("Unapproved document source")
        return self


class Chunk(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    source_id: str
    section: str
    summary: str = Field(min_length=10, max_length=1500)


class Corpus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int
    corpus_version: str
    document_version: str
    reviewed_at: str
    sources: list[Source]
    chunks: list[Chunk]

    @model_validator(mode="after")
    def validate_corpus(self):
        ids = {s.id for s in self.sources}
        if (self.schema_version != 1 or self.document_version != "v1.17.7"
                or len(ids) != len(self.sources) or len(self.sources) != 3
                or {c.id for c in self.chunks} != TOPICS or len(self.chunks) != len(TOPICS)
                or any(c.source_id not in ids for c in self.chunks)
                or any(s.reviewed_at != self.reviewed_at for s in self.sources)):
            raise ValueError("Invalid corpus or incomplete topic set")
        return self


class DocumentationRetriever:
    def __init__(self, path: Path = DEFAULT_CORPUS):
        self.path = path

    def load(self):
        try:
            if self.path.stat().st_size > 100_000:
                raise ValueError("Corpus too large")
            raw = self.path.read_bytes()
            corpus = Corpus.model_validate_json(raw)
            info = DocumentInfo(corpus_version=corpus.corpus_version, corpus_sha256=hashlib.sha256(raw).hexdigest(),
                                document_version=corpus.document_version, reviewed_at=corpus.reviewed_at,
                                pages=len(corpus.sources), chunks=len(corpus.chunks))
            return corpus, info
        except (OSError, ValueError) as exc:
            raise DocumentUnavailable("Document corpus unavailable") from exc

    def ask(self, question: str, product_version: str | None = None) -> AskResponse:
        trace = [AgentStep(agent="Documentation Retriever", action="retrieve_documentation", detail="Retrieve reviewed English summaries of official API documentation")]
        def result(status, reason, message, **kwargs):
            return AskResponse(status=status, reason_code=reason, message=message, mode="documentation",
                               scope=DOC_SCOPE, warnings=[VERSION_WARNING], agent_trace=trace.copy(), **kwargs)
        try:
            corpus, info = self.load()
        except DocumentUnavailable:
            return result("upstream_error", "document_corpus_unavailable", "The local document corpus is missing or failed validation.", retryable=False)
        q = normalize(question)
        versions = set(re.findall(r"(?<![\d.])v?(\d+\.\d+(?:\.\d+)?)(?![\d.])", q))
        if product_version:
            versions.add(product_version.lower().removeprefix("v"))
        if versions and versions != {"1.17.7"}:
            return result("insufficient_evidence", "document_version_not_covered", "Only v1.17.7 documentation is included. The requested version or cross-version comparison is not covered.", documentation=info)
        # Reject uncovered dimensions rather than attach a loosely related paragraph.
        unsupported = ("attachment", "upload", "rate limit", "pagination", "oauth", "proxy", "nginx", "forwarding", "concurrency", "retry", "retries", "idempotency", "batch", "pricing", "cost", "timeout", "webhook", "custom field", "size limit")
        if any(word in q for word in unsupported) or re.search(r"\b(?:[45]\d{2})\b", q):
            return result("insufficient_evidence", "document_topic_not_covered", "The summaries do not cover this detail or error-code diagnosis. Related topics cannot substitute for missing evidence.", documentation=info)
        if not re.search(r"\b(api|tickets?|keys?|headers?)\b", q):
            return result("insufficient_evidence", "document_topic_not_covered", "The corpus covers only API ticket creation and API key configuration.", documentation=info)
        topics = []
        def add(topic):
            if topic not in topics:
                topics.append(topic)
        if re.search(r"\b(updat\w*|delet\w*|modify|modifying|edit|change)\b", q) and "ticket" in q:
            add("doc-capabilities")
        if re.search(r"\b(headers?|authentication|authorization|ip|x-api-key)\b", q):
            add("doc-auth")
        if key_setup_intent(q):
            add("doc-key-setup")
        if required_fields_intent(q):
            add("doc-fields")
        if re.search(r"\b(responses?|success\w*|returns?)\b", q):
            add("doc-response")
        if re.search(r"\b(url|paths?|methods?|formats?|post|endpoints?|json|xml)\b", q):
            add("doc-endpoint")
        if not topics and re.search(r"\b(create|creating)\s+(?:a |an |new )?tickets?\b", q):
            topics = ["doc-key-setup", "doc-auth", "doc-endpoint", "doc-fields", "doc-response"]
        if not topics:
            return result("needs_clarification", "missing_document_target", "Please specify an API documentation topic.", documentation=info,
                          clarifying_questions=["Do you need key configuration, authentication headers, creation endpoints, required fields, success responses or supported ticket operations?"])
        chunks = {c.id: c for c in corpus.chunks}
        pages = {s.id: s for s in corpus.sources}
        citations = []
        for topic in topics:
            chunk = chunks[topic]
            page = pages[chunk.source_id]
            citations.append(DocumentCitation(chunk_id=topic, title=page.title, url=page.url, section=chunk.section,
                evidence=chunk.summary, document_version=page.document_version, reviewed_at=page.reviewed_at,
                fetched_at=page.fetched_at, source_sha256=page.source_sha256))
        claims = [Claim(text=s.evidence, citation_ids=[s.chunk_id]) for s in citations]
        trace.append(AgentStep(agent="Documentation Retriever", action="validate_document_evidence", detail=f"Checked source, version and corpus identity for {len(citations)} summaries; this does not verify a live deployment"))
        return result("answered", "document_evidence_found", "Found reviewed summaries of official documentation. Check the applicable version.", documentation=info,
                      answer="Documentation evidence (reviewed English summaries):\n" + "\n".join(c.text for c in claims), claims=claims, sources=citations)
