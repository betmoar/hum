#!/usr/bin/env bash
# One-command setup: secrets + backend deps + frontend deps.
#
#   ./scripts/setup.sh                 # secrets + uv sync + npm ci
#   ./scripts/setup.sh --secrets-only  # just write .env (the Docker path)
#   ./scripts/setup.sh --dev           # setup, then start dev servers
#   ./scripts/setup.sh --prod          # setup, build frontend, run server
#
# Idempotent: only BLANK `KEY=` values in .env are filled; existing values are
# never touched; a second run is a no-op. Secrets are filled IN PLACE (never
# appended) because .env.example already ships blank `KEY=` lines — appending
# would create duplicate keys whose winner depends on dotenv parse order.
set -euo pipefail
cd "$(dirname "$0")/.."

mode="${1:-}"
case "$mode" in
  ""|--secrets-only|--dev|--prod) ;;
  *) echo "usage: $0 [--secrets-only|--dev|--prod]" >&2; exit 2 ;;
esac

command -v python3 >/dev/null || { echo "python3 not found on PATH" >&2; exit 1; }

# --- secrets ---------------------------------------------------------------
if [ ! -f .env ]; then
  cp .env.example .env
  echo "created .env from .env.example"
fi

fill_blank_key() {
  # fill_blank_key KEY VALUE — replace a blank `KEY=` line with `KEY=VALUE`.
  # Non-blank values are left untouched. mktemp+mv instead of sed -i for
  # BSD/GNU portability.
  local key="$1" value="$2" tmp
  if grep -q "^${key}=$" .env; then
    tmp="$(mktemp)"
    sed "s|^${key}=\$|${key}=${value}|" .env > "$tmp"
    mv "$tmp" .env
    echo "generated ${key}"
  elif ! grep -q "^${key}=" .env; then
    printf '%s=%s\n' "$key" "$value" >> .env
    echo "generated ${key} (key was absent — appended)"
  fi
}

fill_blank_key API_BEARER_TOKEN "$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
fill_blank_key STREAM_SIGNING_KEY "$(python3 -c 'import secrets; print(secrets.token_hex(32))')"

if [ "$mode" = "--secrets-only" ]; then
  echo ".env ready."
  exit 0
fi

# --- deps ------------------------------------------------------------------
command -v uv >/dev/null || { echo "uv not found. Install it: https://docs.astral.sh/uv/" >&2; exit 1; }
uv sync --extra dev
npm --prefix frontend ci

case "$mode" in
  --dev)  exec ./scripts/dev.sh ;;
  --prod) ./scripts/build.sh && exec uv run hum ;;
  *)      echo "setup complete — next: ./scripts/dev.sh (dev) or ./scripts/setup.sh --prod" ;;
esac
