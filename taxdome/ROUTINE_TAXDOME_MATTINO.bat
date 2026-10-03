@echo off
setlocal EnableExtensions

REM ============================================================
REM  ROUTINE TAXDOME DEL MATTINO
REM  Lanciata ogni giorno alle 07:30 dall'Utilita' di pianificazione
REM  (attivita' creata da INSTALLA_ROUTINE_TAXDOME.bat).
REM
REM  Fa quello che fa 0_UTILIZZA_QUESTO.bat, ma senza conferme e
REM  senza "pause": tutto l'output finisce nel file
REM  LOG\taxdome_AAAA-MM-GG.log accanto a questo .bat.
REM
REM  Va tenuto in REGOLE CARICAMENTI, accanto agli altri lanciatori:
REM  usa gli script .py di quella cartella (o della sottocartella altro\).
REM ============================================================

REM --- Impostazioni -------------------------------------------
REM Dopo le mail, scansione diretta di T: per i caricamenti senza notifica:
REM   NO        = non la fa
REM   ANTEPRIMA = scrive nel log cosa farebbe, senza toccare nulla
REM   ESEGUI    = elabora davvero i file trovati
set "SCANSIONE_T=ANTEPRIMA"
set "DAL=10/09/2026"
set "ARCHIVIO=\\192.168.50.254\Pubblica\1.DENIS\STUDIO\ELENCO CLIENTI"
REM ------------------------------------------------------------

set PYTHONUNBUFFERED=1
REM Con l'output rediretto su file Python scriverebbe in cp1252 e andrebbe
REM in errore sul primo carattere fuori tabella: forziamo UTF-8.
set PYTHONIOENCODING=utf-8

set "QUI=%~dp0"
set "SCRIPT_DIR=%QUI%altro"
if not exist "%SCRIPT_DIR%\processa_outlook_automatico.py" set "SCRIPT_DIR=%QUI:~0,-1%"

REM Directory corrente = cartella del .bat (sul server pushd assegna una
REM lettera temporanea), altrimenti l'attivita' partirebbe da System32.
pushd "%QUI%" || exit /b 1

if not exist "%QUI%LOG" mkdir "%QUI%LOG"
for /f %%d in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set "OGGI=%%d"
set "LOG=%QUI%LOG\taxdome_%OGGI%.log"

echo Routine TaxDome in corso: non chiudere questa finestra.
echo Log: %LOG%

>> "%LOG%" echo.
>> "%LOG%" echo ============================================================
>> "%LOG%" echo [%date% %time%] AVVIO ROUTINE TAXDOME - utente %USERNAME%
>> "%LOG%" echo ============================================================

REM La chiave sta nelle variabili d'ambiente dell'utente (la imposta
REM INSTALLA_ROUTINE_TAXDOME.bat). Se l'Utilita' di pianificazione non
REM l'ha ancora vista, la rileggiamo direttamente dal registro.
if not defined ANTHROPIC_API_KEY for /f "tokens=2,*" %%a in ('reg query HKCU\Environment /v ANTHROPIC_API_KEY 2^>nul ^| find "REG_"') do set "ANTHROPIC_API_KEY=%%b"

REM Controlli prima di toccare qualunque cosa: se manca il server o T:
REM non si rinomina nulla e non si spostano mail.
set "ERRORE="
if not defined ANTHROPIC_API_KEY set "ERRORE=chiave ANTHROPIC_API_KEY non impostata - rilanciare INSTALLA_ROUTINE_TAXDOME.bat"
if not defined ERRORE if not exist "%SCRIPT_DIR%\processa_outlook_automatico.py" set "ERRORE=processa_outlook_automatico.py non trovato in %QUI% ne' in %QUI%altro"
if not defined ERRORE if not exist T:\ set "ERRORE=disco T: non raggiungibile - TaxDome Drive e' avviato?"
if not defined ERRORE if not exist "%ARCHIVIO%\" set "ERRORE=archivio dello Studio non raggiungibile: %ARCHIVIO%"
if not defined ERRORE where python >nul 2>&1 || set "ERRORE=python non trovato nel PATH dell'utente %USERNAME%"
if defined ERRORE goto :errore

>> "%LOG%" echo.
>> "%LOG%" echo [%date% %time%] 1/2 - Mail della cartella Outlook TAXDOME CARICAMENTI
python -u "%SCRIPT_DIR%\processa_outlook_automatico.py" < nul >> "%LOG%" 2>&1
set "ESITO=%ERRORLEVEL%"
>> "%LOG%" echo [%date% %time%] Fine mail - codice %ESITO%

if /i "%SCANSIONE_T%"=="NO" goto :fine
set "OPZIONI=--dal %DAL%"
if /i "%SCANSIONE_T%"=="ESEGUI" (set "OPZIONI=%OPZIONI% --esegui") else (set "SCANSIONE_T=ANTEPRIMA")

>> "%LOG%" echo.
>> "%LOG%" echo [%date% %time%] 2/2 - Scansione diretta di T: in modalita' %SCANSIONE_T%
python -u "%SCRIPT_DIR%\processa_cartelle_taxdome.py" %OPZIONI% < nul >> "%LOG%" 2>&1
set "ESITO_T=%ERRORLEVEL%"
>> "%LOG%" echo [%date% %time%] Fine scansione - codice %ESITO_T%
if "%ESITO%"=="0" set "ESITO=%ESITO_T%"
goto :fine

:errore
>> "%LOG%" echo [%date% %time%] ERRORE: %ERRORE%
>> "%LOG%" echo Routine NON eseguita: nessun file e nessuna mail toccati.
echo ERRORE: %ERRORE%
set "ESITO=1"

:fine
>> "%LOG%" echo [%date% %time%] FINE ROUTINE - codice %ESITO%
REM Tiene i log degli ultimi 90 giorni.
powershell -NoProfile -Command "Get-ChildItem -LiteralPath '%QUI%LOG' -Filter 'taxdome_*.log' | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-90) } | Remove-Item -Force" >nul 2>&1
popd
exit /b %ESITO%
