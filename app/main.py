"""FastAPI backend: propose journal entries from documents, validate, and approve or reject."""
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .ledger import CHART, validate
from .llm_proposer import (
    LLMError,
    azure_config_from_env,
    openai_config_from_env,
    propose_with_llm,
    propose_with_openai,
)
from .models import JournalEntry
from .proposer import ExtractionError, propose_entry
from .store import EntryStore

ROOT = Path(__file__).resolve().parent.parent

app = FastAPI(title="Journal Entry Agent")
store = EntryStore()


class ProposeRequest(BaseModel):
    document: str = Field(min_length=10, max_length=20000)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/accounts")
def accounts() -> list[dict[str, str]]:
    return [{"code": code, "name": name, "type": kind} for code, (name, kind) in CHART.items()]


@app.get("/api/config")
def config() -> dict[str, str]:
    """Tells the frontend which proposer is active. Never returns secrets."""
    openai = openai_config_from_env()
    if openai:
        return {"proposer": f"openai:{openai.model}"}
    azure = azure_config_from_env()
    return {"proposer": f"azure-openai:{azure.deployment}" if azure else "rules"}


@app.get("/api/samples")
def samples() -> list[dict[str, str]]:
    data = json.loads((ROOT / "data" / "synthetic_documents.json").read_text())
    return [{"id": item["id"], "text": item["text"]} for item in data]


@app.post("/api/propose", status_code=201)
def propose(request: ProposeRequest) -> JournalEntry:
    extra_issues: list[str] = []
    openai = openai_config_from_env()
    azure = azure_config_from_env()
    try:
        if openai:
            entry, extra_issues = propose_with_openai(request.document, openai)
        elif azure:
            entry, extra_issues = propose_with_llm(request.document, azure)
        else:
            entry = propose_entry(request.document)
    except ExtractionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    entry.issues = extra_issues + validate(entry)
    entry.status = "needs_review" if entry.issues else "pending"
    return store.add(entry)


@app.get("/api/entries")
def entries() -> list[JournalEntry]:
    return store.all()


def _get_or_404(entry_id: str) -> JournalEntry:
    entry = store.get(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="entry not found")
    return entry


@app.post("/api/entries/{entry_id}/approve")
def approve(entry_id: str) -> JournalEntry:
    entry = _get_or_404(entry_id)
    if entry.issues:
        raise HTTPException(status_code=409, detail="entry has validation issues and cannot be approved")
    if entry.status != "pending":
        raise HTTPException(status_code=409, detail=f"entry is {entry.status}")
    entry.status = "approved"
    return entry


@app.post("/api/entries/{entry_id}/reject")
def reject(entry_id: str) -> JournalEntry:
    entry = _get_or_404(entry_id)
    if entry.status not in ("pending", "needs_review"):
        raise HTTPException(status_code=409, detail=f"entry is {entry.status}")
    entry.status = "rejected"
    return entry
