import pytest
from fastapi.testclient import TestClient

from app.agents.customer_support import CustomerSupportAgent
from app.agents.code_analyzer import CodeAnalyzerAgent
from app.generation import AnswerGeneration, GeminiSettings
from app.main import create_app
from app.models import AskRequest
from test_code_agents import store


@pytest.mark.parametrize('question', [
    'it occurs a 401 error', '401', 'I get HTTP 403', 'osTicket returns 500',
    'There is an error code 401', 'I see a 401 error code', 'The response is 401',
])
def test_unscoped_error_asks_before_tools_or_model(store, monkeypatch, question):
    def forbidden(*args, **kwargs):
        pytest.fail('Clarification must not retrieve evidence or call the model')
    class Provider:
        generate = forbidden
    agent = CustomerSupportAgent(CodeAnalyzerAgent(store),
        generation=AnswerGeneration(GeminiSettings(enabled=True), Provider()))
    monkeypatch.setattr(agent.code_analyzer, 'run', forbidden)
    monkeypatch.setattr(agent.documentation, 'ask', forbidden)
    with TestClient(create_app(agent)) as client:
        response = client.post('/ask', json={'question': question})
    data = response.json()
    assert response.status_code == 200
    assert (data['status'], data['reason_code']) == ('needs_clarification', 'missing_error_context')
    assert data['resolution'] == 'clarification_needed' and data['handoff'] is None
    assert data['generation']['status'] == 'skipped'
    assert data['answer'] is None and not data['sources'] and not data['claims']
    assert data['delegated_to'] is None
    assert 'what were you trying to do' in data['clarifying_questions'][0]


@pytest.mark.parametrize('question,kwargs', [
    ('I get 401 while creating a ticket through the API', {}),
    ('I get 401 when signing in to the staff panel', {}),
    ('Find the code that returns 401', {}),
    ('Where does requireApiKey return 401?', {}),
    ('401 error', {'file_path': 'include/class.api.php'}),
    ('401 error', {'task': 'code_analysis'}),
])
def test_context_or_explicit_engineering_request_still_retrieves(store, question, kwargs):
    result = CustomerSupportAgent(CodeAnalyzerAgent(store)).ask(
        AskRequest(question=question, answer_mode='offline', **kwargs))
    assert result.mode == 'static_code_analysis' and result.delegated_to == 'Code Analyzer'
    assert result.status == 'answered'


def test_resubmit_original_error_with_context(store):
    agent = CustomerSupportAgent(CodeAnalyzerAgent(store))
    first = agent.ask(AskRequest(question='it occurs a 401 error', answer_mode='offline'))
    second = agent.ask(AskRequest(question='A 401 error occurs while creating a ticket through the API.', answer_mode='offline'))
    assert first.reason_code == 'missing_error_context'
    assert second.mode == 'static_code_analysis' and second.sources
