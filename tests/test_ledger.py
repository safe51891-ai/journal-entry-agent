from decimal import Decimal

from app.ledger import validate
from app.models import JournalEntry, Line


def make(*lines: Line, date: str = "2026-10-03") -> JournalEntry:
    return JournalEntry(date=date, description="test", lines=list(lines))


def test_balanced_entry_with_known_accounts_passes():
    entry = make(
        Line(account="6200", debit=Decimal("480.00")),
        Line(account="2000", credit=Decimal("480.00")),
    )
    assert validate(entry) == []


def test_unbalanced_entry_is_flagged():
    entry = make(
        Line(account="6200", debit=Decimal("480.00")),
        Line(account="2000", credit=Decimal("400.00")),
    )
    assert any("unbalanced" in issue for issue in validate(entry))


def test_unknown_account_is_flagged():
    entry = make(
        Line(account="6999", debit=Decimal("10.00")),
        Line(account="2000", credit=Decimal("10.00")),
    )
    assert any("unknown account 6999" in issue for issue in validate(entry))


def test_negative_amount_is_flagged():
    entry = make(
        Line(account="6200", debit=Decimal("-50.00")),
        Line(account="2000", credit=Decimal("-50.00")),
    )
    assert any("negative amount" in issue for issue in validate(entry))


def test_zero_total_is_flagged():
    entry = make(
        Line(account="6200", debit=Decimal("0.00")),
        Line(account="2000", credit=Decimal("0.00")),
    )
    assert any("greater than zero" in issue for issue in validate(entry))


def test_line_with_both_sides_is_flagged():
    entry = make(
        Line(account="6200", debit=Decimal("10.00"), credit=Decimal("10.00")),
        Line(account="2000", credit=Decimal("0.00")),
    )
    assert any("exactly one of debit or credit" in issue for issue in validate(entry))


def test_invalid_date_is_flagged():
    entry = make(
        Line(account="6200", debit=Decimal("10.00")),
        Line(account="2000", credit=Decimal("10.00")),
        date="2026-13-40",
    )
    assert any("invalid date" in issue for issue in validate(entry))


def test_single_line_entry_is_flagged():
    entry = make(Line(account="6200", debit=Decimal("10.00")))
    assert any("at least two lines" in issue for issue in validate(entry))
