# Registra la routine TaxDome del mattino nell'Utilita' di pianificazione di Windows.
# Si lancia con INSTALLA_ROUTINE_TAXDOME.bat, una volta sola, dal PC dello Studio
# dove girano Outlook e TaxDome Drive, con l'utente che usa quel PC.
# Rilanciarlo e' sicuro: sovrascrive l'attivita' con lo stesso nome.

param(
    [switch]$Elevato,   # uso interno: seconda fase, gia' come amministratore
    [string]$Utente     # uso interno: utente a cui intestare l'attivita'
)

# --- Impostazioni -------------------------------------------------------
$NomeAttivita = 'TaxDome - archiviazione caricamenti'
$Ora = '07:30'
# PROCESSO.md: l'errore 0x800710E0 si risolve con "Esegui con i privilegi piu' elevati".
$PrivilegiElevati = $true
# ------------------------------------------------------------------------

$ErrorActionPreference = 'Stop'
$Lanciatore = Join-Path $PSScriptRoot 'ROUTINE_TAXDOME_MATTINO.bat'

function Registra([string]$utente) {
    $azione = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument "/c `"`"$Lanciatore`"`""
    $quando = New-ScheduledTaskTrigger -Daily -At $Ora
    $livello = if ($PrivilegiElevati) { 'Highest' } else { 'Limited' }
    # Interactive = gira solo con l'utente connesso (va bene anche a schermo
    # bloccato): serve per Outlook via COM e per il disco T: di TaxDome Drive.
    $chi = New-ScheduledTaskPrincipal -UserId $utente -LogonType Interactive -RunLevel $livello
    # StartWhenAvailable: se alle 07:30 il PC era spento, parte appena possibile.
    $opzioni = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 6)
    Register-ScheduledTask -TaskName $NomeAttivita -Action $azione -Trigger $quando `
        -Principal $chi -Settings $opzioni -Force `
        -Description "Ogni mattina alle $Ora archivia i documenti caricati dai clienti su TaxDome. Log in $PSScriptRoot\LOG" | Out-Null

    $prossima = (Get-ScheduledTask -TaskName $NomeAttivita | Get-ScheduledTaskInfo).NextRunTime
    Write-Host ''
    Write-Host "OK - attivita' '$NomeAttivita' registrata per $utente." -ForegroundColor Green
    Write-Host "Prossima esecuzione: $prossima"

    # Una seconda attivita' sulla stessa routine elaborerebbe le mail due volte.
    $doppie = Get-ScheduledTask -ErrorAction SilentlyContinue | Where-Object {
        $_.TaskName -ne $NomeAttivita -and
        ($_.Actions | Where-Object { "$($_.Execute) $($_.Arguments)" -match 'LANCIA_TAXDOME|processa_outlook_automatico|ROUTINE_TAXDOME' })
    }
    foreach ($d in $doppie) {
        Write-Host ''
        Write-Host "ATTENZIONE: anche l'attivita' '$($d.TaskPath)$($d.TaskName)' lancia la routine TaxDome." -ForegroundColor Yellow
        Write-Host "Disattivala dall'Utilita' di pianificazione per non avere due esecuzioni." -ForegroundColor Yellow
    }

    Write-Host ''
    $prova = Read-Host "Vuoi lanciarla subito per prova? Elabora davvero le mail in attesa (SI/NO)"
    if ($prova -eq 'SI') {
        Start-ScheduledTask -TaskName $NomeAttivita
        Write-Host "Avviata. Il log del giorno e' in $PSScriptRoot\LOG"
    }
}

try {
    if ($Elevato) {
        Registra $Utente
    } else {
        if (-not (Test-Path -LiteralPath $Lanciatore)) {
            throw "Non trovo $Lanciatore - ROUTINE_TAXDOME_MATTINO.bat deve stare nella stessa cartella di questo script."
        }

        # 1) Chiave Anthropic come variabile d'ambiente dell'utente, cosi' non
        #    deve stare scritta in chiaro nei .bat.
        if ([Environment]::GetEnvironmentVariable('ANTHROPIC_API_KEY', 'User')) {
            Write-Host "Chiave Anthropic gia' impostata per l'utente $env:USERNAME."
        } else {
            $chiave = (Read-Host 'Incolla la chiave Anthropic (sk-ant-...) e premi Invio').Trim()
            if (-not $chiave.StartsWith('sk-ant-')) { throw 'La chiave deve iniziare con sk-ant-' }
            [Environment]::SetEnvironmentVariable('ANTHROPIC_API_KEY', $chiave, 'User')
            Write-Host "Chiave salvata nelle variabili d'ambiente dell'utente $env:USERNAME."
        }

        # 2) Attivita' pianificata. Con i privilegi elevati Windows chiede ora
        #    l'amministratore, ma l'attivita' resta intestata all'utente corrente.
        $utente = [Security.Principal.WindowsIdentity]::GetCurrent().Name
        if ($PrivilegiElevati) {
            Write-Host 'Registrazione attivita'': conferma la richiesta di Windows...'
            $argomenti = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Elevato -Utente `"$utente`""
            Start-Process powershell.exe -Verb RunAs -Wait -ArgumentList $argomenti
        } else {
            Registra $utente
        }
    }
} catch {
    Write-Host ''
    Write-Host "ERRORE: $($_.Exception.Message)" -ForegroundColor Red
}

# La finestra amministratore si chiuderebbe subito: lasciamo leggere l'esito.
if ($Elevato) { Read-Host 'Premi Invio per chiudere' | Out-Null }
