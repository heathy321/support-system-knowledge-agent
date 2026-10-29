from concurrent.futures import ThreadPoolExecutor
from threading import Event
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.agents.customer_support import CustomerSupportAgent
from app.agents.code_analyzer import CodeAnalyzerAgent
from app.conversation import ClarificationMemory
from app.main import create_app
from app.models import AskRequest, AskResponse
from test_code_agents import store
from test_intent_router import setup_agent, envelope


def clarify():
    return AskResponse(status='needs_clarification', reason_code='test_clarify', message='More detail needed.',
                       clarifying_questions=['Where did it happen?'])


class RecordingAgent:
    def __init__(self, response=None):
        self.requests = []
        self.response = response or clarify

    def ask(self, request):
        self.requests.append(request)
        return self.response()


def test_http_error_followup_remembers_original_and_clears_after_completion(store):
    agent = CustomerSupportAgent(CodeAnalyzerAgent(store))
    app = create_app(agent)
    with TestClient(app) as client:
        first = client.post('/ask', json={'question': 'it occurs a 401 error', 'answer_mode': 'offline'}).json()
        token = first['conversation']['clarification_id']
        assert first['conversation']['state'] == 'awaiting_reply' and token
        assert first['conversation']['expires_in_seconds'] == 900
        second = client.post('/ask', json={'question': 'when creating a ticket through the API', 'clarification_id': token}).json()
        assert second['status'] == 'answered' and second['mode'] == 'static_code_analysis'
        assert second['conversation']['context_used'] and second['conversation']['user_turns'] == 2
        assert second['conversation']['clarification_id'] is None
        assert second['handoff']['user_messages'] == ['it occurs a 401 error', 'when creating a ticket through the API']
        assert '401' in second['handoff']['question'] and 'creating a ticket' in second['handoff']['question']
        assert second['generation']['backend'] == 'offline'  # Original explicit no-cost mode retained.
        stale = client.post('/ask', json={'question': 'try again', 'clarification_id': token}).json()
        assert stale['reason_code'] == 'conversation_expired'


def test_original_version_boundary_is_not_lost(store):
    with TestClient(create_app(CustomerSupportAgent(CodeAnalyzerAgent(store)))) as client:
        first = client.post('/ask', json={'question': 'Help me with the API in v1.18.2', 'answer_mode': 'offline'}).json()
        second = client.post('/ask', json={'question': 'Which fields are required?', 'clarification_id': first['conversation']['clarification_id']}).json()
    assert second['reason_code'] == 'document_version_not_covered' and not second['sources']


def test_independent_sessions_and_rotation_do_not_leak_context():
    memory = ClarificationMemory()
    agent = RecordingAgent()
    a = memory.ask(AskRequest(question='First issue 401'), agent)
    b = memory.ask(AskRequest(question='Different issue 403'), agent)
    next_a = memory.ask(AskRequest(question='in the API', clarification_id=a.conversation.clarification_id), agent)
    assert '401' in agent.requests[-1].question and '403' not in agent.requests[-1].question
    assert next_a.conversation.clarification_id != a.conversation.clarification_id
    stale = memory.ask(AskRequest(question='again', clarification_id=a.conversation.clarification_id), agent)
    assert stale.reason_code == 'conversation_expired' and len(agent.requests) == 3
    memory.ask(AskRequest(question='in staff login', clarification_id=b.conversation.clarification_id), agent)
    assert '403' in agent.requests[-1].question and '401' not in agent.requests[-1].question


def test_assistant_options_are_history_not_retrieval_terms():
    memory = ClarificationMemory()
    agent = RecordingAgent(lambda: AskResponse(status='needs_clarification', reason_code='clarify', message='Clarify',
        clarifying_questions=['API, login, or another action?']))
    first = memory.ask(AskRequest(question='I see 401'), agent)
    memory.ask(AskRequest(question='Opening a ticket', clarification_id=first.conversation.clarification_id), agent)
    request = agent.requests[-1]
    assert request.question == 'I see 401\nOpening a ticket'
    assert 'login' not in request.question and 'API' not in request.question
    assert request._clarification_history[1]['content'] == 'API, login, or another action?'


