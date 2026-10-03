@echo off
REM Installa la routine TaxDome del mattino (ogni giorno alle 07:30).
REM Da lanciare UNA volta, con doppio clic normale (non "Esegui come
REM amministratore"), dal PC dello Studio con Outlook e TaxDome Drive.
REM Il lavoro lo fa installa_routine_taxdome.ps1, nella stessa cartella.

echo.
echo ============================================================
echo   INSTALLA ROUTINE TAXDOME DELLE 07:30
echo ============================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installa_routine_taxdome.ps1"

echo.
pause
