"""Extraction: provenance, clarification, validation of LLM output, fallbacks and failures.

No real hosted model is called. LLM behaviour is simulated with httpx.MockTransport,
which exercises the real request-building and response-parsing code.
"""
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app import time_utils as tu
from app.config import get_settings
from app.db import new_session
from app.evaluation import extraction_eval
from app.services import extraction
from app.services.llm import providers
from app.services.ml import classifier, train
from tests.conftest import ASHA, login

MONDAY_8AM = datetime(2026, 11, 2, 2, 30, tzinfo=timezone.utc)


@pytest.fixture(scope="module", autouse=True)
def model():
    if classifier.get_model_info() is None:
        train.train()
        classifier.reload()


@pytest.fixture()
def frozen():
    tu.freeze(MONDAY_8AM)
    yield
    tu.freeze(None)


@pytest.fixture()
def llm_on(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("LLM_API_KEY", "sk-test-not-real")
    get_settings.cache_clear()
    yield
    providers.set_transport(None)
    monkeypatch.setenv("LLM_PROVIDER", "none")
    get_settings.cache_clear()


def anthropic_reply(fields: dict, status: int = 200):
    def handler(request: httpx.Request):
        assert request.headers["x-api-key"] == "sk-test-not-real"
        body = json.loads(request.content)
        assert body["tool_choice"]["name"] == "extract_booking_request"
        return httpx.Response(status, json={"content": [{"type": "tool_use", "name": "x", "input": fields}],
                                            "usage": {"input_tokens": 321, "output_tokens": 45}})
    return httpx.MockTransport(handler)


def test_example_request_with_provenance(seeded, frozen):
    with new_session() as db:
        r, _ = extraction.extract(db, "My kitchen tap is leaking. I need a plumber tomorrow morning in Wakad.")
    assert r.method == "rules" and r.method_label == "Rules-based extraction (no LLM used)"
    assert r.predicted_category.value == "plumbing" and r.predicted_category.source == "ml_model"
    assert r.locality.value == "wakad" and r.locality.source == "user_text" and r.locality.evidence == "Wakad"
    assert r.preferred_date.value == "2026-11-03" and r.preferred_date.source == "inferred"
    assert "Tuesday, 03 November 2026" in r.preferred_date.display  # resolved date is shown
    assert r.time_window.value == "morning"
    assert r.issue_description.value == "My kitchen tap is leaking."
    assert r.missing_fields == []


def test_missing_fields_produce_focused_questions(seeded, frozen):
    with new_session() as db:
        r, _ = extraction.extract(db, "Washing machine is not spinning")
    assert r.missing_fields == ["locality", "preferred_date", "time_window"]
    q = {x.field: x for x in r.questions}
    assert {o["value"] for o in q["locality"].options} == {"wakad", "hinjawadi", "baner", "aundh"}
    assert q["preferred_date"].options[1]["label"].startswith("Tomorrow, Tue 03 Nov")


def test_never_invents_unsupported_locality(seeded, frozen):
    with new_session() as db:
        r, _ = extraction.extract(db, "MCB keeps tripping. I am in Kothrud, tomorrow afternoon")
    assert r.locality.value is None and "locality" in r.missing_fields
    assert any("Kothrud" in n for n in r.notes)


def test_out_of_horizon_date_is_not_accepted(seeded, frozen):
    with new_session() as db:
        r, _ = extraction.extract(db, "Fridge not cooling, Wakad, 25 December")
    assert r.preferred_date.value is None and any("next 7 days" in n for n in r.notes)


def test_overrides_are_validated_and_marked(seeded, frozen):
    with new_session() as db:
        r, _ = extraction.extract(db, "Washing machine is not spinning")
        r2 = extraction.apply_overrides(db, r, {"locality": "aundh", "preferred_date": "2026-11-04",
                                                "time_window": "evening"})
        assert r2.missing_fields == [] and r2.locality.source == "user_edit"
        with pytest.raises(extraction.OverrideError):
            extraction.apply_overrides(db, r, {"locality": "mumbai"})
        with pytest.raises(extraction.OverrideError):
            extraction.apply_overrides(db, r, {"preferred_date": "2026-12-25"})


def test_dangerous_electrical_issue_gets_safety_notice(seeded, frozen):
    with new_session() as db:
        r, _ = extraction.extract(db, "Burning smell and sparks from the switch board in Baner")
    assert r.safety_notice and "Do not attempt a DIY repair" in r.safety_notice


def test_llm_output_is_validated_against_user_words(seeded, frozen, llm_on):
    # The fake LLM invents a locality and a time the user never said.
    providers.set_transport(anthropic_reply({
        "issue_description": "Kitchen tap leaking", "locality": "baner", "date_expression": "tomorrow",
        "resolved_date": "2026-11-03", "time_expression": "at 9 am", "time_window": "at:9"}))
    with new_session() as db:
        r, info = extraction.extract(db, "kitchen tap leaking, come tomorrow")
    assert r.method == "llm"
    assert r.locality.value is None, "invented locality must be rejected"
    assert r.time_window.value is None, "invented time must be rejected"
    assert r.preferred_date.value == "2026-11-03"
    assert info["llm_usage"]["input_tokens"] == 321
    assert any("rejected" in n for n in r.notes)


def test_llm_wrong_date_resolution_is_caught(seeded, frozen, llm_on):
    providers.set_transport(anthropic_reply({
        "issue_description": "Fan slow", "locality": "aundh", "date_expression": "tomorrow",
        "resolved_date": "2026-11-05", "time_expression": None, "time_window": None}))
    with new_session() as db:
        r, _ = extraction.extract(db, "Fan slow in Aundh tomorrow")
    assert r.preferred_date.value is None and any("Please confirm the day" in n for n in r.notes)


def test_llm_failure_falls_back_to_labelled_rules(seeded, frozen, llm_on):
    providers.set_transport(httpx.MockTransport(lambda req: httpx.Response(500, json={"error": "boom"})))
    with new_session() as db:
        r, _ = extraction.extract(db, "Tap leaking in Wakad tomorrow morning")
    assert r.method == "rules" and "fallback" in r.method_label and "unavailable" in r.method_label
    assert r.locality.value == "wakad"


def test_openai_adapter_parses_structured_output(llm_on, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    get_settings.cache_clear()

    def handler(request):
        body = json.loads(request.content)
        assert body["response_format"]["type"] == "json_schema"
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({"a": 1})}}],
                                         "usage": {"prompt_tokens": 10, "completion_tokens": 2}})
    providers.set_transport(httpx.MockTransport(handler))
    res = providers.complete_json("sys", "user", {"type": "object"}, "x")
    assert res.data == {"a": 1} and res.input_tokens == 10 and res.provider == "openai"


