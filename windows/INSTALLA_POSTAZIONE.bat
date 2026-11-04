@echo off
rem Da lanciare una volta su ogni PC dei collaboratori che usano /autofattura.
setlocal
cd /d "%~dp0.."
echo Installazione programma autofatture in %CD%
py -3 -m venv .venv || goto :errore
.venv\Scripts\python -m pip install -q -r requirements.txt || goto :errore
setx AUTOFATTURE_CONFIG "\\192.168.50.254\Pubblica\AUTOFATTURE\config.yaml" >nul
.venv\Scripts\python -m autofatture clienti || goto :errore
echo.
echo Fatto. Chiudere e riaprire Claude Code in questa cartella, poi usare /autofattura.
pause
exit /b 0
:errore
echo ERRORE durante l'installazione.
pause
exit /b 1
