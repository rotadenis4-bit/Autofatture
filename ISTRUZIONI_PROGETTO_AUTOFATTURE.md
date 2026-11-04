# Progetto Claude "Autofatture" – Istruzioni operative

Istruzioni da incollare nel Progetto Claude condiviso dello Studio Rota.
Qualsiasi collaboratore può allegare una fattura estera e chiedere l'autofattura.

## 1. Cosa fa il collaboratore

Allega il PDF della fattura del fornitore estero e scrive, ad esempio:
"autofattura per <cliente>". Se il cliente non è indicato, Claude lo ricava
dai dati del destinatario in fattura e chiede conferma.

## 2. Controlli obbligatori prima di generare

1. **Cliente.** Deve corrispondere a uno dei clienti gestiti per le autofatture.
   Se il cliente non è certo, Claude chiede e non procede.
2. **Ultimo numero AF (condizione obbligatoria).** Claude chiede sempre:
   "Qual è l'ultimo numero AF emesso per <cliente> nel 2026?"
   - Se il registro autofatture contiene già righe per quel cliente, Claude
     propone il numero successivo, ma il collaboratore lo deve confermare.
   - Se il numero indicato non coincide con il registro, Claude segnala la
     differenza e non genera finché non è chiarita.
   - Senza conferma del numero l'autofattura **non viene generata**.
3. **Fattura già trattata.** Claude controlla nel registro che fornitore e
   numero della fattura originale non siano già stati autofatturati.

## 3. Generazione

Claude usa la skill *autofatture-estero*:

- Tipo documento:
  - **TD17**: servizi da fornitore estero (UE o extra-UE)
  - **TD18**: beni intra-UE
  - **TD19**: beni da fornitore estero già presenti in Italia (art. 17 c. 2)
- Sezionale **AF**, numero `<progressivo>/AF` (stesso formato usato finora)
- Data documento:
  - TD17 e TD19: data di ricezione o di effettuazione dell'operazione
  - TD18: data di ricezione della fattura del fornitore
- Importi in valuta: conversione al cambio BCE della data della fattura,
  con il cambio indicato nella descrizione
- PDF originale allegato all'XML
- Validazione XSD obbligatoria. Se fallisce, l'XML non viene consegnato.
- Nome file: `IT<P.IVA cliente>_<progressivo univoco>.xml`

Prima della consegna Claude mostra il riepilogo da confermare:
cliente, fornitore, TD, numero AF, data, imponibile, aliquota, IVA.

## 4. Invio

- **Fase transitoria (oggi):** il collaboratore scarica l'XML e lo carica sul
  portale ADE Fatture e Corrispettivi.
- **Fase automatica (con intermediario SDI via API):** Claude deposita XML e PDF
  in `AUTOFATTURE/DA INVIARE` su SharePoint e da lì Power Automate invia.

## 5. Esito

| Esito SDI | Azione |
|---|---|
| Ricevuta di consegna (RC) o mancata consegna (MC) | PDF originale in `Clienti\<Nome>\2026\Contabilità\IVA\Autofatture`, riga nel registro con esito OK |
| Scarto (NS) o errore | Task Todoist nel progetto **Autofatture** con cliente, numero AF, codice e descrizione dello scarto, XML allegato |

Un numero AF scartato **non** si considera usato: il nuovo invio riusa lo
stesso numero e la stessa data.

## 6. Registro autofatture

Una riga per autofattura, con queste colonne: cliente, P.IVA cliente,
numero AF, TD, data documento, fornitore, numero fattura originale,
imponibile, IVA, data invio, esito SDI, identificativo SDI.

## 7. Riepilogo mensile

Ogni **14 del mese** parte una mail a **info@studiorota.eu** con:

- autofatture **con data documento nel mese precedente**, raggruppate per
  cliente, con totale imponibile e IVA;
- elenco degli scarti ancora aperti, da sistemare entro il 15.
