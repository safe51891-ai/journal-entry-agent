"""Data models for journal entries."""
import uuid
from decimal import Decimal

from pydantic import BaseModel, Field


class Line(BaseModel):
    account: str
    debit: Decimal = Decimal("0")
    credit: Decimal = Decimal("0")
    memo: str = ""


class JournalEntry(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    date: str
    description: str
    source_ref: str = ""
    proposed_by: str = "rules"  # "rules" or "azure-openai:<deployment>"
    lines: list[Line]
    status: str = "pending"  # pending | needs_review | approved | rejected
    issues: list[str] = Field(default_factory=list)