def test_cost_is_only_an_estimate_when_prices_configured(llm_on, monkeypatch):
    assert providers.estimate_cost(1000, 100) is None
    monkeypatch.setenv("LLM_INPUT_PRICE_PER_MTOK", "3")
    monkeypatch.setenv("LLM_OUTPUT_PRICE_PER_MTOK", "15")
    get_settings.cache_clear()
    est = providers.estimate_cost(1_000_000, 100_000)
    assert est["value"] == 4.5 and "ESTIMATE" in est["label"]


def test_interpret_endpoint_end_to_end(seeded, client):
    h = login(client, ASHA)
    r = client.post("/api/requests/interpret", headers={**h, "X-Developer-Mode": "1"},
                    json={"text": "My kitchen tap is leaking. I need a plumber tomorrow in Wakad.",
                          "overrides": {"time_window": "any"}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ready"] is True and body["search"]["technicians"]
    comps = [s["component"] for s in body["trace"]["steps"]]
    assert {"extraction", "ml_classification", "validation", "technician_matching"} <= set(comps)
    assert "password" not in json.dumps(body["trace"]).lower()


def test_extraction_eval_suite_runs(seeded):
    out = extraction_eval.run("rules")
    assert out["summary"]["cases"] >= 25
    assert out["summary"]["overall_field_accuracy"] > 0.8