def test_expired_context_never_treats_reply_as_a_new_question():
    now = [0]
    memory = ClarificationMemory(ttl=10, clock=lambda: now[0])
    agent = RecordingAgent()
    first = memory.ask(AskRequest(question='first issue'), agent)
    now[0] = 11
    result = memory.ask(AskRequest(question='just API', clarification_id=first.conversation.clarification_id), agent)
    assert result.reason_code == 'conversation_expired' and len(agent.requests) == 1


def test_reset_and_unknown_ids_do_not_dispatch(store):
    with TestClient(create_app(CustomerSupportAgent(CodeAnalyzerAgent(store)))) as client:
        first = client.post('/ask', json={'question': '401', 'answer_mode': 'offline'}).json()
        token = first['conversation']['clarification_id']
        assert client.post('/conversation/reset', json={'clarification_id': token}).json() == {'status': 'cleared'}
        response = client.post('/ask', json={'question': 'API', 'clarification_id': token})
        assert response.json()['reason_code'] == 'conversation_expired'
        assert response.json()['intent_generation']['status'] == 'not_requested'
        assert client.post('/ask', json={'question': 'API', 'clarification_id': '../bad'}).status_code == 422
        assert client.post('/ask', json={'question': 'API', 'history': []}).status_code == 422
        assert client.post('/ask', json={'question': 'API', '_clarification_history': []}).status_code == 422


def test_model_receives_latest_reply_and_prior_clarification(store, monkeypatch):
    async def forbidden(*args, **kwargs): pytest.fail('No real model requests')
    monkeypatch.setattr(httpx.AsyncHTTPTransport, 'handle_async_request', forbidden)
    calls = []
    def handle(req):
        data = json.loads(json.loads(req.content)['contents'][0]['parts'][0]['text'])
        calls.append(data)
        if len(calls) == 1:
            return httpx.Response(200, json=envelope({'decision': 'needs_clarification',
                'clarification': 'Do you mean a booking or an osTicket support case?'}))
        assert data['clarification_history'][-1] == {'role': 'user', 'content': 'I mean closing an osTicket support case'}
        assert data['clarification_history'][1]['role'] == 'assistant'
        assert 'cancel a ticket booking' in data['question']
        return httpx.Response(200, json=envelope({'decision': 'insufficient_evidence', 'clarification': None}))
    with TestClient(create_app(setup_agent(store, handle))) as client:
        first = client.post('/ask', json={'question': 'How do I cancel a ticket booking?'}).json()
        second = client.post('/ask', json={'question': 'I mean closing an osTicket support case', 'clarification_id': first['conversation']['clarification_id']}).json()
    assert len(calls) == 2 and second['reason_code'] == 'llm_topic_not_covered'
    assert second['conversation']['state'] == 'complete' and not second['sources']


def test_failed_reply_retains_context_without_duplicating_on_manual_retry():
    memory = ClarificationMemory()
    agent = RecordingAgent()
    first = memory.ask(AskRequest(question='Initial issue'), agent)
    token = first.conversation.clarification_id
    agent.response = lambda: AskResponse(status='upstream_error', reason_code='llm_timeout', message='Timeout')
    failed = memory.ask(AskRequest(question='extra details', clarification_id=token), agent)
    assert failed.conversation.state == 'retry' and failed.conversation.clarification_id == token
    agent.response = clarify
    memory.ask(AskRequest(question='revised details', clarification_id=token), agent)
    assert 'extra details' not in agent.requests[-1].question
    assert agent.requests[-1].question.count('Initial issue') == 1


