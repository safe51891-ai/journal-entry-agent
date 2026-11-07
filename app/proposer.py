"""Turns a plain-text source document (invoice, sales invoice) into a proposed journal entry.

This is a rule-based stand-in for the LLM step. Its output still goes through ledger.validate,
so swapping in a model later does not weaken the controls.
"""
import re
from decimal import Decimal, InvalidOperation

from .models import JournalEntry, Line

CATEGORY_ACCOUNTS = {
    "office": "6100",
    "software": "6200",
    "travel": "6300",
    "legal": "6400",
    "consulting": "6400",
}

FIELD_RE = re.compile(r"^\s*([A-Za-z ]+?)\s*:\s*(.+?)\s*$", re.MULTILINE)


class ExtractionError(ValueError):
    """Raised when a document lacks the fields needed to propose an entry."""


def _fields(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for match in FIELD_RE.finditer(text):
        found.setdefault(match.group(1).strip().lower(), match.group(2).strip())
    return found


def _amount(raw: str) -> Decimal:
    cleaned = raw.replace(",", "").replace("USD", "").strip()
    try:
        return Decimal(cleaned).quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise ExtractionError(f"cannot read amount '{raw}'") from exc


def propose_entry(text: str) -> JournalEntry:
    fields = _fields(text)
    for required in ("date", "total", "description"):
        if required not in fields:
            raise ExtractionError(f"missing field: {required}")

    total = _amount(fields["total"])
    description = fields["description"]
    vendor = fields.get("vendor", "")
    label = f"{vendor} - {description}" if vendor else description

    if fields.get("type", "purchase").lower() == "sales":
        debit_account, credit_account = "1200", "4000"  # receivable / revenue
    else:
        category = fields.get("category", "").lower()
        expense_account = CATEGORY_ACCOUNTS.get(category, f"UNMAPPED:{category or 'none'}")
        paid = fields.get("status", "unpaid").lower() == "paid"
        debit_account = expense_account
        credit_account = "1000" if paid else "2000"  # cash / payable

    return JournalEntry(
        date=fields["date"],
        description=label,
        source_ref=fields.get("invoice", ""),
        lines=[
            Line(account=debit_account, debit=total, memo=description),
            Line(account=credit_account, credit=total, memo=description),
        ],
    )
