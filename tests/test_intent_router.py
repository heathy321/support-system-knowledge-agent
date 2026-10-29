import json

import httpx
import pytest

from app.agents.customer_support import CustomerSupportAgent
from app.agents.code_analyzer import CodeAnalyzerAgent
from app.generation import GeminiSettings, GeminiClient, AnswerGeneration
from app.intent_router import IntentRouter
from app.models import AskRequest
from pydantic import SecretStr
from test_code_agents import store


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    async def forbidden(*args, **kwargs):
        pytest.fail('Routing tests must not call a live model')
    monkeypatch.setattr(httpx.AsyncHTTPTransport, 'handle_async_request', forbidden)


def envelope(payload):
    return {'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': json.dumps(payload)}]}}],
            'usageMetadata': {'promptTokenCount': 120, 'candidatesTokenCount': 35, 'totalTokenCount': 155}}


def setup_agent(store, handler):
    settings = GeminiSettings(enabled=True, api_key=SecretStr('test-only-key'))
    client = GeminiClient(settings, httpx.MockTransport(handler))
    return CustomerSupportAgent(CodeAnalyzerAgent(store), generation=AnswerGeneration(settings, client))


def test_booking_ambiguity_uses_one_classification_no_retrieval(store, monkeypatch):
    calls = []
    question = 'How do I cancel a ticket booking?'
    def handle(req):
        calls.append(req)
        payload = json.loads(req.content)
        assert json.loads(payload['contents'][0]['parts'][0]['text']) == {'question': question}
        assert 'tools' not in payload and 'test-only-key' not in req.content.decode()
        assert payload['generationConfig']['maxOutputTokens'] == 512
        return httpx.Response(200, json=envelope({'decision': 'needs_clarification',
            'clarification': 'Do you mean cancelling a travel/event booking, or closing an osTicket support ticket?'}))
    agent = setup_agent(store, handle)
    def forbidden(*args): pytest.fail('A clarification must not retrieve')
    monkeypatch.setattr(agent.code_analyzer, 'run', forbidden)
    monkeypatch.setattr(agent.documentation, 'ask', forbidden)
    result = agent.ask(AskRequest(question=question))
    assert len(calls) == 1 and result.reason_code == 'llm_intent_clarification'
    assert result.status == 'needs_clarification' and 'booking' in result.clarifying_questions[0]
    assert result.intent_generation.status == 'completed' and result.intent_generation.total_tokens == 155
    assert result.generation.status == 'skipped' and result.handoff is None and not result.sources


@pytest.mark.parametrize('decision,reason', [
    ('outside_scope', 'llm_outside_scope'), ('insufficient_evidence', 'llm_topic_not_covered')])
def test_non_answer_decisions_do_not_become_generated_answers(store, decision, reason):
    calls = []
    def handle(req):
        calls.append(req)
        return httpx.Response(200, json=envelope({'decision': decision, 'clarification': None}))
    result = setup_agent(store, handle).ask(AskRequest(question='Cancel my reservation'))
    assert len(calls) == 1 and result.reason_code == reason and result.status == 'insufficient_evidence'
    assert not result.sources and not result.answer
    if decision == 'outside_scope': assert result.handoff is None


def test_classification_then_bounded_retrieval_then_synthesis(store):
    calls = []
    def handle(req):
        payload = json.loads(req.content)
        data = json.loads(payload['contents'][0]['parts'][0]['text'])
        calls.append(data)
        if len(calls) == 1:
            return httpx.Response(200, json=envelope({'decision': 'code_analysis', 'clarification': None}))
        assert data['question'] == 'Locate the login handler'  # Never rewritten by model.
        return httpx.Response(200, json=envelope({'status': 'answered', 'claims': [
            {'text': 'The cited file contains a login entry point.', 'citation_ids': [data['evidence'][0]['chunk_id']]}]}))
    result = setup_agent(store, handle).ask(AskRequest(question='Locate the login handler'))
    assert len(calls) == 2 and result.status == 'answered'
    assert result.intent_generation.status == result.generation.status == 'completed'
    assert result.delegated_to == 'Code Analyzer' and result.sources


def test_route_choice_cannot_bypass_document_topic_or_version_guards(store):
    calls = []
    def handle(req):
        calls.append(req)
        return httpx.Response(200, json=envelope({'decision': 'documentation', 'clarification': None}))
    result = setup_agent(store, handle).ask(AskRequest(question='API attachment allowance in v1.18.2'))
    assert len(calls) == 1 and result.reason_code == 'document_version_not_covered'
    assert result.generation.status == 'skipped' and not result.sources


@pytest.mark.parametrize('payload', [
    {'decision': 'execute_shell', 'clarification': None},
    {'decision': 'code_analysis', 'clarification': None, 'file_path': '../../secret'},
    {'decision': 'documentation', 'clarification': None, 'question': 'API required fields'},
    {'decision': 'needs_clarification', 'clarification': ''},
    {'decision': 'needs_clarification', 'clarification': '\u4e2d\u6587'},
    {'decision': 'outside_scope', 'clarification': 'Unexpected extra advice'},
])
def test_untrusted_classifier_outputs_fail_closed(store, payload, monkeypatch):
    calls = []
    def handle(req):
        calls.append(req)
        return httpx.Response(200, json=envelope(payload))
    agent = setup_agent(store, handle)
    def forbidden(*args): pytest.fail('Invalid output must not dispatch tools')
    monkeypatch.setattr(agent.code_analyzer, 'run', forbidden)
    monkeypatch.setattr(agent.documentation, 'ask', forbidden)
    result = agent.ask(AskRequest(question='Help me'))
    assert len(calls) == 1 and result.reason_code == 'llm_intent_invalid_output'
    assert result.status == 'upstream_error' and result.intent_generation.status == 'error'
    assert not result.sources and result.answer is None


@pytest.mark.parametrize('status,reason', [(429, 'llm_rate_limited'), (401, 'llm_auth_error'), (503, 'llm_provider_error')])
def test_intent_failure_no_retry_or_synthesis(store, status, reason):
    calls = []
    def handle(req):
        calls.append(req)
        return httpx.Response(status, text='private upstream error')
    result = setup_agent(store, handle).ask(AskRequest(question='Help me'))
    assert len(calls) == 1 and result.reason_code == reason
    assert 'private upstream error' not in result.model_dump_json()
    assert result.intent_generation.status == 'error' and result.generation.status == 'skipped'


def test_offline_never_reads_model_configuration(store, monkeypatch):
    def forbidden(*args): pytest.fail('Offline routing must not use model configuration')
    monkeypatch.setattr(GeminiSettings, 'from_env', forbidden)
    result = CustomerSupportAgent(CodeAnalyzerAgent(store)).ask(AskRequest(question='How do I cancel a ticket booking?', answer_mode='offline'))
    assert result.reason_code == 'ambiguous_intent' and result.intent_generation.backend == 'offline'


def test_error_context_rule_still_precedes_model(store):
    def forbidden(*args): pytest.fail('Bare error uses a deterministic clarification')
    result = setup_agent(store, forbidden).ask(AskRequest(question='it occurs a 401 error'))
    assert result.reason_code == 'missing_error_context' and result.intent_generation.status == 'not_requested'
