import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.agents.customer_support import CustomerSupportAgent
from app.agents.code_analyzer import CodeAnalyzerAgent
from app.models import AskRequest
from app.main import create_app
from test_code_agents import store
from test_generation import agent_with, envelope


@pytest.mark.parametrize('question,citation', [
    ('What information do we need to collect to create a ticket through the API?', 'doc-fields'),
    ('Can we update an existing ticket through the API?', 'doc-capabilities'),
    ('How do I configure an API key in the admin panel?', 'doc-key-setup'),
])
def test_support_guidance_requires_only_question(store, question, citation):
    agent = CustomerSupportAgent(CodeAnalyzerAgent(store))
    with TestClient(create_app(agent)) as client:
        data = client.post('/ask', json={'question': question}).json()
    assert data['status'] == 'answered' and data['resolution'] == 'guidance_available'
    assert citation in {s['chunk_id'] for s in data['sources']}
    assert data['generation']['backend'] == 'offline' and data['handoff'] is None


def test_business_failure_routes_to_code_without_claiming_fix(store):
    r = CustomerSupportAgent(CodeAnalyzerAgent(store)).ask(AskRequest(question='A customer cannot log in to osTicket.'))
    assert r.delegated_to == 'Code Analyzer'
    assert any(s.file_path == 'scp/login.php' for s in r.sources)
    assert r.resolution in {'engineering_review', 'unresolved'}
    assert r.handoff['request_id'] == r.request_id and r.handoff['question'].startswith('A customer')
    assert r.handoff['delivery'] == 'Prepared locally; not sent to anyone.'


@pytest.mark.parametrize('phrase', ['log in', 'sign in', 'sign-in'])
def test_login_phrasing_does_not_retrieve_logging(store, phrase):
    r = CustomerSupportAgent(CodeAnalyzerAgent(store)).ask(AskRequest(question=f'A customer cannot {phrase} to osTicket.'))
    assert r.sources[0].file_path == 'scp/login.php'


def test_failure_is_not_answered_with_generic_setup_instructions(store):
    r = CustomerSupportAgent(CodeAnalyzerAgent(store)).ask(AskRequest(question='How do I create an API ticket? It fails with 401.'))
    assert r.mode == 'static_code_analysis' and r.resolution == 'engineering_review'
    assert all(s.evidence_kind == 'code_excerpt' for s in r.sources)


def test_ambiguous_question_asks_for_business_context(store):
    r = CustomerSupportAgent(CodeAnalyzerAgent(store)).ask(AskRequest(question='Help me with osTicket'))
    assert r.resolution == 'clarification_needed' and r.handoff is None
    assert 'what happened' in r.clarifying_questions[0]
    assert 'retrieval scope' not in r.model_dump_json()


def test_unsupported_version_prepares_handoff(store):
    r = CustomerSupportAgent(CodeAnalyzerAgent(store)).ask(AskRequest(question='API required fields in v1.18.2'))
    assert r.resolution == 'unresolved'
    assert r.handoff['reason_code'] == 'document_version_not_covered'
    assert not r.handoff['sources']


def test_auto_uses_configured_model_once_and_preserves_checked_citations(store):
    seen = []
    def handler(request):
        seen.append(request)
        prompt = json.loads(request.content)['systemInstruction']['parts'][0]['text']
        assert 'customer support staff' in prompt
        return httpx.Response(200, json=envelope())
    r = agent_with(store, handler).ask(AskRequest(question='API required fields'))
    assert len(seen) == 1 and r.generation.status == 'completed'
    assert r.resolution == 'guidance_available'


def test_auto_error_does_not_silently_fallback_or_retry(store):
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(429)
    r = agent_with(store, handler).ask(AskRequest(question='API required fields'))
    assert len(seen) == 1 and r.reason_code == 'llm_rate_limited'
    assert r.handoff and r.answer is None and r.resolution == 'unresolved'
    assert r.handoff['sources'][0]['chunk_id'] == 'doc-fields'
    assert not r.sources


def test_auto_enabled_missing_key_is_explicit_failure(store, monkeypatch):
    monkeypatch.setenv('ENABLE_GEMINI', '1')
    r = CustomerSupportAgent(CodeAnalyzerAgent(store)).ask(AskRequest(question='API required fields'))
    assert r.reason_code == 'llm_missing_key' and r.handoff