def test_followup_generation_uses_history_as_context_and_sources_as_evidence(store, monkeypatch):
    async def forbidden(*args, **kwargs): pytest.fail('No real model requests')
    monkeypatch.setattr(httpx.AsyncHTTPTransport, 'handle_async_request', forbidden)
    calls = []
    def handle(req):
        payload = json.loads(req.content)
        data = json.loads(payload['contents'][0]['parts'][0]['text'])
        calls.append(data)
        if len(calls) == 1:
            return httpx.Response(200, json=envelope({'decision': 'needs_clarification',
                'clarification': 'Which API task do you need help with?'}))
        assert data['clarification_history'][0]['content'] == 'Help me with the API'
        assert data['clarification_history'][-1]['content'] == 'Which fields are required to create a ticket?'
        assert {s['chunk_id'] for s in data['evidence']} == {'doc-fields'}
        assert 'not evidence' in payload['systemInstruction']['parts'][0]['text']
        return httpx.Response(200, json=envelope({'status': 'answered', 'claims': [
            {'text': 'The documented base fields are email, name, subject and message.', 'citation_ids': ['doc-fields']}]}))
    with TestClient(create_app(setup_agent(store, handle))) as client:
        first = client.post('/ask', json={'question': 'Help me with the API'}).json()
        second = client.post('/ask', json={'question': 'Which fields are required to create a ticket?',
            'clarification_id': first['conversation']['clarification_id']}).json()
    assert len(calls) == 2 and second['status'] == 'answered'
    assert second['generation']['status'] == 'completed' and second['conversation']['context_used']


def test_changing_explicit_options_requires_new_question():
    memory = ClarificationMemory()
    agent = RecordingAgent()
    first = memory.ask(AskRequest(question='Initial issue', answer_mode='offline'), agent)
    result = memory.ask(AskRequest(question='details', answer_mode='gemini', clarification_id=first.conversation.clarification_id), agent)
    assert result.reason_code == 'conversation_options_changed' and len(agent.requests) == 1


def test_turn_and_character_budgets_do_not_silently_truncate():
    memory = ClarificationMemory()
    agent = RecordingAgent()
    result = memory.ask(AskRequest(question='Initial issue'), agent)
    for n in range(3):
        result = memory.ask(AskRequest(question=f'detail {n}', clarification_id=result.conversation.clarification_id), agent)
    assert result.conversation.state == 'limit_reached' and result.conversation.clarification_id is None
    result = memory.ask(AskRequest(question='x'*1500), agent)
    for _ in range(2):
        result = memory.ask(AskRequest(question='y'*1500, clarification_id=result.conversation.clarification_id), agent)
    before = len(agent.requests)
    result = memory.ask(AskRequest(question='z'*1500, clarification_id=result.conversation.clarification_id), agent)
    assert result.reason_code == 'conversation_limit_reached' and len(agent.requests) == before


def test_capacity_does_not_evict_other_pending_context():
    memory = ClarificationMemory(capacity=1)
    agent = RecordingAgent()
    first = memory.ask(AskRequest(question='Initial issue'), agent)
    second = memory.ask(AskRequest(question='Different issue'), agent)
    assert second.conversation.state == 'unavailable'
    continued = memory.ask(AskRequest(question='my details', clarification_id=first.conversation.clarification_id), agent)
    assert continued.conversation.context_used


def test_concurrent_reply_rejected_and_reset_during_request_does_not_resurrect():
    memory = ClarificationMemory()
    agent = RecordingAgent()
    first = memory.ask(AskRequest(question='Initial issue'), agent)
    token = first.conversation.clarification_id
    entered, release = Event(), Event()
    def blocked():
        entered.set()
        assert release.wait(5)
        return clarify()
    agent.response = blocked
    request = AskRequest(question='details', clarification_id=token)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(memory.ask, request, agent)
        assert entered.wait(5)
        try:
            rejected = memory.ask(request, agent)
            assert rejected.reason_code == 'conversation_busy' and len(agent.requests) == 2
            memory.reset(token)
        finally:
            release.set()
        completed = future.result()
    assert completed.conversation.state == 'expired' and completed.conversation.clarification_id is None
