import json
from decimal import Decimal

import httpx
import pytest

from app.llm_proposer import AzureConfig, LLMError, azure_config_from_env, propose_with_llm
from app.proposer import ExtractionError

CONFIG = AzureConfig(endpoint="https://example-resource.openai.azure.com", api_key="test-key", deployment="gpt-test")
DOC = "Invoice: INV-2041\nDate: 2026-10-03\nVendor: Northwind Cloud\nCategory: software\nTotal: 480.00\nStatus: unpaid\nDescription: Monthly hosting"


def fake_transport(content: dict | str, status: int = 200) -> httpx.MockTransport:
    body = content if isinstance(content, str) else json.dumps(content)

    def handler(request: httpx.Request) -> httpx.Response:
        if status != 200:
            return httpx.Response(status, json={"error": "nope"})
        return httpx.Response(200, json={"choices": [{"message": {"content": body}}]})

    return httpx.MockTransport(handler)


GOOD = {
    "date": "2026-10-03",
    "vendor": "Northwind Cloud",
    "description": "Monthly hosting",
    "source_ref": "INV-2041",
    "amount": "480.00",
    "debit_account": "6200",
    "credit_account": "2000",
}


def test_valid_model_answer_becomes_entry_with_provenance():
    entry, extra = propose_with_llm(DOC, CONFIG, transport=fake_transport(GOOD))
    assert extra == []
    assert entry.proposed_by == "azure-openai:gpt-test"
    assert entry.lines[0].account == "6200" and entry.lines[0].debit == Decimal("480.00")
    assert entry.lines[1].account == "2000" and entry.lines[1].credit == Decimal("480.00")


def test_amount_not_in_document_is_flagged_as_extra_issue():
    wrong = {**GOOD, "amount": "580.00"}
    _, extra = propose_with_llm(DOC, CONFIG, transport=fake_transport(wrong))
    assert any("does not appear in the source document" in issue for issue in extra)


def test_model_error_becomes_extraction_error():
    with pytest.raises(ExtractionError, match="missing a total"):
        propose_with_llm(DOC, CONFIG, transport=fake_transport({"error": "missing a total"}))


def test_missing_key_is_extraction_error():
    partial = {k: v for k, v in GOOD.items() if k != "credit_account"}
    with pytest.raises(ExtractionError, match="credit_account"):
        propose_with_llm(DOC, CONFIG, transport=fake_transport(partial))


def test_http_error_is_llm_error():
    with pytest.raises(LLMError, match="HTTP 500"):
        propose_with_llm(DOC, CONFIG, transport=fake_transport("", status=500))


def test_non_json_content_is_llm_error():
    with pytest.raises(LLMError, match="unexpected response"):
        propose_with_llm(DOC, CONFIG, transport=fake_transport("not json"))


def test_config_absent_without_all_three_variables(monkeypatch):
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_DEPLOYMENT", raising=False)
    assert azure_config_from_env() is None


def test_config_read_from_environment(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "k")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
    config = azure_config_from_env()
    assert config is not None
    assert config.deployment == "gpt-4o-mini"
    assert config.api_version == "2024-10-21"
