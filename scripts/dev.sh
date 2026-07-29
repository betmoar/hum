#!/usr/bin/env bash
# Run frontend vite dev server + backend uvicorn in parallel.
set -e
trap 'kill 0' EXIT
cd "$(dirname "$0")/.."

if [ ! -d frontend/node_modules ]; then
  echo "frontend deps missing — running npm install"
  (cd frontend && npm install)
fi

if [ ! -d .venv ]; then
  echo "no .venv found — run ./scripts/setup.sh first"
  exit 1
fi

# shellcheck disable=SC1091
source .venv/bin/activate

(cd frontend && npm run dev) &
uvicorn app.main:app --reload --reload-dir app --host 127.0.0.1 --port 8000 &
wait
