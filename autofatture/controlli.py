"""Regole fisse applicate ai dati estratti da Claude, prima di generare e inviare.

Queste regole non dipendono dal giudizio di Claude: se un PDF manipolato riesce a
falsare un dato, l'invio si ferma comunque qui.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import Decimal

from .configurazione import Configurazione, ErroreConfigurazione
from .modello import PAESI_UE, DatiAutofattura
from .registro import Registro

TOLLERANZA = Decimal("0.02")


def _formati_importo(valore: Decimal) -> set[str]:
    """Modi in cui un importo può comparire nel testo del PDF."""
    v = f"{valore:.2f}"
    intero, decimali = v.split(".")
    con_migliaia = f"{int(intero):,}"
    return {
        v,
        f"{intero},{decimali}",
        f"{con_migliaia}.{decimali}",
        f"{con_migliaia.replace(',', '.')},{decimali}",
    }


def importo_nel_testo(valore: Decimal, testo: str) -> bool:
    compatto = re.sub(r"\s", "", testo)
    return any(
        re.search(rf"(?<![\d.,]){re.escape(f)}(?![\d])", compatto) for f in _formati_importo(valore)
    )


def controlla(
    dati: DatiAutofattura,
    config: Configurazione,
    registro: Registro,
    testo_pdf: str,
    oggi: date | None = None,
) -> list[str]:
    oggi = oggi or date.today()
    errori: list[str] = []

    try:
        config.cliente(dati.cliente_id)
    except ErroreConfigurazione as e:
        return [str(e)]

    esito_claude = str(dati.controllo_contenuto.get("esito", "")).lower()
    if esito_claude != "ok":
        motivo = dati.controllo_contenuto.get("motivo") or "controllo del contenuto non eseguito"
        errori.append(f"Controllo del contenuto non superato: {motivo}")

    paese = dati.fornitore.paese
    if paese == "IT":
        errori.append("Fornitore italiano: non è un'autofattura TD17/TD18/TD19")
    if dati.tipo_documento == "TD18" and paese not in PAESI_UE:
        errori.append(f"TD18 solo per beni da fornitori UE, il fornitore è {paese}")

    if dati.data_documento > oggi:
        errori.append(f"Data documento {dati.data_documento} nel futuro")
    if dati.data_documento < oggi - timedelta(days=400):
        errori.append(f"Data documento {dati.data_documento} troppo vecchia: verificare a mano")
    if dati.fattura_originale.data > oggi:
        errori.append(f"Data della fattura originale {dati.fattura_originale.data} nel futuro")

    anno = dati.data_documento.year
    atteso = registro.ultimo_numero(dati.cliente_id, anno) + 1
    if dati.numero_af != atteso:
        errori.append(
            f"Numero AF {dati.numero_af} non in sequenza: per {dati.cliente_id} nel {anno} "
            f"il prossimo è {atteso}"
        )

    doppione = registro.duplicato(dati.cliente_id, dati.fornitore.denominazione, dati.fattura_originale.numero)
    if doppione:
        errori.append(
            f"Fattura {dati.fattura_originale.numero} di {dati.fornitore.denominazione} già "
            f"autofatturata con {doppione.numero_documento} ({doppione.stato})"
        )

    somma_righe = sum((r.importo_valuta for r in dati.righe), Decimal("0"))
    if abs(somma_righe - dati.fattura_originale.totale_valuta) > TOLLERANZA:
        errori.append(
            f"Somma delle righe {somma_righe} diversa dal totale della fattura "
            f"{dati.fattura_originale.totale_valuta} {dati.fattura_originale.divisa}"
        )
    if not importo_nel_testo(abs(dati.fattura_originale.totale_valuta), testo_pdf):
        errori.append(
            f"Il totale {dati.fattura_originale.totale_valuta} non compare nel testo del PDF"
        )
    if dati.fattura_originale.numero.casefold() not in re.sub(r"\s+", " ", testo_pdf).casefold():
        # Il numero può essere spezzato in più righe nel testo estratto.
        compatto = re.sub(r"[\s-]", "", testo_pdf).casefold()
        if re.sub(r"[\s-]", "", dati.fattura_originale.numero).casefold() not in compatto:
            errori.append(f"Il numero fattura {dati.fattura_originale.numero} non compare nel PDF")

    if abs(dati.totale_eur) > Decimal(str(config.soglia_importo_eur)):
        errori.append(
            f"Totale {dati.totale_eur} € oltre la soglia di invio automatico "
            f"({config.soglia_importo_eur:.2f} €)"
        )
    return errori
