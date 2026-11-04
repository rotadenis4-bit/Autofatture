@echo off
rem Da lanciare una volta sul server, con l'utente che terra' le credenziali
rem (doppio clic normale, non "Esegui come amministratore").
setlocal
cd /d "%~dp0.."
py -3 -m venv .venv || goto :errore
.venv\Scripts\python -m pip install -q -r requirements-server.txt || goto :errore
.venv\Scripts\python -m playwright install chromium || goto :errore
setx AUTOFATTURE_CONFIG "\\192.168.50.254\Pubblica\AUTOFATTURE\config.yaml" >nul
set AUTOFATTURE_CONFIG=\\192.168.50.254\Pubblica\AUTOFATTURE\config.yaml
.venv\Scripts\python -m autofatture clienti || goto :errore

echo.
echo Credenziali (i caratteri non vengono mostrati):
call "%~dp0IMPOSTA_CREDENZIALI.bat" nopausa

schtasks /Create /TN "Autofatture\Elabora coda" /TR "\"%~dp0ELABORA_AUTOFATTURE.bat\"" /SC MINUTE /MO 15 /F || goto :errore
schtasks /Create /TN "Autofatture\Riepilogo del 14" /TR "\"%~dp0RIEPILOGO_AUTOFATTURE.bat\"" /SC MONTHLY /D 14 /ST 08:00 /F || goto :errore
echo.
echo Fatto: coda ogni 15 minuti, riepilogo il 14 di ogni mese alle 08:00.
pause
exit /b 0
:errore
echo ERRORE durante l'installazione.
pause
exit /b 1
