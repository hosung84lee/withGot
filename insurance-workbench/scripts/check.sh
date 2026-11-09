#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
uv run ruff check apps/api
uv run pytest
npm --prefix apps/web run build
