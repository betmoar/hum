#!/usr/bin/env bash
# The one command to run before pushing. Mirrors CI exactly — if this is
# green locally, CI will be green. Run from anywhere; no arguments needed.
#
#   ./scripts/check.sh            # everything (backend + frontend)
#   ./scripts/check.sh backend    # backend only (ruff, mypy --strict, pytest)
#   ./scripts/check.sh frontend   # frontend only (svelte-check, vitest, build)
#   ./scripts/check.sh fast       # inner loop: ruff+mypy+pytest(no cov)+vitest — NOT a pre-push substitute
set -euo pipefail
cd "$(dirname "$0")/.."

want="${1:-all}"
case "$want" in
  all|backend|frontend|fast) ;;
  *) echo "usage: $0 [all|backend|frontend|fast]" >&2; exit 2 ;;
esac

fail() { echo "✗ $1 failed — fix before pushing." >&2; exit 1; }

if [ "$want" = "fast" ]; then
  # Inner-loop mode: assumes a previously-synced .venv. If one is missing,
  # `uv run --no-sync` does NOT error — it creates an EMPTY venv and every
  # check below then fails with confusing import errors, so we check first.
  # --no-sync is load-bearing: plain `uv run` re-syncs on a stale lockfile,
  # defeating the fast path.
  if [ ! -x .venv/bin/python ]; then
    echo "no synced .venv — run ./scripts/setup.sh first" >&2; exit 1
  fi
  echo "── fast: ruff ─────────────────────────────────────────"
  uv run --no-sync ruff check . || fail "ruff"
  echo "── fast: mypy --strict ────────────────────────────────"
  uv run --no-sync mypy app/ --strict || fail "mypy"
  echo "── fast: pytest (no coverage) ─────────────────────────"
  uv run --no-sync pytest -q || fail "pytest"
  echo "── fast: vitest ───────────────────────────────────────"
  npm --prefix frontend test || fail "vitest"
  echo "✓ fast checks green — run ./scripts/check.sh before pushing."
  exit 0
fi

if [ "$want" != "frontend" ]; then
  if ! command -v uv >/dev/null; then
    echo "uv not found. Install it: https://docs.astral.sh/uv/" >&2; exit 1
  fi
  stamp=".venv/.sync-stamp"
  # Quoted so a missing uv.lock/pyproject.toml can't make `-nt` quietly report
  # "unchanged" and skip a sync that was actually needed.
  if [ ! -f "$stamp" ] || [ "uv.lock" -nt "$stamp" ] || [ "pyproject.toml" -nt "$stamp" ]; then
    echo "── backend: sync deps (dev extras) ────────────────────"
    uv sync --extra dev || fail "uv sync"
    touch "$stamp"
  else
    echo "── backend: deps unchanged — skipping uv sync ─────────"
  fi
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
