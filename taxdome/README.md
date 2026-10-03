# Routine TaxDome delle 07:30

Ogni mattina alle 07:30 il PC dello Studio archivia da solo i documenti caricati
dai clienti su TaxDome: è la stessa routine di `0_UTILIZZA_QUESTO.bat`, ma senza
domande e con un log giornaliero.

La pianificazione la fa l'**Utilità di pianificazione di Windows** sul PC, non il
cloud: la routine ha bisogno di Outlook aperto, del disco `T:` di TaxDome Drive e
del server `192.168.50.254`, raggiungibili solo dalla rete dello Studio.

## File

| File | A cosa serve |
|---|---|
| `ROUTINE_TAXDOME_MATTINO.bat` | La routine vera e propria, lanciata alle 07:30. Scrive tutto in `LOG\taxdome_AAAA-MM-GG.log`. |
| `INSTALLA_ROUTINE_TAXDOME.bat` | Da lanciare **una volta**: salva la chiave Anthropic e crea l'attività delle 07:30. |
| `installa_routine_taxdome.ps1` | Usato da `INSTALLA_ROUTINE_TAXDOME.bat`, non va aperto. |

## Installazione (una volta sola)

1. Copiare i file in `\\192.168.50.254\Pubblica\1.DENIS\STUDIO\REGOLE CARICAMENTI\`,
   accanto agli altri lanciatori: la routine usa gli stessi `.py` (in quella
   cartella o nella sottocartella `altro\`).
2. Dal PC con Outlook e TaxDome Drive, **doppio clic normale** su
   `INSTALLA_ROUTINE_TAXDOME.bat` (non "Esegui come amministratore", altrimenti
   chiave e attività finiscono intestate all'amministratore).
3. Solo la prima volta: incollare la chiave Anthropic quando richiesta.
4. Confermare la richiesta di Windows (serve per "Esegui con i privilegi più
   elevati", come indicato in `PROCESSO.md`).
5. Rispondere `SI` alla prova e controllare il log in `REGOLE CARICAMENTI\LOG\`.

Se i file sono stati scaricati da GitHub, Windows può bloccarli: tasto destro →
Proprietà → **Sblocca**.

Se esiste già un'attività che lancia `LANCIA_TAXDOME.bat`, l'installazione lo
segnala: va disattivata, altrimenti la routine gira due volte.

## Quando parte

- Ogni giorno alle 07:30, con il PC acceso e l'utente connesso (va bene anche a
  schermo bloccato) e TaxDome Drive attivo su `T:`.
- Se il PC è in sospensione lo risveglia; se è spento, la routine parte appena si
  accede.

## Cosa fa

Prima controlla chiave, disco `T:` e archivio sul server: se manca qualcosa non
tocca né file né mail e scrive `ERRORE` nel log.

1. **Mail** della cartella Outlook `TAXDOME CARICAMENTI` → `processa_outlook_automatico.py`.
2. **Scansione diretta di `T:`** (impostazione `SCANSIONE_T` in testa al `.bat`):
   - `ANTEPRIMA` (predefinita): elenca nel log i file che la via mail ha lasciato
     indietro, senza toccarli. Per elaborarli si lancia a mano
     `PROCESSA_CARTELLE_TAXDOME.bat`. È la scelta prudente indicata da
     `PROCESSO.md`, perché il filtro sui documenti dello Studio è euristico.
   - `ESEGUI`: li elabora anche, senza conferma.
   - `NO`: salta la scansione.

## Modifiche

- **Orario**: cambiare `$Ora` in `installa_routine_taxdome.ps1` e rilanciare
  l'installazione (oppure Utilità di pianificazione → attività → scheda Attivazione).
- **Scansione e data `--dal`**: impostazioni in testa a `ROUTINE_TAXDOME_MATTINO.bat`.
- **Disinstallare**: `schtasks /Delete /TN "TaxDome - archiviazione caricamenti" /F`

## Se qualcosa non va

| Sintomo | Causa e rimedio |
|---|---|
| Log: `disco T: non raggiungibile`, ma in Esplora risorse `T:` c'è | Le attività con privilegi elevati possono non vedere i dischi collegati dall'utente. In `installa_routine_taxdome.ps1` impostare `$PrivilegiElevati = $false` e rilanciare l'installazione. |
| Log: errore Outlook `0x80080005` / "Esecuzione server non riuscita" | Outlook aperto normalmente non accetta script lanciati come amministratore: stesso rimedio della riga sopra. |
| Log: `chiave ANTHROPIC_API_KEY non impostata` | Rilanciare `INSTALLA_ROUTINE_TAXDOME.bat` con l'utente del PC. |
| Nessun log del giorno | PC spento o utente disconnesso, oppure server non raggiungibile: Utilità di pianificazione → attività → scheda Cronologia. |
| Utilità di pianificazione: `0x800710E0` | Deve restare attiva "Esegui con i privilegi più elevati" (`PROCESSO.md`). |
