@echo off
cd /d "%~dp0.."
uv run uvicorn app.main:app --app-dir apps/api --host 127.0.0.1 --port 8000 --reload --reload-dir apps/api --no-access-log
