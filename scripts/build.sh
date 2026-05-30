#!/usr/bin/env bash
# Build the frontend so FastAPI can serve it from frontend/dist.
set -e
cd "$(dirname "$0")/.."

cd frontend
if [ ! -d node_modules ]; then
  npm ci
fi
npm run build
echo "Built frontend/dist."
