import json
import logging
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.knowledge import DEFAULT_CORPUS, KnowledgeStore, KnowledgeUnavailable
from app.main import create_app
from app.models import AskRequest
from app.service import KnowledgeAssistant
from evals.run import AS_OF, CASES, ScenarioStore, evaluate_case


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_regression_case(case):
    result = evaluate_case(case)
    assert result["passed"], result


@pytest.fixture
def client():
    return TestClient(create_app(KnowledgeAssistant(today=lambda: AS_OF)))


def test_api_success_and_provenance(client):
    response = client.post("/ask", json={"question": "Peach 随身行李重量限制？"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "answered"
    assert response.headers["X-Request-ID"] == data["request_id"]
    assert len(data["corpus_sha256"]) == 64
    assert data["claims"][0]["citation_ids"] == [data["sources"][0]["chunk_id"]]
    assert data["claims"][0]["text"] == data["sources"][0]["evidence"] == data["answer"]


@pytest.mark.parametrize("question", ["", " ", "a", "x" * 1501])
def test_invalid_question(client, question):
    assert client.post("/ask", json={"question": question}).status_code == 422


def test_invalid_slots_and_extra_fields(client):
    assert client.post("/ask", json={"question": "行李政策", "context": {"fare_type": "invented"}}).status_code == 422
    assert client.post("/ask", json={"question": "行李政策", "simulate_error": True}).status_code == 422


def test_actual_missing_storage_maps_to_503(tmp_path):
    app = create_app(KnowledgeAssistant(KnowledgeStore(tmp_path / "missing.json"), today=lambda: AS_OF))
    with TestClient(app) as client:
        result = client.post("/ask", json={"question": "Peach 手提行李重量限制？"})
        assert result.status_code == 503
        assert result.json()["status"] == "upstream_error"
        assert result.json()["answer"] is None
        assert client.get("/health").status_code == 503
        assert client.get("/knowledge").status_code == 503


@pytest.mark.parametrize("fault", ["bad_json", "unknown_doc", "duplicate_id", "untrusted_url"])
def test_corrupt_corpus_fails_closed(tmp_path, fault):
    path = tmp_path / "bad.json"
    data = json.loads(DEFAULT_CORPUS.read_text(encoding="utf-8"))
    if fault == "unknown_doc":
        data["chunks"][0]["document_id"] = "missing"
    elif fault == "duplicate_id":
        data["chunks"][1]["id"] = data["chunks"][0]["id"]
    elif fault == "untrusted_url":
        data["documents"][0]["url"] = "https://example.com/fake"
    path.write_text("not json" if fault == "bad_json" else json.dumps(data), encoding="utf-8")
    with pytest.raises(KnowledgeUnavailable):
        KnowledgeStore(path).load()


@pytest.mark.parametrize("age,expected", [(-1, "insufficient_evidence"), (0, "answered"), (30, "answered"), (31, "insufficient_evidence")])
def test_review_window_boundary(age, expected):
    service = KnowledgeAssistant(today=lambda: AS_OF + timedelta(days=age))
    assert service.ask(AskRequest(question="Peach 手提行李重量限制？")).status == expected


def test_stateless_clarification_then_answer(client):
    question = "Peach 可以改签吗？"
    first = client.post("/ask", json={"question": question}).json()
    assert first["status"] == "needs_clarification"
    second = client.post("/ask", json={"question": question, "context": {
        "fare_type": "standard_plus", "reason": "voluntary", "booking_channel": "direct"}}).json()
    assert second["status"] == "answered"
    assert second["sources"][0]["chunk_id"] == "change-plus"


def test_question_is_not_logged(caplog):
    marker = "PRIVATE-PASSENGER-NAME"
    with caplog.at_level(logging.INFO, logger="travel_ops"):
        KnowledgeAssistant(today=lambda: AS_OF).ask(AskRequest(question="Peach 手提行李重量限制？" + marker))
    assert marker not in caplog.text
    assert "request_id=" in caplog.text


def test_page_assets_and_catalog(client):
    page = client.get("/")
    assert page.status_code == 200
    assert "政策知识工作台" in page.text
    assert "Content-Security-Policy" in page.headers
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/styles.css").status_code == 200
    assert client.get("/knowledge").json()["chunk_count"] == 11
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/openapi.json").status_code == 200


@pytest.mark.parametrize("question,context,code", [
    ("Peach 因天气改签", {"reason": "voluntary"}, "conflicting_context"),
    ("Peach 官网 Standard 退款", {"booking_channel": "agency"}, "conflicting_context"),
    ("Peach Minimum 和 Standard 能改签吗？", {}, "multiple_fares"),
    ("Peach 托运行李重量和免费额度？", {}, "multiple_topics"),
    ("Peach 随身行李与托运行李政策", {}, "multiple_topics"),
    ("Peach 托运行李怎么购买？", {}, "detail_not_covered"),
    ("Peach Standard Plus 个人原因改签可以换目的地吗？", {"booking_channel": "direct"}, "detail_not_covered"),
    ("Peach 不是个人原因退款", {"fare_type": "standard", "booking_channel": "direct"}, "ambiguous_context"),
    ("Peach 官网 Standard 取消手续费是多少？", {"reason": "voluntary"}, "detail_not_covered"),
])
def test_context_and_scope_edges(question, context, code):
    result = KnowledgeAssistant(today=lambda: AS_OF).ask(AskRequest(question=question, context=context))
    assert result.reason_code == code
    assert result.answer is None


@pytest.mark.parametrize("question", [
    "客人不去了，这张票能退吗？",
    "买的是最便宜那档，想换一天飞。",
    "客人想改天飞，可以吗？",
])
def test_colloquial_intent_does_not_invent_context(client, question):
    data = client.post("/ask", json={"question": question, "context": {"airline": "peach"}}).json()
    assert data["reason_code"] == "missing_policy_context"
    assert data["context"]["fare_type"] is None
    assert data["context"]["reason"] is None
    assert data["context"]["booking_channel"] is None
    questions = "".join(data["clarifying_questions"])
    assert all(word in questions for word in ["票价类型", "退改原因", "购票渠道"])


def test_colloquial_clarification_can_be_resolved(client):
    question = "买的是最便宜那档，想换一天飞。"
    data = client.post("/ask", json={"question": question, "context": {
        "airline": "peach", "fare_type": "standard_plus", "reason": "voluntary", "booking_channel": "direct"}}).json()
    # Price descriptions cannot override the confirmed fare family.
    assert data["status"] == "answered"
    assert data["sources"][0]["chunk_id"] == "change-plus"


@pytest.mark.parametrize("question", [
    "客人说是 Standard，但订单显示 Minimum。",
    "客户表示是Standard Plus，行程单标注Minimum。",
    "旅客说Minimum，票面写着Standard。",
])
def test_reported_conflict_requests_verification_not_arbitrary_choice(client, question):
    data = client.post("/ask", json={"question": question, "context": {"airline": "peach"}}).json()
    assert data["reason_code"] == "conflicting_context"
    assert data["context"]["fare_type"] is None
    prompt = "".join(data["clarifying_questions"])
    assert "不一致" in prompt and "核对" in prompt


@pytest.mark.parametrize("question", [
    "酒店想换一天住", "客人想换一天上班", "客人不去了，怎么联系？",
])
def test_colloquial_rules_do_not_turn_other_requests_into_flight_changes(client, question):
    data = client.post("/ask", json={"question": question, "context": {
        "airline": "peach", "fare_type": "standard_plus", "reason": "voluntary", "booking_channel": "direct"}}).json()
    assert data["status"] == "insufficient_evidence"
