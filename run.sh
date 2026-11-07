#!/usr/bin/env bash
# Starts the Journal Entry Agent.
#  - Creates .venv and installs requirements on first run (needs Python 3.10+).
#  - Loads Azure OpenAI settings from .env if present.
#  - Without Azure settings, the rule-based proposer is used.
set -euo pipefail

cd "$(dirname "$0")"

PYTHON="${PYTHON:-}"
if [ -z "$PYTHON" ]; then
  for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1 &&
       "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
      PYTHON="$candidate"
      break
    fi
  done
fi
if [ -z "$PYTHON" ]; then
  echo "Python 3.10+ is required. Install it, or set PYTHON=/path/to/python3.x and retry." >&2
  exit 1
fi
echo "Using $("$PYTHON" --version) at $(command -v "$PYTHON")"

if [ ! -d .venv ]; then
  "$PYTHON" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -r requirements.txt

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

if [ -n "${OPENAI_API_KEY:-}" ]; then
  echo "Proposer: OpenAI (model: ${OPENAI_MODEL:-gpt-6-luna})"
elif [ -n "${AZURE_OPENAI_API_KEY:-}" ]; then
  echo "Proposer: Azure OpenAI (deployment: ${AZURE_OPENAI_DEPLOYMENT:-?})"
else
  echo "Proposer: rule-based (no OPENAI_API_KEY or Azure key in .env)"
fi

exec uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
