import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.ledger import validate
from app.proposer import ExtractionError, propose_entry

SAMPLES = json.loads((Path(__file__).resolve().parent.parent / "data" / "synthetic_documents.json").read_text())


def test_unpaid_software_invoice_credits_payable():
    entry = propose_entry(
        "Invoice: INV-1\nDate: 2026-10-03\nVendor: Acme\nCategory: software\n"
        "Total: 480.00\nStatus: unpaid\nDescription: Hosting"
    )
    assert entry.lines[0].account == "6200"
    assert entry.lines[0].debit == Decimal("480.00")
    assert entry.lines[1].account == "2000"
    assert entry.lines[1].credit == Decimal("480.00")
    assert entry.source_ref == "INV-1"


def test_paid_invoice_credits_cash():
    entry = propose_entry(
        "Date: 2026-10-05\nCategory: office\nTotal: 132.50\nStatus: paid\nDescription: Paper"
    )
    assert entry.lines[1].account == "1000"


def test_sales_invoice_debits_receivable_and_credits_revenue():
    entry = propose_entry(
        "Type: sales\nDate: 2026-10-15\nTotal: 9000.00\nStatus: unpaid\nDescription: Service"
    )
    assert [line.account for line in entry.lines] == ["1200", "4000"]


def test_thousands_separator_is_parsed():
    entry = propose_entry("Date: 2026-10-09\nCategory: travel\nTotal: 1,875.20\nDescription: Flights")
    assert entry.lines[0].debit == Decimal("1875.20")


def test_missing_total_raises():
    with pytest.raises(ExtractionError, match="missing field: total"):
        propose_entry("Date: 2026-10-22\nCategory: software\nDescription: No total")


def test_unreadable_amount_raises():
    with pytest.raises(ExtractionError, match="cannot read amount"):
        propose_entry("Date: 2026-10-23\nTotal: twelve dollars\nDescription: OCR failure")


@pytest.mark.parametrize("sample", SAMPLES, ids=[s["id"] for s in SAMPLES])
def test_synthetic_samples_meet_expectation(sample):
    """Each synthetic document must end in its expected outcome after validation."""
    if sample["expect"] == "error":
        with pytest.raises(ExtractionError):
            propose_entry(sample["text"])
        return
    entry = propose_entry(sample["text"])
    status = "needs_review" if validate(entry) else "pending"
    assert status == sample["expect"]
