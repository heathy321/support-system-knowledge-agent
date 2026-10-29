import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agents.customer_support import CustomerSupportAgent
from app.agents.code_analyzer import CodeAnalyzerAgent
from app.models import AskRequest
from app.main import create_app
from test_code_agents import store


@pytest.fixture
def agent(store):
    return CustomerSupportAgent(CodeAnalyzerAgent(store))


@pytest.mark.parametrize("question,expected", [
    ("What minimum information is required by the official API to create a ticket from an external system?", "doc-fields"),
    ("Which management page lets me add an osTicket API key?", "doc-key-setup"),
    ("What information must I provide to create an API ticket?", "doc-fields"),
    ("What minimum data is needed for an API ticket?", "doc-fields"),
    ("How do I configure an API key?", "doc-key-setup"),
    ("Where do I add an API KEY?", "doc-key-setup"),
    ("Where do I configure an ＡＰＩ key in the admin panel?", "doc-key-setup"),
])
def test_natural_document_intents_do_not_call_code(agent, monkeypatch, question, expected):
    def unexpected(*args): pytest.fail("Document question must not call code tools")
    monkeypatch.setattr(agent.code_analyzer, "run", unexpected)
    r=agent.ask(AskRequest(question=question))
    assert r.status=="answered" and r.mode=="documentation"
    assert {s.chunk_id for s in r.sources}=={expected}


@pytest.mark.parametrize("question", ["API", "Help me with this API", "osTicket API key", "How should I handle this?", "Something is wrong with osTicket"])
def test_ambiguous_query_does_not_touch_either_backend(agent, monkeypatch, question):
    def unexpected(*args): pytest.fail("Ambiguous question must not read either evidence store")
    monkeypatch.setattr(agent.documentation, "ask", unexpected)
    monkeypatch.setattr(agent.code_analyzer, "run", unexpected)
    r=agent.ask(AskRequest(question=question))
    assert (r.mode,r.status,r.reason_code)==("routing","needs_clarification","ambiguous_intent")
    assert r.answer is None and not r.sources and not r.claims
    assert r.delegated_to is None and r.clarifying_questions
    assert [s.action for s in r.agent_trace]==["clarify_intent"]


@pytest.mark.parametrize("question", ["Where is the API key code?", "Where is requireApiKey defined?", "How should I investigate API 401?", "API status code 401", "The API key checking function in the source code"])
def test_explicit_code_intent_stays_code(agent, question):
    r=agent.ask(AskRequest(question=question))
    assert r.mode=="static_code_analysis" and r.delegated_to=="Code Analyzer"


def test_source_ip_is_documentation_not_source_code(agent):
    r=agent.ask(AskRequest(question="Official documentation requirements for source IP and headers"))
    assert r.mode=="documentation" and r.status=="answered"
    assert {s.chunk_id for s in r.sources}=={"doc-auth"}


@pytest.mark.parametrize("question", ["What information must I provide to the API? What is the attachment limit?", "How do I configure an API key with a reverse proxy?"])
def test_synonyms_do_not_bypass_unsupported_topic_guard(agent, question):
    r=agent.ask(AskRequest(question=question))
    assert r.status=="insufficient_evidence" and r.reason_code=="document_topic_not_covered"
    assert not r.sources and r.answer is None


def test_user_can_resolve_route_by_resubmitting_with_task(agent):
    with TestClient(create_app(agent)) as c:
        first=c.post('/ask',json={'question':'API'})
        assert first.status_code==200 and first.json()['mode']=='routing'
        r=c.post('/ask',json={'question':'API','task':'documentation'}).json()
        assert r['mode']=='documentation' and r['reason_code']=='missing_document_target'
        r=c.post('/ask',json={'question':'API key configuration in the admin panel','task':'documentation'}).json()
        assert r['status']=='answered'


def test_original_acceptance_history_remains_intact():
    import hashlib
    import zipfile
    root=Path(__file__).resolve().parents[1]
    with zipfile.ZipFile(root/'docs/archive/pre-english-v07.zip') as archive:
        raw=archive.read('evals/docs-acceptance-first.json')
        protocol=archive.read('evals/docs_acceptance_v2_protocol.md').decode('utf-8')
        manifest=json.loads(archive.read('manifest.json'))
        assert all(hashlib.sha256(archive.read(name)).hexdigest()==digest for name,digest in manifest.items())
    assert hashlib.sha256(raw).hexdigest() in protocol
    report=json.loads(raw)
    assert report['cases']==8 and report['passed']==6
