#!/usr/bin/env bash
# The one command to run before pushing. Mirrors CI exactly — if this is
# green locally, CI will be green. Run from anywhere; no arguments needed.
#
#   ./scripts/check.sh            # everything (backend + frontend)
#   ./scripts/check.sh backend    # backend only (ruff, mypy --strict, pytest)
#   ./scripts/check.sh frontend   # frontend only (svelte-check, vitest, build)
set -euo pipefail
cd "$(dirname "$0")/.."

want="${1:-all}"
case "$want" in
  all|backend|frontend) ;;
  *) echo "usage: $0 [all|backend|frontend]" >&2; exit 2 ;;
esac

fail() { echo "✗ $1 failed — fix before pushing." >&2; exit 1; }

if [ "$want" != "frontend" ]; then
  if ! command -v uv >/dev/null; then
    echo "uv not found. Install it: https://docs.astral.sh/uv/" >&2; exit 1
  fi
  echo "── backend: sync deps (dev extras) ────────────────────"
  uv sync --extra dev || fail "uv sync"
  echo "── backend: ruff ──────────────────────────────────────"
  uv run ruff check . || fail "ruff"
  echo "── backend: mypy --strict ─────────────────────────────"
  uv run mypy app/ --strict || fail "mypy"
  echo "── backend: pytest (unit + coverage) ──────────────────"
  uv run pytest -q --cov=app || fail "pytest"
fi

if [ "$want" != "backend" ]; then
  cd frontend
  if [ ! -d node_modules ]; then
    echo "frontend deps missing — running npm ci"
    npm ci
  fi
  echo "── frontend: svelte-check ─────────────────────────────"
  npm run check || fail "svelte-check"
  echo "── frontend: vitest ───────────────────────────────────"
  npm test || fail "vitest"
  echo "── frontend: vite build ───────────────────────────────"
  npm run build || fail "vite build"
  cd ..
fi

echo "✓ all checks green."
