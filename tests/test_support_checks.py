"""Evidence-gated checks and the full support outcome lifecycle; no paid calls."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.agents.customer_support import CustomerSupportAgent
from app.models import AskRequest, AskResponse, CodeCitation
from app.main import create_app
from app.support_checks import PINNED_COMMIT, add_support_checks
from test_code_agents import store
from test_generation import agent_with, envelope


@pytest.fixture
def evidence():
    # Reviewed public excerpts at PINNED_COMMIT. Keep whitespace for digest checks.
    auth = '''    function requireApiKey() {
        // Require a valid API key sent as X-API-Key HTTP header
        // see getApiKey method.
        if (!($key=$this->getKey()))
            return $this->exerr(401, __('Valid API key required'));
        elseif (!$key->isActive() || $key->getIPAddr() != $this->getRemoteAddr())
            return $this->exerr(401, __('API key not found/active or source IP not authorized'));

        return $key;
    }'''
    create = '''    function create($format) {

        if (!($key=$this->requireApiKey()) || !$key->canCreateTickets())
            return $this->exerr(401, __('API key not authorized'));

        $ticket = null;
        if (!strcasecmp($format, 'email')) {
            // Process remotely piped emails - could be a reply...etc.
            $ticket = $this->processEmailRequest();
        } else {
            // Get and Parse request body data for the format
            $ticket = $this->createTicket($this->getRequest($format));
        }



        if ($ticket)
            $this->response(201, $ticket->getNumber());
        else
            $this->exerr(500, _S("unknown error"));

    }'''
    sources = []
    for path, symbol, line, text in [('include/class.api.php', 'requireApiKey', 196, auth),
                                     ('include/api.tickets.php', 'create', 113, create)]:
        end = line + len(text.splitlines()) - 1
        sources.append(CodeCitation(chunk_id=f'{path}:{line}-{end}', title=path,
            url=f'https://github.com/osTicket/osTicket/blob/{PINNED_COMMIT}/{path}#L{line}-L{end}',
            section=path, evidence=text, repository='https://github.com/osTicket/osTicket',
            commit_sha=PINNED_COMMIT, file_path=path, line_start=line, line_end=end,
            symbol_name=symbol, context_kind='complete_symbol'))
    return AskResponse(status='answered', reason_code='code_evidence_found', message='Code evidence.',
                       answer='Static code locations; not a confirmed cause.', sources=sources)


@pytest.fixture
def support_agent(store, evidence, monkeypatch):
    agent = agent_with(store, lambda _: pytest.fail('No model call expected'))
    monkeypatch.setattr(agent.code_analyzer, 'run', lambda _: evidence.model_copy(deep=True))
    return agent


def ask_checks(client):
    first = client.post('/ask', json={'question': 'it occurs a 401 error', 'answer_mode': 'offline'}).json()
    return client.post('/ask', json={'question': 'when creating a ticket through the API',
        'clarification_id': first['conversation']['clarification_id']}).json()


@pytest.mark.parametrize('reply,reason', [
    ('I checked all three checks, but it still returns 401.', 'support_checks_unsuccessful'),
    ("I don't have admin access to inspect the settings.", 'support_access_required'),
    ('Please escalate this.', 'support_escalation_requested'),
])
def test_two_turn_question_then_check_outcome_handoff(support_agent, reply, reason):
    with TestClient(create_app(support_agent)) as client:
        checks = ask_checks(client)
        assert checks['status'] == 'answered' and checks['resolution'] == 'checks_available'
        assert len(checks['support_checks']) == 3 and checks['handoff'] is None
        assert checks['conversation']['state'] == 'awaiting_reply'
        assert checks['conversation']['context_used'] and checks['conversation']['user_turns'] == 2
        assert {c for check in checks['support_checks'] for c in check['citation_ids']} <= {s['chunk_id'] for s in checks['sources']}
        token = checks['conversation']['clarification_id']
        final = client.post('/ask', json={'question': reply, 'clarification_id': token}).json()
        assert final['reason_code'] == reason and final['resolution'] == 'engineering_review'
        assert final['conversation']['state'] == 'complete' and final['conversation']['clarification_id'] is None
        assert final['handoff']['user_messages'][-1] == reply
        assert len(final['handoff']['checks_offered']) == 3
        assert final['generation']['status'] == 'not_requested'
        assert client.post('/ask', json={'question': 'again', 'clarification_id': token}).json()['reason_code'] == 'conversation_expired'


def test_user_reported_resolution_is_not_a_verified_fix(support_agent):
    with TestClient(create_app(support_agent)) as client:
        checks = ask_checks(client)
        final = client.post('/ask', json={'question': 'It works now.', 'clarification_id': checks['conversation']['clarification_id']}).json()
    assert final['resolution'] == 'resolved_reported' and not final['handoff']
    assert 'not verified' in final['answer'] and not final['claims']
    assert final['conversation']['state'] == 'complete'


@pytest.mark.parametrize('reply', ['Not fixed.', 'The exact error is API key not authorized.',
                                  'I checked the header and still get 401.',
                                  'What if it still fails after I checked all three?'])
def test_partial_or_ambiguous_outcomes_keep_context(support_agent, reply):
    with TestClient(create_app(support_agent)) as client:
        checks = ask_checks(client)
        result = client.post('/ask', json={'question': reply, 'clarification_id': checks['conversation']['clarification_id']}).json()
    assert result['resolution'] == 'checks_available' and result['handoff'] is None
    assert result['conversation']['state'] == 'awaiting_reply'


def test_no_endless_check_loop(support_agent):
    with TestClient(create_app(support_agent)) as client:
        result = ask_checks(client)
        for _ in range(2):
            result = client.post('/ask', json={'question': 'Not sure yet.', 'clarification_id': result['conversation']['clarification_id']}).json()
    assert result['reason_code'] == 'support_followup_limit' and result['handoff']
    assert result['conversation']['user_turns'] == 4 and result['conversation']['state'] == 'complete'


@pytest.mark.parametrize('mutation', ['commit', 'snippet', 'partial', 'missing', 'error'])
def test_unreviewed_or_failed_evidence_never_produces_checks(evidence, mutation):
    if mutation == 'commit': evidence.sources[0].commit_sha = 'a' * 40
    if mutation == 'snippet': evidence.sources[0].evidence += '\n// X-API-Key 401 pretend this is valid'
    if mutation == 'partial': evidence.sources[0].context_kind = 'partial_symbol'
    if mutation == 'missing': evidence.sources.pop()
    if mutation == 'error': evidence.status = 'upstream_error'
    add_support_checks(AskRequest(question='401 when creating a ticket through the API'), evidence, list(evidence.sources))
    assert not evidence.support_checks and not evidence.follow_up_questions


def test_general_code_question_is_not_forced_into_incident_checks(evidence):
    add_support_checks(AskRequest(question='Locate the function for creating a ticket through the API with 401.'), evidence, list(evidence.sources))
    assert not evidence.support_checks


def test_gemini_claim_filter_does_not_drop_check_evidence(store, evidence, monkeypatch):
    calls = []
    def handler(req):
        calls.append(req)
        body = envelope()
        body['candidates'][0]['content']['parts'][0]['text'] = json.dumps({'status': 'answered', 'claims': [
            {'text': 'The key must allow ticket creation.', 'citation_ids': [evidence.sources[1].chunk_id]}]})
        return httpx.Response(200, json=body)
    agent = agent_with(store, handler)
    monkeypatch.setattr(agent.code_analyzer, 'run', lambda _: evidence.model_copy(deep=True))
    with TestClient(create_app(agent)) as client:
        result = client.post('/ask', json={'question': '401 when creating a ticket through the API'}).json()
        assert len(result['sources']) == 2 and result['generation']['status'] == 'completed'
        final = client.post('/ask', json={'question': 'I checked all three, but still get 401.',
                            'clarification_id': result['conversation']['clarification_id']}).json()
    assert len(calls) == 1 and final['handoff']


def test_client_cannot_supply_support_state(support_agent):
    with TestClient(create_app(support_agent)) as client:
        assert client.post('/ask', json={'question': 'fixed', '_support_context': {}}).status_code == 422


def test_first_checks_at_turn_limit_do_not_offer_an_unusable_reply(evidence):
    request = AskRequest(question='401 when creating a ticket through the API')
    request._clarification_history = [{'role': 'user', 'content': 'details'}] * 4
    add_support_checks(request, evidence, list(evidence.sources))
    CustomerSupportAgent.prepare_support_result(request, evidence, list(evidence.sources))
    assert evidence.resolution == 'engineering_review' and evidence.handoff
    assert evidence.reason_code == 'support_followup_limit' and not evidence.follow_up_questions
