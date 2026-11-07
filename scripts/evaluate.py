"""Run the synthetic dataset through the proposer and validator and print a report.

Usage: python scripts/evaluate.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.ledger import validate  # noqa: E402
from app.proposer import ExtractionError, propose_entry  # noqa: E402


def outcome(text: str) -> tuple[str, str]:
    try:
        entry = propose_entry(text)
    except ExtractionError as exc:
        return "error", str(exc)
    issues = validate(entry)
    if issues:
        return "needs_review", "; ".join(issues)
    total = entry.lines[0].debit
    return "pending", f"{entry.lines[0].account} / {entry.lines[1].account} = {total}"


def main() -> int:
    samples = json.loads((ROOT / "data" / "synthetic_documents.json").read_text())
    correct = 0
    print(f"{'id':8} {'expected':13} {'actual':13} {'result':6} detail")
    for sample in samples:
        actual, detail = outcome(sample["text"])
        ok = actual == sample["expect"]
        correct += ok
        print(f"{sample['id']:8} {sample['expect']:13} {actual:13} {'PASS' if ok else 'FAIL':6} {detail}")
    print(f"\nAccuracy: {correct}/{len(samples)} = {correct / len(samples):.0%}")
    return 0 if correct == len(samples) else 1


if __name__ == "__main__":
    raise SystemExit(main())
