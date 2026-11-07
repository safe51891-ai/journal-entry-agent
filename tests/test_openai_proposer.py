import json
from decimal import Decimal

import httpx
import pytest

from app.llm_proposer import (
    DEFAULT_OPENAI_MODEL,
    OPENAI_URL,
    LLMError,
    OpenAIConfig,
    openai_config_from_env,
    propose_with_openai,
)
from app.proposer import ExtractionError

CONFIG = OpenAIConfig(api_key="sk-test", model="gpt-6-luna")
DOC = "Invoice: INV-2041\nDate: 2026-10-03\nVendor: Northwind Cloud\nCategory: software\nTotal: 480.00\nStatus: unpaid\nDescription: Monthly hosting"

GOOD = {
    "date": "2026-10-03",
    "vendor": "Northwind Cloud",
    "description": "Monthly hosting",
    "source_ref": "INV-2041",
    "amount": "480.00",
    "debit_account": "6200",
    "credit_account": "2000",
}


def fake_transport(content: dict | str, status: int = 200, seen: list | None = None) -> httpx.MockTransport:
    body = content if isinstance(content, str) else json.dumps(content)

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if status != 200:
            return httpx.Response(status, json={"error": "nope"})
        return httpx.Response(200, json={"choices": [{"message": {"content": body}}]})

    return httpx.MockTransport(handler)


def test_valid_answer_becomes_entry_with_openai_provenance():
    entry, extra = propose_with_openai(DOC, CONFIG, transport=fake_transport(GOOD))
    assert extra == []
    assert entry.proposed_by == "openai:gpt-6-luna"
    assert entry.lines[0].account == "6200" and entry.lines[0].debit == Decimal("480.00")
    assert entry.lines[1].account == "2000" and entry.lines[1].credit == Decimal("480.00")


def test_request_uses_bearer_key_json_mode_and_cheapest_settings():
    seen: list[httpx.Request] = []
    propose_with_openai(DOC, CONFIG, transport=fake_transport(GOOD, seen=seen))
    request = seen[0]
    assert str(request.url) == OPENAI_URL
    assert request.headers["authorization"] == "Bearer sk-test"
    body = json.loads(request.content)
    assert body["model"] == "gpt-6-luna"
    assert body["response_format"] == {"type": "json_object"}
    assert body["reasoning_effort"] == "none"
    assert body["messages"][1] == {"role": "user", "content": DOC}


def test_amount_not_in_document_is_flagged():
    _, extra = propose_with_openai(DOC, CONFIG, transport=fake_transport({**GOOD, "amount": "580.00"}))
    assert any("does not appear in the source document" in issue for issue in extra)


def test_model_error_becomes_extraction_error():
    with pytest.raises(ExtractionError, match="missing a total"):
        propose_with_openai(DOC, CONFIG, transport=fake_transport({"error": "missing a total"}))


def test_http_error_is_llm_error_without_leaking_key():
    with pytest.raises(LLMError, match="HTTP 401") as info:
        propose_with_openai(DOC, CONFIG, transport=fake_transport("", status=401))
    assert "sk-test" not in str(info.value)


def test_non_json_content_is_llm_error():
    with pytest.raises(LLMError, match="unexpected response"):
        propose_with_openai(DOC, CONFIG, transport=fake_transport("not json"))


def test_config_absent_without_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert openai_config_from_env() is None


def test_config_defaults_to_cheapest_model(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    config = openai_config_from_env()
    assert config is not None
    assert config.model == DEFAULT_OPENAI_MODEL == "gpt-6-luna"


def test_model_can_be_overridden(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5.6-luna")
    assert openai_config_from_env().model == "gpt-5.6-luna"
