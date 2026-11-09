#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
uv run uvicorn app.main:app --app-dir apps/api --host 127.0.0.1 --port 8000 --reload --reload-dir apps/api --no-access-log &
api_pid=$!
trap 'kill "$api_pid" 2>/dev/null || true' EXIT INT TERM
npm --prefix apps/web run dev
