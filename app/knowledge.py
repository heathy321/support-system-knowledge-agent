"""Versioned, curated evidence and a small bilingual lexical retriever."""
import hashlib
import json
import math
import re
from collections import Counter
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel, Field, ValidationError, model_validator

from app.models import Fare, Topic

DEFAULT_CORPUS = Path(__file__).resolve().parents[1] / "knowledge" / "peach.json"


class KnowledgeUnavailable(Exception):
    """Expected storage or document-validation failure."""


class Document(BaseModel):
    id: str
    title: str
    url: str
    reviewed_at: date

    @model_validator(mode="after")
    def official_url(self):
        parsed = urlparse(self.url)
        if parsed.scheme != "https" or parsed.hostname not in {"www.flypeach.com", "cs.flypeach.com"} or parsed.username:
            raise ValueError("Only official Peach HTTPS sources are accepted")
        return self


class Chunk(BaseModel):
    id: str
    document_id: str
    topic: Topic
    fare_type: Fare | None
    section: str
    text: str = Field(min_length=1)
    keywords: list[str]


class Corpus(BaseModel):
    version: str
    review_window_days: int = Field(ge=1, le=90)
    documents: list[Document]
    chunks: list[Chunk]

    @model_validator(mode="after")
    def references(self):
        docs = {d.id for d in self.documents}
        if len(docs) != len(self.documents) or len({c.id for c in self.chunks}) != len(self.chunks):
            raise ValueError("Duplicate evidence identifiers")
        if any(c.document_id not in docs for c in self.chunks):
            raise ValueError("Unknown evidence document")
        return self


class KnowledgeStore:
    def __init__(self, path: Path = DEFAULT_CORPUS):
        self.path = path

    def load(self) -> tuple[Corpus, str]:
        try:
            raw = self.path.read_bytes()
            corpus = Corpus.model_validate(json.loads(raw))
        except (OSError, ValueError, ValidationError) as exc:
            raise KnowledgeUnavailable("Knowledge storage unavailable") from exc
        return corpus, hashlib.sha256(raw).hexdigest()


def tokens(text: str) -> list[str]:
    result = re.findall(r"[a-z0-9]+", text.lower())
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        result.extend(run[i:i + 2] for i in range(max(1, len(run) - 1)))
    return result


def retrieve(corpus: Corpus, question: str, topic: Topic, fare: Fare | None) -> list[Chunk]:
    """Filter applicability first, then rank evidence using BM25 over bilingual tokens.

    The router supplies a topic alias so paraphrases classified by its controlled
    vocabulary can still retrieve a relevant paragraph. BM25 is not confidence.
    All matching paragraphs are retained for conflict checks (no hidden top-k).
    """
    candidates = [c for c in corpus.chunks if c.topic == topic and c.fare_type == fare]
    if not candidates:
        return []
    aliases = {"carry_on": "随身", "checked_limits": "限制", "checked_allowance": "免费", "change": "改签", "cancel": "退款"}
    query = set(tokens(question + " " + aliases[topic]))
    docs = [tokens(c.text + " " + " ".join(c.keywords)) for c in corpus.chunks]
    frequencies = Counter(t for doc in docs for t in set(doc))
    avg_len = sum(map(len, docs)) / max(1, len(docs))
    index = {c.id: doc for c, doc in zip(corpus.chunks, docs)}

    def score(chunk: Chunk) -> float:
        doc = index[chunk.id]
        counts = Counter(doc)
        total = 0.0
        for term in query:
            tf = counts[term]
            idf = math.log(1 + (len(docs) - frequencies[term] + .5) / (frequencies[term] + .5))
            total += idf * (tf * 2.2) / (tf + 1.2 * (.25 + .75 * len(doc) / avg_len))
        return total

    return sorted((c for c in candidates if score(c) > 0), key=score, reverse=True)
