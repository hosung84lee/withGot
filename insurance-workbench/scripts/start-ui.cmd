@echo off
cd /d "%~dp0.."
where node >nul 2>nul
if errorlevel 1 (echo Install Node.js 24 LTS first. & pause & exit /b 1)
if not exist apps\web\node_modules (call npm --prefix apps/web ci & if errorlevel 1 exit /b 1)
call npm --prefix apps/web run dev -- --open
