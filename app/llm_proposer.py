"""LLM proposer using an Azure OpenAI deployment (Azure AI Foundry).

The model only proposes. Its output is checked here (amount must appear in the source text)
and then by ledger.validate, the same as the rule-based proposer. A wrong answer gets flagged.

Configuration (environment variables, never stored in the repo):
  AZURE_OPENAI_ENDPOINT     e.g. https://<resource>.openai.azure.com
  AZURE_OPENAI_API_KEY      key from the Azure portal (Keys and Endpoint)
  AZURE_OPENAI_DEPLOYMENT   your model deployment name, e.g. gpt-4o-mini
  AZURE_OPENAI_API_VERSION  optional, default 2024-10-21
"""
import json
import os
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import httpx

from .models import JournalEntry, Line
from .proposer import ExtractionError

DEFAULT_API_VERSION = "2024-10-21"

SYSTEM_PROMPT = """You convert one finance source document into a single journal entry.
Return only a JSON object with these keys:
  date (YYYY-MM-DD), vendor, description, source_ref, amount (positive decimal string),
  debit_account, credit_account.
Chart of accounts: 1000 Cash, 1200 Accounts receivable, 2000 Accounts payable,
4000 Service revenue, 6100 Office supplies, 6200 Software subscriptions, 6300 Travel,
6400 Professional fees.
Rules:
- Purchase, unpaid: debit the expense account, credit 2000.
- Purchase, paid: debit the expense account, credit 1000.
- Sales invoice: debit 1200, credit 4000.
- Choose the expense account from the document's category.
- Copy the amount exactly from the document. Never invent values.
If a required value is missing or unreadable, return {"error": "<short reason>"}."""

REQUIRED_KEYS = ("date", "description", "amount", "debit_account", "credit_account")


class LLMError(RuntimeError):
    """The model call failed (network, HTTP error, or malformed response)."""


@dataclass(frozen=True)
class AzureConfig:
    endpoint: str
    api_key: str
    deployment: str
    api_version: str = DEFAULT_API_VERSION


def azure_config_from_env() -> AzureConfig | None:
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
    api_key = os.getenv("AZURE_OPENAI_API_KEY", "").strip()
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "").strip()
    if not (endpoint and api_key and deployment):
        return None
    return AzureConfig(
        endpoint=endpoint,
        api_key=api_key,
        deployment=deployment,
        api_version=os.getenv("AZURE_OPENAI_API_VERSION", DEFAULT_API_VERSION).strip(),
    )


DEFAULT_OPENAI_MODEL = "gpt-6-luna"  # lowest-cost current OpenAI text model; see README
OPENAI_URL = "https://api.openai.com/v1/chat/completions"


@dataclass(frozen=True)
class OpenAIConfig:
    api_key: str
    model: str = DEFAULT_OPENAI_MODEL


def openai_config_from_env() -> OpenAIConfig | None:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None
    return OpenAIConfig(api_key=api_key, model=os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL).strip())


def _call_openai(document: str, config: OpenAIConfig, transport: httpx.BaseTransport | None) -> dict:
    body = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": document},
        ],
        "response_format": {"type": "json_object"},
        # Cheapest setting: no hidden reasoning tokens, which are billed as output.
        "reasoning_effort": "none",
    }
    try:
        with httpx.Client(timeout=30, transport=transport) as client:
            response = client.post(
                OPENAI_URL,
                headers={"Authorization": f"Bearer {config.api_key}"},
                json=body,
            )
    except httpx.HTTPError as exc:
        raise LLMError(f"could not reach OpenAI: {exc.__class__.__name__}") from exc

    if response.status_code >= 400:
        raise LLMError(f"OpenAI returned HTTP {response.status_code}")
    try:
        content = response.json()["choices"][0]["message"]["content"]
        return json.loads(content)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise LLMError("OpenAI returned an unexpected response") from exc


def propose_with_openai(
    document: str,
    config: OpenAIConfig,
    transport: httpx.BaseTransport | None = None,
) -> tuple[JournalEntry, list[str]]:
    """Same contract as propose_with_llm, using the OpenAI platform API."""
    data = _call_openai(document, config, transport)
    return entry_from_model_output(document, data, f"openai:{config.model}")


def _document_amounts(document: str) -> set[Decimal]:
    amounts: set[Decimal] = set()
    for raw in re.findall(r"-?\d[\d,]*(?:\.\d+)?", document):
        try:
            amounts.add(Decimal(raw.replace(",", "")).quantize(Decimal("0.01")))
        except InvalidOperation:
            continue
    return amounts


def _call_model(document: str, config: AzureConfig, transport: httpx.BaseTransport | None) -> dict:
    url = f"{config.endpoint.rstrip('/')}/openai/deployments/{config.deployment}/chat/completions"
    body = {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": document},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0,
    }
    try:
        with httpx.Client(timeout=30, transport=transport) as client:
            response = client.post(
                url,
                params={"api-version": config.api_version},
                headers={"api-key": config.api_key},
                json=body,
            )
    except httpx.HTTPError as exc:
        raise LLMError(f"could not reach Azure OpenAI: {exc.__class__.__name__}") from exc

    if response.status_code >= 400:
        raise LLMError(f"Azure OpenAI returned HTTP {response.status_code}")
    try:
        content = response.json()["choices"][0]["message"]["content"]
        return json.loads(content)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise LLMError("Azure OpenAI returned an unexpected response") from exc


def propose_with_llm(
    document: str,
    config: AzureConfig,
    transport: httpx.BaseTransport | None = None,
) -> tuple[JournalEntry, list[str]]:
    """Return (proposed entry, extra issues found by the guardrails before validation)."""
    data = _call_model(document, config, transport)
    return entry_from_model_output(document, data, f"azure-openai:{config.deployment}")


def entry_from_model_output(document: str, data: dict, proposed_by: str) -> tuple[JournalEntry, list[str]]:
    """Turn the model's JSON into an entry, applying the guardrails shared by every LLM provider."""
    if "error" in data:
        raise ExtractionError(str(data["error"]))
    missing = [key for key in REQUIRED_KEYS if not data.get(key)]
    if missing:
        raise ExtractionError(f"model omitted: {', '.join(missing)}")

    try:
        amount = Decimal(str(data["amount"])).quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise ExtractionError(f"model returned an unreadable amount '{data['amount']}'") from exc

    extra_issues: list[str] = []
    if amount not in _document_amounts(document):
        extra_issues.append(f"amount {amount} does not appear in the source document")

    vendor = str(data.get("vendor", "")).strip()
    description = str(data["description"]).strip()
    label = f"{vendor} - {description}" if vendor else description

    entry = JournalEntry(
        date=str(data["date"]),
        description=label,
        source_ref=str(data.get("source_ref", "")),
        proposed_by=proposed_by,
        lines=[
            Line(account=str(data["debit_account"]), debit=amount, memo=description),
            Line(account=str(data["credit_account"]), credit=amount, memo=description),
        ],
    )
    return entry, extra_issues
