# Journal Entry Agent

A finance workflow where an AI proposal is only as good as the checks it has to pass.

Source document → proposed journal entry → deterministic validation → human approval.

## What it demonstrates

- **Hard controls over AI output.** Every proposal, whatever produced it, goes through `app/ledger.py`. Entries must balance, use known accounts, carry valid dates, and have positive amounts. Entries that fail are marked `needs_review` and cannot be approved.
- **Knowing when not to use AI.** Amount arithmetic and validation are plain code with `Decimal`, never a model.
- **Human approval.** Nothing is approved without a person clicking Approve.
- **Two proposers, one validator.** A rule-based proposer works offline. An LLM proposer (OpenAI by default, Azure optional) is used when its key is set. Both feed the same checks.

## Requirements

- Python 3.10 or newer (the code uses `X | None` type hints). macOS ships Python 3.9, which will not work.
- An OpenAI API key only if you want the LLM proposer. The app runs without one.

## Quick start

```bash
./run.sh
```

Then open http://127.0.0.1:8000.

`run.sh` finds a Python 3.10+ interpreter, creates `.venv`, installs `requirements.txt`, loads `.env` if it exists, and starts the server with auto-reload. To pick a specific interpreter, run `PYTHON=/path/to/python3.13 ./run.sh`.

Click a synthetic sample (SYN-001 to SYN-011), then **Propose entry**.

## Use an LLM (OpenAI, recommended)

The app can use an LLM to read the source document. It is optional. Without a key, the rule-based proposer is used.

1. Create a key at https://platform.openai.com/api-keys (requires a funded OpenAI API account).
2. Copy the template and paste the key:

   ```bash
   cp .env.example .env
   ```

   In `.env`, set `OPENAI_API_KEY=<your key>`. Leave `OPENAI_MODEL=gpt-6-luna` as is.
3. Restart the server (`Ctrl+C`, then `./run.sh`).

`.env` is git-ignored, so the key stays out of the repo. Do not paste the key into any file that is committed. Check which proposer is active at http://127.0.0.1:8000/api/config (returns `rules`, `openai:gpt-6-luna`, or `azure-openai:<deployment>`). The key is never returned by the API.

### Groq (free-tier option, used in this repo's live tests)

