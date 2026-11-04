@echo off
rem Lanciato il 14 di ogni mese: mail con le autofatture del mese precedente.
cd /d "%~dp0.."
.venv\Scripts\python -m autofatture riepilogo --invia
