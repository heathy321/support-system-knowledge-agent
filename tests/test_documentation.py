import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agents.code_analyzer import CodeAnalyzerAgent
from app.agents.customer_support import CustomerSupportAgent
from app.agents.repository import RepositoryStore
from app.documentation import DocumentationRetriever, DocumentUnavailable, DEFAULT_CORPUS
from app.main import create_app
from app.models import AskRequest, CodeCitation, DocumentCitation
from test_code_agents import store


@pytest.fixture
def agent(store):
    return CustomerSupportAgent(CodeAnalyzerAgent(store))


@pytest.mark.parametrize("question,ids", [
    ("What authentication header does the official API documentation require?", {"doc-auth"}),
    ("How do I configure an API key in the admin panel?", {"doc-key-setup"}),
    ("What fields are required to create an API ticket?", {"doc-fields"}),
    ("What is the API ticket creation endpoint and HTTP method?", {"doc-endpoint"}),
    ("What response does successful API ticket creation return, according to the official documentation?", {"doc-response"}),
    ("Does the API documentation support updating existing tickets?", {"doc-capabilities"}),
    ("How do I create a ticket using the API?", {"doc-key-setup", "doc-auth", "doc-endpoint", "doc-fields", "doc-response"}),
    ("What API headers and required fields are needed?", {"doc-auth", "doc-fields"}),
])
def test_document_answers_are_scoped_and_cited(agent, question, ids):
    r = agent.ask(AskRequest(question=question))
    assert r.status == "answered" and r.mode == "documentation"
    assert {s.chunk_id for s in r.sources} == ids
    assert all(isinstance(s, DocumentCitation) for s in r.sources)
    assert r.documentation.code_version_relation == "unverified" and r.warnings
    assert r.retrieval_backend is None and r.delegated_to is None
    assert all(c.citation_ids and set(c.citation_ids) <= ids for c in r.claims)
    assert [c.text for c in r.claims] == [s.evidence for s in r.sources]


@pytest.mark.parametrize("question,kwargs,reason", [
    ("Official API documentation", {}, "missing_document_target"),
    ("What attachment limits and headers does the API documentation specify?", {}, "document_topic_not_covered"),
    ("What is the root cause of API 401 according to the official documentation?", {}, "document_topic_not_covered"),
    ("What is the official API rate limit configuration?", {}, "document_topic_not_covered"),
    ("Official OAuth configuration", {}, "document_topic_not_covered"),
    ("API required fields", {"product_version":"1.18.1"}, "document_version_not_covered"),
    ("v2.0 API required fields", {}, "document_version_not_covered"),
    ("v1.17.7 API required fields", {"product_version":"1.18.1"}, "document_version_not_covered"),
    ("Official API documentation", {"file_path":"scp/login.php","task":"documentation"}, "conflicting_task"),
])
def test_missing_or_uncovered_context_never_returns_related_answer(agent, question, kwargs, reason):
    r=agent.ask(AskRequest(question=question, **kwargs))
    assert r.reason_code == reason
    assert r.answer is None and not r.sources and not r.claims


def test_combined_has_independent_typed_evidence_and_version_warning(agent):
    r=agent.ask(AskRequest(question="Official API header requirements and authentication code locations"))
    assert r.status == "answered" and r.mode == "combined"
    assert {s.evidence_kind for s in r.sources} == {"code_excerpt", "curated_document_summary"}
    assert r.documentation.document_version == "v1.17.7"
    assert r.repository.commit_sha == "a" * 40
    assert r.warnings and r.documentation.code_version_relation == "unverified"
    assert {b.branch for b in r.branches} == {"documentation", "code_analysis"}
    assert all(b.status == "answered" for b in r.branches)


def test_combined_does_not_report_partial_success(agent):
    r=agent.ask(AskRequest(question="Official API documentation for 401 and related code"))
    assert r.status == "insufficient_evidence" and r.reason_code == "combined_incomplete"
    assert r.answer is None and not r.sources
    assert [b.status for b in r.branches] == ["insufficient_evidence", "answered"]


def test_explicit_task_routes_are_respected(agent):
    code=agent.ask(AskRequest(question="API configuration code", task="code_analysis"))
    assert code.mode == "static_code_analysis"
    doc=agent.ask(AskRequest(question="API authentication implementation", task="documentation"))
    assert doc.mode == "documentation"


def test_document_mode_never_calls_code_when_code_is_down(tmp_path):
    agent=CustomerSupportAgent(CodeAnalyzerAgent(RepositoryStore(tmp_path/'absent',expected_commit='a'*40)))
    with TestClient(create_app(agent)) as c:
        assert c.post('/ask',json={'question':'API required fields'}).json()['status']=='answered'
        r=c.post('/ask',json={'question':'API headers and authentication code'})
        assert r.status_code==503 and r.json()['reason_code']=='combined_incomplete'
        assert not r.json()['sources']
        h=c.get('/health')
        assert h.status_code==503
        assert h.json()['components']=={'code':'unavailable','documentation':'ready'}
        assert c.get('/documentation').status_code==200


def test_code_mode_survives_document_failure(store, tmp_path):
    agent=CustomerSupportAgent(CodeAnalyzerAgent(store), DocumentationRetriever(tmp_path/'absent'))
    with TestClient(create_app(agent)) as c:
        assert c.post('/ask',json={'question':'API 401'}).json()['status']=='answered'
        assert c.post('/ask',json={'question':'API required fields'}).status_code==503
        assert c.get('/documentation').status_code==503
        assert c.get('/health').json()['components']=={'code':'ready','documentation':'unavailable'}
        assert c.get('/repositories').status_code==200


@pytest.mark.parametrize('mutation', ['url','version','missing_chunk','duplicate','broken_ref'])
def test_corrupt_document_corpus_fails_closed(tmp_path, mutation):
    data=json.loads(DEFAULT_CORPUS.read_text(encoding='utf-8'))
    if mutation=='url': data['sources'][0]['url']='https://evil.example/docs'
    elif mutation=='version': data['sources'][0]['document_version']='v2.0'
    elif mutation=='missing_chunk': data['chunks'].pop()
    elif mutation=='duplicate': data['chunks'].append(data['chunks'][0])
    else: data['chunks'][0]['source_id']='absent'
    p=tmp_path/'corpus.json';p.write_text(json.dumps(data),encoding='utf-8')
    retriever=DocumentationRetriever(p)
    with pytest.raises(DocumentUnavailable): retriever.load()
    assert retriever.ask('API headers').status=='upstream_error'


def test_sources_have_reviewed_summary_and_source_identity():
    corpus,info=DocumentationRetriever().load()
    assert info.pages==3 and info.chunks==6 and len(info.corpus_sha256)==64
    assert all(s.document_version=='v1.17.7' and len(s.source_sha256)==64 for s in corpus.sources)
