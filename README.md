# Autofatture TD17 / TD18 / TD19 – Studio Rota

Il collaboratore lancia `/autofattura` in Claude Code e trascina il PDF della
fattura estera. Claude legge i dati e li manda in coda. Il server dello Studio
fa tutto il resto: genera l'XML con il PDF originale allegato, lo carica sul
portale ADE con Entratel, archivia il PDF e apre un task Todoist quando qualcosa
non va. Il 14 di ogni mese manda il riepilogo a info@studiorota.eu.

(La routine TaxDome delle 07:30 è a parte, in `taxdome/`.)

## Come funziona

```
Collaboratore (Claude Code, /autofattura)          Server 192.168.50.254
──────────────────────────────────────────          ─────────────────────────────────────
1. verifica-pdf: contenuti attivi, testo sospetto
2. Claude legge il PDF → dati.json (solo dati)
3. domanda obbligatoria sull'ultimo numero AF
4. anteprima: tutte le regole + XML di prova
5. OK del collaboratore → accoda ───────────────►  6. ogni 15 min rifà TUTTI i controlli
                                                   7. confronta il numero AF col portale ADE
                                                   8. genera e valida l'XML (XSD) + PDF allegato
                                                   9. carica sul portale (Entratel)
                                                  10. esito SDI:
                                                      • consegnata / mancata consegna →
                                                        PDF in CLIENTI\<cliente>\<anno>\
                                                        Contabilità\IVA\Autofatture + registro
                                                      • scarto o errore → task Todoist
                                                  11. il 14: mail di riepilogo del mese prima
```

### Perché un PDF manipolato non può fare danni

Claude non ha né browser né credenziali: restituisce solo un modulo di dati.
Il server, prima di inviare, applica regole fisse che non dipendono da Claude:

- solo i clienti elencati in `config.yaml`; ogni altra P.IVA è bloccata;
- numero AF uguale al successivo nel registro **e** a quello sul portale ADE;
- totale e numero della fattura devono comparire davvero nel testo del PDF;
- la somma delle righe deve tornare col totale della fattura;
- niente doppioni (stesso fornitore e numero già autofatturati);
- sopra la soglia (`soglia_importo_eur`, predefinita 20.000 €) niente invio automatico;
- PDF con JavaScript, file incorporati, azioni automatiche o frasi rivolte a un AI: bloccato;
- XML valido sul tracciato ufficiale FatturaPA.

Sul portale il programma può fare solo tre cose: leggere l'ultimo AF, caricare
l'XML, leggere l'esito. Le credenziali Entratel stanno nel Gestore credenziali di
Windows del server e non compaiono mai in file, log o chat.

## Numerazione AF

- Una numerazione per cliente e per anno. Formato `1/AF` di base; per FFOMO e
  Porto di Clanezzo `AF01 07/26` (`formato_numero` del cliente).
- Nome file `IT<id trasmittente>_<numero><lettera>.xml`, es. `IT02259870166_50A.xml`:
  P.IVA per le società, CF di 16 caratteri per ditte individuali e persone fisiche.
  Se il nome è già stato usato (nuovo invio dopo uno scarto) la lettera diventa B, C...
- Il punto di partenza è `ultimo_af_iniziale` in `config.yaml`, da leggere una volta sul portale.
- Un numero **scartato** dallo SDI si riusa per il nuovo invio, tranne lo scarto
  **00404** (duplicato): lì lo SDI ha già quel numero, che resta occupato.
- Se il caricamento si interrompe a metà (`ERRORE_INVIO`), il numero resta
  occupato finché qualcuno non controlla sul portale: se il file non è arrivato,
  nel registro si mette `SCARTATA` e si ricarica il PDF.

## Installazione

### Server (una volta)

1. Copiare il repository sul server, ad esempio in `C:\Autofatture`.
2. Creare `\\192.168.50.254\Pubblica\AUTOFATTURE\` e mettere lì `config.yaml`,
   copiato da `config.esempio.yaml` e compilato: clienti, P.IVA, cartelle,
   ultimo numero AF, CF delle ditte individuali, id del progetto Todoist.
3. Lo schema ufficiale FatturaPA 1.2.3 è già in `schemi\`: senza, in modalità
   `ade` l'invio è bloccato.
4. Doppio clic su `windows\INSTALLA_SERVER.bat` con l'utente che userà il programma
   (non "Esegui come amministratore": le credenziali sono legate all'utente).
   Chiede le credenziali a caratteri nascosti e crea le attività pianificate:
   coda ogni 15 minuti, riepilogo il 14 alle 08:00.

### PC dei collaboratori

1. Clonare il repository e fare doppio clic su `windows\INSTALLA_POSTAZIONE.bat`.
2. Aprire Claude Code nella cartella del repository: il comando `/autofattura` è già disponibile.

## Stato attuale

| Parte | Stato |
|---|---|
| Lettura, controlli, XML con PDF allegato, registro, coda, esiti, archivio, task, riepilogo | pronta, coperta dai test |
| Modalità `simulazione` (prova completa senza invio) | pronta: è quella predefinita |
| Login Entratel, lettura ultimo AF, caricamento ed esiti sul portale (`autofatture/ade.py`) | **da completare sul server**: i passaggi vanno registrati sulle pagine reali del portale |
| Validazione XSD 1.2.3 + controlli pratici della skill *autofatture-estero* | pronta |
| Autofatture cumulative/riepilogative (Packlink mensile) | non automatiche: skill *autofatture-estero* |

## Comandi

```
python -m autofatture clienti                      # clienti autorizzati e prossimo AF
python -m autofatture verifica-pdf fattura.pdf
python -m autofatture anteprima dati.json fattura.pdf --xml prova.xml
python -m autofatture accoda dati.json fattura.pdf
python -m autofatture elabora                      # (server) coda + esiti
python -m autofatture riepilogo [--mese 2026-10] [--invia]
python -m autofatture imposta-credenziali          # (server)
```

Test: `python -m pytest`.
