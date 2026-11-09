@echo off
cd /d "%~dp0.."
where py >nul 2>nul
if not errorlevel 1 (py -3 scripts\preview.py) else (python scripts\preview.py)
pause
