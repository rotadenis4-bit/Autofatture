@echo off
rem Salva Entratel, Todoist e posta nel Gestore credenziali di Windows.
cd /d "%~dp0.."
.venv\Scripts\python -m autofatture imposta-credenziali
if not "%~1"=="nopausa" pause