Groq serves an OpenAI-compatible API. Set `GROQ_API_KEY` in `.env` (create one at https://console.groq.com/keys). `GROQ_MODEL` defaults to `openai/gpt-oss-20b`, the lowest-cost usable text model on Groq's model list at the time of writing ($0.075 input and $0.30 output per 1M tokens). `llama-3.1-8b-instant` is not on the current list, so do not use it.

Priority: OpenAI if `OPENAI_API_KEY` is set, then Groq if `GROQ_API_KEY` is set, then Azure OpenAI if its three variables are set, then rules.

Live results with Groq (`openai/gpt-oss-20b`) on this repo's 19 test documents (11 synthetic plus 8 new): 14 of 19 matched the expected outcome. The misses were model answers, not check failures: the model returned an error instead of a draft for an unmapped category (SYN-006, NEW-05) and for invalid dates (SYN-009, NEW-06), and it said there was no account for `consulting` (NEW-04). In one case (SYN-007) the model invented an amount of 50.00 that is not in the document, and the guardrail flagged it. Those results are from one run, so expect some variation.

### What the LLM does

The LLM only reads the document and fills in a draft entry. It does not decide anything else:

1. It receives the source document text and a system prompt listing the chart of accounts and the debit/credit rules.
2. It returns JSON: date, vendor, description, source reference, amount, debit account, credit account.
3. The app checks the answer before it is shown:
   - The amount must appear in the source document, or the entry is flagged.
   - `ledger.validate` runs on the result, exactly as for the rule-based proposer.
4. Amounts are handled as `Decimal` in code, never by the model. An entry the model gets wrong is marked `needs_review` and cannot be approved. A person still clicks Approve.

Each entry records its proposer in `proposed_by`: `rules`, `openai:<model>`, `groq:<model>`, or `azure-openai:<deployment>`.

### Model and cost

`gpt-6-luna` is the default. It is the lowest-cost current text model on OpenAI's pricing page at the time of writing: $0.10 per 1M input tokens and $0.50 per 1M output tokens (standard tier). One invoice is roughly 200 input tokens and 150 output tokens, so a single proposal costs a small fraction of a cent. Check https://developers.openai.com/api/docs/pricing before relying on these numbers, since prices change.

- Reasoning is turned off (`reasoning_effort: none`) so hidden reasoning tokens are not billed.
- JSON output mode is requested. The model page lists structured outputs, but this app has not yet been run against the live API, so confirm the first proposal works.
- To try another model, set `OPENAI_MODEL` in `.env`.

### Azure OpenAI (optional)

Set `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY` and `AZURE_OPENAI_DEPLOYMENT` in `.env` (values from the Azure portal, **Resource → Keys and Endpoint**). Use this only if you need Azure. OpenAI takes priority when both are set. `AZURE_OPENAI_API_VERSION` is optional; the default is `2024-10-21`.

## Test it

```bash
source .venv/bin/activate
python -m pytest -q          # 51 tests: ledger rules, rule and LLM proposers, API, every synthetic sample
python scripts/evaluate.py   # PASS/FAIL table and accuracy over the synthetic set (rule-based)
```

The tests use a mock HTTP transport for OpenAI and Azure, so they never call the real services and need no key.

## Using the API directly

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/config` | Active proposer (never returns secrets) |
| GET | `/api/accounts` | Chart of accounts |
| GET | `/api/samples` | Synthetic source documents |
| POST | `/api/propose` | Body `{"document": "..."}`; returns a proposed entry (201) |
| GET | `/api/entries` | All entries in this session |
| POST | `/api/entries/{id}/approve` | Approve a `pending` entry with no issues |
| POST | `/api/entries/{id}/reject` | Reject a `pending` or `needs_review` entry |

Interactive docs are at http://127.0.0.1:8000/docs.

## Source document format

The rule-based proposer reads `Field: value` lines. Required: `Date`, `Total`, `Description`. Optional: `Vendor`, `Category`, `Status`, `Type`, `Invoice`.

```
Invoice: INV-2041
Type: purchase
Date: 2026-10-03
Vendor: Northwind Cloud
Category: software
Total: 480.00
Status: unpaid
Description: Monthly hosting for n8n workflows
```

- `Type: sales` books Dr 1200 Accounts receivable / Cr 4000 Service revenue.
- Purchases use the category to pick the expense account (office → 6100, software → 6200, travel → 6300, legal or consulting → 6400). `Status: paid` credits Cash (1000); otherwise Accounts payable (2000).

## Chart of accounts

| Code | Name | Type |
|---|---|---|
| 1000 | Cash | asset |
| 1200 | Accounts receivable | asset |
| 2000 | Accounts payable | liability |
| 4000 | Service revenue | revenue |
| 6100 | Office supplies | expense |
| 6200 | Software subscriptions | expense |
| 6300 | Travel | expense |
| 6400 | Professional fees | expense |

## Synthetic dataset

`data/synthetic_documents.json` has 11 documents, all invented:

| Cases | Expected outcome |
|---|---|
| SYN-001 to 005: valid purchases (software, office, travel, legal) and a sales invoice | pending |
| SYN-006 to 009: unmapped category, negative total, zero total, invalid date | needs_review |
| SYN-010 to 011: missing total, unreadable amount | error (extraction fails) |

## Structure

```
app/
  models.py         Line and JournalEntry (Decimal amounts)
  ledger.py         chart of accounts and validation rules
  proposer.py       rule-based document → proposed entry
  llm_proposer.py   LLM document → proposed entry: OpenAI (default) and Azure, guarded by ledger.validate
  store.py          in-memory entry store
  main.py           FastAPI routes
static/index.html   frontend (vanilla JS, no build step)
data/               synthetic documents
tests/              pytest suite
scripts/evaluate.py accuracy report for the rule-based proposer
run.sh              setup + start script
.env.example        template for OpenAI and Azure settings (copy to .env)
```

## Troubleshooting

- **`Python 3.10+ is required`**: install Python 3.10+ (for example from python.org or Homebrew), or run `PYTHON=/path/to/python3.x ./run.sh`.
- **`/api/config` says `rules` after adding the key**: `.env` is read only at startup. Restart the server. Check that all three values are filled in.
- **HTTP 502 on propose**: the LLM provider rejected the call or could not be reached. The error message gives the HTTP status code. For OpenAI, `401` means a bad key and `429` means the account has no credit or hit a rate limit. For Azure, check the endpoint, key, deployment name and API version.
- **Entry flagged "amount does not appear in the source document"**: the model changed or invented the amount. The entry is marked `needs_review` and cannot be approved.

## Next steps

1. **Real persistence.** Replace the in-memory store with PostgreSQL and add an audit trail (who approved, when).
2. **Period controls.** Block entries dated in closed periods.
3. **Evaluation on messier data.** Real invoices are PDFs with OCR errors. Measure proposal accuracy against labelled examples, including the Azure proposer, not only the synthetic set.

## Note

All sample data is synthetic. Vendors, invoice numbers and amounts are invented.
