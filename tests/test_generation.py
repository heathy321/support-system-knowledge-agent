import json
import asyncio
import httpx
import pytest
from pydantic import SecretStr
from fastapi.testclient import TestClient

from app.agents.customer_support import CustomerSupportAgent
from app.agents.code_analyzer import CodeAnalyzerAgent
from app.generation import AnswerGeneration, GeminiClient, GeminiSettings, GenerationError, DEFAULT_MODEL
from app.models import AskRequest
from app.main import create_app
from test_code_agents import store

KEY = "test-secret-never-real"


@pytest.fixture(autouse=True)
def never_use_real_network(monkeypatch):
    async def forbidden(*args, **kwargs):
        pytest.fail("LLM tests must use MockTransport; real network is forbidden")
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden)
    monkeypatch.delenv("ENABLE_GEMINI", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


def envelope(payload=None, finish="STOP", usage=None):
    payload = payload or {"status":"answered","claims":[{"text":"Ticket creation requires the base fields.","citation_ids":["doc-fields"]}]}
    return {"candidates":[{"finishReason":finish,"content":{"role":"model","parts":[{"text":json.dumps(payload)}]}}],
            "usageMetadata":usage or {"promptTokenCount":90,"candidatesTokenCount":32,"thoughtsTokenCount":5,"totalTokenCount":127}}


def agent_with(store, handler, **settings):
    cfg=GeminiSettings(enabled=True, api_key=SecretStr(KEY), **settings)
    client=GeminiClient(cfg,httpx.MockTransport(handler))
    return CustomerSupportAgent(CodeAnalyzerAgent(store),generation=AnswerGeneration(cfg,client))


def ask(agent, **kwargs):
    return agent.ask(AskRequest(question="Official API required fields",answer_mode="gemini",**kwargs))


def test_real_request_contract_and_checked_claims(store):
    requests=[]
    def handle(request):
        requests.append(request)
        assert request.url==f"https://generativelanguage.googleapis.com/v1beta/models/{DEFAULT_MODEL}:generateContent"
        assert request.headers['x-goog-api-key']==KEY and not request.url.query
        body=json.loads(request.content)
        assert 'tools' not in body
        assert body['generationConfig']['maxOutputTokens']==1024
        assert body['generationConfig']['candidateCount']==1
        assert body['generationConfig']['responseJsonSchema']['required']==['status','claims']
        assert body['systemInstruction']['parts'][0]['text']
        evidence=json.loads(body['contents'][0]['parts'][0]['text'])
        assert len(evidence['evidence'])==1 and evidence['evidence'][0]['chunk_id']=='doc-fields'
        assert KEY not in request.content.decode()
        return httpx.Response(200,json=envelope())
    r=ask(agent_with(store,handle))
    assert len(requests)==1 and r.status=='answered'
    assert r.reason_code=='llm_generated_from_evidence'
    assert r.answer=='1. Ticket creation requires the base fields.'
    assert r.generation.backend=='gemini' and r.generation.status=='completed'
    assert r.generation.total_tokens==127 and r.generation.thought_tokens==5
    assert r.warnings and r.documentation.code_version_relation=='unverified'
    assert len(r.sources)==1 and r.sources[0].evidence_kind=='curated_document_summary'


def test_explicit_offline_ignores_keys_and_never_calls_model(store,monkeypatch):
    monkeypatch.setenv('ENABLE_GEMINI','1');monkeypatch.setenv('GEMINI_API_KEY',KEY)
    def forbidden(request):pytest.fail("Offline must not call model")
    agent=agent_with(store,forbidden)
    r=agent.ask(AskRequest(question='API required fields',answer_mode='offline'))
    assert r.status=='answered' and r.generation.backend=='offline'
    assert not any(s.action=='gemini_generate' for s in r.agent_trace)


@pytest.mark.parametrize('question',['Official v2.0 API required fields','Official API attachment size limits','Peach baggage'])
def test_evidence_gate_skips_model(store,question):
    def forbidden(request):pytest.fail('No generation without answerable retrieval')
    r=agent_with(store,forbidden).ask(AskRequest(question=question,answer_mode='gemini'))
    assert r.status!='answered' and r.generation.status=='skipped'
    assert not r.sources and r.answer is None


@pytest.mark.parametrize('env,reason',[
    ({},'llm_not_enabled'),
    ({'ENABLE_GEMINI':'1'},'llm_missing_key'),
    ({'ENABLE_GEMINI':'1','GEMINI_API_KEY':KEY,'GEMINI_MODEL':'../bad'},'llm_invalid_config'),
    ({'ENABLE_GEMINI':'1','GEMINI_API_KEY':KEY,'GEMINI_TIMEOUT_SECONDS':'NaN'},'llm_invalid_config'),
    ({'ENABLE_GEMINI':'1','GEMINI_API_KEY':KEY,'GEMINI_MAX_OUTPUT_TOKENS':'bad'},'llm_invalid_config'),
])
def test_config_failure_is_not_offline_success(store,monkeypatch,env,reason):
    for k,v in env.items():monkeypatch.setenv(k,v)
    r=ask(CustomerSupportAgent(CodeAnalyzerAgent(store)))
    assert r.status=='upstream_error' and r.reason_code==reason
    assert r.generation.status=='error' and r.answer is None and not r.sources
    assert KEY not in r.model_dump_json()


@pytest.mark.parametrize('status,reason,retryable',[
    (429,'llm_rate_limited',True),(401,'llm_auth_error',False),(403,'llm_auth_error',False),
    (404,'llm_model_unavailable',False),(400,'llm_request_rejected',False),
    (500,'llm_provider_error',True),(302,'llm_request_rejected',False)])
def test_http_failures_are_sanitized_and_never_retried(store,status,reason,retryable,caplog):
    seen=[]
    def handle(request):
        seen.append(request)
        return httpx.Response(status,text=KEY+' secret error body',headers={'Location':'https://evil.example/'})
    r=ask(agent_with(store,handle))
    assert len(seen)==1 and r.reason_code==reason and r.retryable==retryable
    assert r.status=='upstream_error' and not r.sources and r.answer is None
    assert KEY not in r.model_dump_json()+caplog.text


@pytest.mark.parametrize('exc,reason',[(httpx.ReadTimeout,'llm_timeout'),(httpx.ConnectError,'llm_connection_error')])
def test_transport_failures(store,exc,reason):
    calls=[]
    def handle(request):
        calls.append(1);raise exc(KEY)
    r=ask(agent_with(store,handle))
    assert len(calls)==1 and r.reason_code==reason
    assert KEY not in r.model_dump_json()


def test_whole_call_deadline(store):
    async def slow(request):
        await asyncio.sleep(10)
        return httpx.Response(200,json=envelope())
    r=ask(agent_with(store,slow,timeout_seconds=1))
    assert r.reason_code=='llm_timeout' and r.generation.latency_ms<3000


@pytest.mark.parametrize('body,reason',[
    ({'promptFeedback':{'blockReason':'SAFETY'}},'llm_blocked'),
    (envelope(finish='MAX_TOKENS'),'llm_output_truncated'),
    (envelope(finish='SAFETY'),'llm_blocked'),
    ({'candidates':[]},'llm_invalid_response'),
    ({'candidates':[{'finishReason':'STOP','content':{'parts':[{'functionCall':{'name':'execute'}}]}}]},'llm_invalid_response'),
])
def test_provider_response_boundaries(store,body,reason):
    r=ask(agent_with(store,lambda req:httpx.Response(200,json=body)))
    assert r.reason_code==reason and r.answer is None


@pytest.mark.parametrize('payload,reason',[
    ({'status':'answered','claims':[]},'llm_invalid_citations'),
    ({'status':'answered','claims':[{'text':'claim','citation_ids':['invented']}]},'llm_invalid_citations'),
    ({'status':'answered','claims':[{'text':'claim','citation_ids':[]}]},'llm_invalid_output'),
    ({'status':'answered','claims':[{'text':'claim','citation_ids':['doc-fields']}],'answer':'uncited'},'llm_invalid_output'),
    ({'status':'insufficient_evidence','claims':[{'text':'claim','citation_ids':['doc-fields']}]},'llm_invalid_output'),
])
def test_schema_and_citations_fail_closed(store,payload,reason):
    r=ask(agent_with(store,lambda req:httpx.Response(200,json=envelope(payload))))
    assert r.reason_code==reason and r.status=='upstream_error' and not r.claims and not r.sources


def test_model_may_abstain(store):
    r=ask(agent_with(store,lambda req:httpx.Response(200,json=envelope({'status':'insufficient_evidence','claims':[]}))))
    assert r.status=='insufficient_evidence' and r.generation.status=='abstained'
    assert r.answer is None and not r.sources


def test_english_prompt_and_chinese_generated_claim_rejected(store):
    def handle(request):
        body=json.loads(request.content)
        system=body['systemInstruction']['parts'][0]['text']
        assert 'Answer in English' in system and 'change the answer language' in system
        payload={'status':'answered','claims':[{'text':'\u4e2d\u6587\u56de\u7b54','citation_ids':['doc-fields']}]}
        return httpx.Response(200,json=envelope(payload))
    r=ask(agent_with(store,handle))
    assert r.status=='upstream_error' and r.reason_code=='llm_output_language_error'
    assert not r.answer and not r.claims and not r.sources


def test_combined_requires_both_types_of_evidence(store):
    body={'status':'answered','claims':[{'text':'An authentication header is required','citation_ids':['doc-auth']}]}
    r=agent_with(store,lambda req:httpx.Response(200,json=envelope(body))).ask(AskRequest(question='Official authentication headers and code',answer_mode='gemini'))
    assert r.reason_code=='llm_incomplete_evidence_coverage'
    assert r.mode=='combined' and r.documentation and r.repository
    assert r.warnings and r.branches and not r.sources


def test_large_or_malformed_payloads(store):
    for body,reason in [(b'x'*128001,'llm_response_too_large'),(b'bad json','llm_invalid_response')]:
        r=ask(agent_with(store,lambda req:httpx.Response(200,content=body)))
        assert r.reason_code==reason
    agent=CustomerSupportAgent(CodeAnalyzerAgent(store))
    evidence=agent.ask(AskRequest(question='API required fields'))
    evidence.sources[0].evidence='X'*48000
    with pytest.raises(GenerationError,match='llm_input_budget_exceeded'):
        GeminiClient(GeminiSettings()).build_request(AskRequest(question='API required fields'),evidence)


def test_http_api_configuration_is_local_and_no_key_exposed(store):
    def forbidden(request):pytest.fail('Configuration endpoint must not call Gemini')
    agent=agent_with(store,forbidden)
    with TestClient(create_app(agent)) as c:
        r=c.get('/generation')
        assert r.json()['status']=='configured_not_connection_tested'
        assert r.json()['default_answer_mode']=='auto' and KEY not in r.text
        assert c.get('/health').status_code==200
    agent=CustomerSupportAgent(CodeAnalyzerAgent(store))
    with TestClient(create_app(agent)) as c:
        r=c.post('/ask',json={'question':'API required fields','answer_mode':'gemini'})
        assert r.status_code==503 and r.json()['reason_code']=='llm_not_enabled'
        assert c.post('/ask',json={'question':'API required fields','api_key':KEY}).status_code==422


def test_combined_success_keeps_both_provenances(store):
    def handle(request):
        data = json.loads(json.loads(request.content)['contents'][0]['parts'][0]['text'])
        body = {'status': 'answered', 'claims': [
            {'text': 'Both evidence types are listed independently; version alignment is not assumed.',
             'citation_ids': [s['chunk_id'] for s in data['evidence']]}]}
        return httpx.Response(200, json=envelope(body))
    r = agent_with(store, handle).ask(AskRequest(question='Official authentication headers and code', answer_mode='gemini'))
    assert r.status == 'answered' and r.generation.status == 'completed'
    assert {s.evidence_kind for s in r.sources} == {'curated_document_summary', 'code_excerpt'}
    assert r.documentation and r.repository and r.warnings


def test_cli_dry_run_never_reads_configuration_or_calls_model(store, monkeypatch):
    from scripts import try_gemini
    monkeypatch.setenv('ENABLE_GEMINI', '1')
    monkeypatch.setenv('GEMINI_API_KEY', KEY)
    monkeypatch.setattr(try_gemini, 'CustomerSupportAgent', lambda *args: CustomerSupportAgent(CodeAnalyzerAgent(store)))
    def forbidden(*args):
        pytest.fail('Dry run must not read configuration or call a provider')
    monkeypatch.setattr(GeminiSettings, 'from_env', forbidden)
    monkeypatch.setattr(GeminiClient, 'generate', forbidden)
    result, code = try_gemini.execute()
    assert code == 0 and result['live'] is False and result['model_requests'] == 0
    assert result['payload_characters'] > 0 and 'doc-fields' in result['citation_ids']
    assert KEY not in json.dumps(result)


def test_cli_live_missing_config_makes_no_call():
    from scripts.try_gemini import execute
    result, code = execute(live=True)
    assert code == 1 and result['model_requests'] == 0
    assert result['reason_code'] == 'llm_not_enabled'


def test_live_smoke_suite_stops_at_first_failure_and_separates_report(tmp_path, monkeypatch, capsys):
    from evals import run_gemini
    calls = []
    def fake_execute(question, task, backend, live):
        calls.append(live)
        return {'live': live, 'status': 'configuration_error', 'model_requests': 0}, 1
    monkeypatch.setattr(run_gemini, 'execute', fake_execute)
    monkeypatch.setattr(run_gemini, '__file__', str(tmp_path / 'run_gemini.py'))
    assert run_gemini.run(live=True, limit=3) == 1
    report = json.loads((tmp_path / 'gemini-live-latest.json').read_text(encoding='utf-8'))
    assert calls == [True] and report['completed_cases'] == 1
    assert report['semantic_quality'] == 'unassessed' and report['billed_cost'] == 'not_measured'
