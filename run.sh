#!/usr/bin/env bash
# Boot J.A.R.V.I.S.
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi
[ -f .env ] || { cp .env.example .env; echo "Created .env - put your ANTHROPIC_API_KEY in it, then run ./run.sh again."; exit 1; }
exec .venv/bin/python -m jarvis.server
