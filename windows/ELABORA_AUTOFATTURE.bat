@echo off
rem Lanciato ogni 15 minuti dall'Utilita' di pianificazione.
cd /d "%~dp0.."
.venv\Scripts\python -m autofatture elabora
