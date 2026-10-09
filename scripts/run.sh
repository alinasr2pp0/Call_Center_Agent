#!/usr/bin/env bash
# Start Call Center Agent (Linux / macOS):  ./scripts/run.sh
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
. .venv/bin/activate
pip install -q -r backend/requirements.txt
[ -f .env ] || cp .env.example .env
cd backend
exec python run.py
