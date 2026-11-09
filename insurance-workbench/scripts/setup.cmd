@echo off
cd /d "%~dp0.."
where uv >nul 2>nul
if errorlevel 1 (echo Install Python 3.12 and uv first. See LOCAL_SETUP.md. & pause & exit /b 1)
call uv sync --locked
if errorlevel 1 exit /b 1
call npm --prefix apps/web ci
if errorlevel 1 exit /b 1
echo Setup complete. Run start-ui.cmd for UI and start-api.cmd for API.
pause
