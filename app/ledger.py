"""Deterministic validation rules. These run on every entry, whatever proposed it.

An AI proposer can be wrong; these checks decide whether an entry may be approved.
"""
from datetime import date
from decimal import Decimal

from .models import JournalEntry

# Chart of accounts: code -> (name, type)
CHART: dict[str, tuple[str, str]] = {
    "1000": ("Cash", "asset"),
    "1200": ("Accounts receivable", "asset"),
    "2000": ("Accounts payable", "liability"),
    "4000": ("Service revenue", "revenue"),
    "6100": ("Office supplies", "expense"),
    "6200": ("Software subscriptions", "expense"),
    "6300": ("Travel", "expense"),
    "6400": ("Professional fees", "expense"),
}


def validate(entry: JournalEntry, chart: dict[str, tuple[str, str]] = CHART) -> list[str]:
    """Return a list of human-readable issues. An empty list means the entry is valid."""
    issues: list[str] = []

    try:
        date.fromisoformat(entry.date)
    except ValueError:
        issues.append(f"invalid date '{entry.date}' (expected YYYY-MM-DD)")

    if len(entry.lines) < 2:
        issues.append("entry needs at least two lines")

    total_debit = Decimal("0")
    total_credit = Decimal("0")
    for number, line in enumerate(entry.lines, start=1):
        if line.account not in chart:
            issues.append(f"line {number}: unknown account {line.account}")
        if line.debit < 0 or line.credit < 0:
            issues.append(f"line {number}: negative amount")
        if (line.debit > 0) == (line.credit > 0):
            issues.append(f"line {number}: must have exactly one of debit or credit")
        total_debit += line.debit
        total_credit += line.credit

    if total_debit != total_credit:
        issues.append(f"unbalanced: debits {total_debit} vs credits {total_credit}")
    if total_debit == 0:
        issues.append("amount must be greater than zero")

    return issues
