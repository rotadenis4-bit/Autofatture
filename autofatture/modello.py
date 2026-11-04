"""Dati di un'autofattura, come li restituisce Claude in dati.json.

Claude legge il PDF e compila solo questo modulo. Tutto ciò che arriva da qui
è considerato non fidato: viene controllato con regole fisse in controlli.py
prima di generare l'XML.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

TIPI_DOCUMENTO = ("TD17", "TD18", "TD19")
ALIQUOTE_AMMESSE = (Decimal("4"), Decimal("5"), Decimal("10"), Decimal("22"))
PAESI_UE = {
    "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "EL", "GR", "ES", "FI", "FR",
    "HR", "HU", "IE", "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO", "SE", "SI", "SK",
}
CENTESIMO = Decimal("0.01")


class ErroreDati(Exception):
    pass


def euro(valore: Decimal) -> Decimal:
    return valore.quantize(CENTESIMO, rounding=ROUND_HALF_UP)


def _decimale(valore, campo: str) -> Decimal:
    try:
        d = Decimal(str(valore))
    except (InvalidOperation, ValueError):
        raise ErroreDati(f"{campo}: '{valore}' non è un numero") from None
    if not d.is_finite():
        raise ErroreDati(f"{campo}: valore non valido")
    return d


def _data(valore, campo: str) -> date:
    try:
        return date.fromisoformat(str(valore))
    except ValueError:
        raise ErroreDati(f"{campo}: '{valore}' non è una data AAAA-MM-GG") from None


def _testo(valore, campo: str, massimo: int, obbligatorio: bool = True) -> str:
    testo = re.sub(r"\s+", " ", str(valore or "")).strip()
    if obbligatorio and not testo:
        raise ErroreDati(f"{campo}: obbligatorio")
    if len(testo) > massimo:
        raise ErroreDati(f"{campo}: massimo {massimo} caratteri")
    return testo


@dataclass
class Fornitore:
    denominazione: str
    paese: str
    id_fiscale: str
    indirizzo: str
    comune: str
    cap: str = ""


@dataclass
class Riga:
    descrizione: str
    importo_valuta: Decimal
    aliquota: Decimal = Decimal("22")


@dataclass
class FatturaOriginale:
    numero: str
    data: date
    divisa: str
    totale_valuta: Decimal


@dataclass
class DatiAutofattura:
    cliente_id: str
    tipo_documento: str
    numero_af: int
    data_documento: date
    fornitore: Fornitore
    fattura_originale: FatturaOriginale
    righe: list[Riga]
    cambio: Decimal | None = None
    data_cambio: date | None = None
    caricato_da: str = ""
    controllo_contenuto: dict = field(default_factory=dict)

    def imponibile_riga_eur(self, riga: Riga) -> Decimal:
        if self.fattura_originale.divisa == "EUR":
            return euro(riga.importo_valuta)
        return euro(riga.importo_valuta / self.cambio)

    def riepilogo_iva(self) -> list[tuple[Decimal, Decimal, Decimal]]:
        """(aliquota, imponibile, imposta) per aliquota, in euro."""
        per_aliquota: dict[Decimal, Decimal] = {}
        for riga in self.righe:
            per_aliquota[riga.aliquota] = (
                per_aliquota.get(riga.aliquota, Decimal("0")) + self.imponibile_riga_eur(riga)
            )
        return [
            (aliquota, imponibile, euro(imponibile * aliquota / 100))
            for aliquota, imponibile in sorted(per_aliquota.items())
        ]

    @property
    def imponibile_eur(self) -> Decimal:
        return sum((r[1] for r in self.riepilogo_iva()), Decimal("0"))

    @property
    def imposta_eur(self) -> Decimal:
        return sum((r[2] for r in self.riepilogo_iva()), Decimal("0"))

    @property
    def totale_eur(self) -> Decimal:
        return self.imponibile_eur + self.imposta_eur

    def a_json(self) -> str:
        def converti(o):
            if isinstance(o, Decimal):
                return str(o)
            if isinstance(o, date):
                return o.isoformat()
            raise TypeError(type(o))

        return json.dumps(asdict(self), default=converti, ensure_ascii=False, indent=2)


def da_dizionario(d: dict) -> DatiAutofattura:
    try:
        f = d["fornitore"]
        o = d["fattura_originale"]
        righe_raw = d["righe"]
    except (KeyError, TypeError) as e:
        raise ErroreDati(f"Campo mancante: {e}") from None

    tipo = str(d.get("tipo_documento", "")).upper()
    if tipo not in TIPI_DOCUMENTO:
        raise ErroreDati(f"tipo_documento deve essere uno di {', '.join(TIPI_DOCUMENTO)}")

    try:
        numero_af = int(d["numero_af"])
    except (KeyError, TypeError, ValueError):
        raise ErroreDati("numero_af: obbligatorio, numero intero") from None
    if numero_af < 1:
        raise ErroreDati("numero_af: deve essere almeno 1")

    paese = _testo(f.get("paese"), "fornitore.paese", 2).upper()
    if not re.fullmatch(r"[A-Z]{2}", paese):
        raise ErroreDati("fornitore.paese: codice ISO a 2 lettere")

    fornitore = Fornitore(
        denominazione=_testo(f.get("denominazione"), "fornitore.denominazione", 80),
        paese=paese,
        id_fiscale=_testo(f.get("id_fiscale"), "fornitore.id_fiscale", 28, obbligatorio=False),
        indirizzo=_testo(f.get("indirizzo"), "fornitore.indirizzo", 60),
        comune=_testo(f.get("comune"), "fornitore.comune", 60),
        cap=_testo(f.get("cap"), "fornitore.cap", 10, obbligatorio=False),
    )

    divisa = _testo(o.get("divisa", "EUR"), "fattura_originale.divisa", 3).upper()
    if not re.fullmatch(r"[A-Z]{3}", divisa):
        raise ErroreDati("fattura_originale.divisa: codice ISO a 3 lettere")
    originale = FatturaOriginale(
        numero=_testo(o.get("numero"), "fattura_originale.numero", 20),
        data=_data(o.get("data"), "fattura_originale.data"),
        divisa=divisa,
        totale_valuta=_decimale(o.get("totale_valuta"), "fattura_originale.totale_valuta"),
    )

    if not isinstance(righe_raw, list) or not righe_raw:
        raise ErroreDati("righe: almeno una riga")
    righe = []
    for i, r in enumerate(righe_raw, 1):
        aliquota = _decimale(r.get("aliquota", 22), f"righe[{i}].aliquota")
        if aliquota not in ALIQUOTE_AMMESSE:
            raise ErroreDati(f"righe[{i}].aliquota: {aliquota} non ammessa")
        importo = _decimale(r.get("importo_valuta"), f"righe[{i}].importo_valuta")
        if importo <= 0:
            raise ErroreDati(f"righe[{i}].importo_valuta: deve essere positivo")
        righe.append(
            Riga(
                descrizione=_testo(r.get("descrizione"), f"righe[{i}].descrizione", 1000),
                importo_valuta=importo,
                aliquota=aliquota,
            )
        )

    cambio = data_cambio = None
    if divisa != "EUR":
        if d.get("cambio") in (None, ""):
            raise ErroreDati(f"Fattura in {divisa}: serve il cambio BCE (unità di {divisa} per 1 EUR)")
        cambio = _decimale(d["cambio"], "cambio")
        if cambio <= 0:
            raise ErroreDati("cambio: deve essere positivo")
        data_cambio = _data(d.get("data_cambio"), "data_cambio")

    controllo = d.get("controllo_contenuto") or {}
    if not isinstance(controllo, dict):
        raise ErroreDati("controllo_contenuto: deve essere un oggetto")

    return DatiAutofattura(
        cliente_id=_testo(d.get("cliente_id"), "cliente_id", 50),
        tipo_documento=tipo,
        numero_af=numero_af,
        data_documento=_data(d.get("data_documento"), "data_documento"),
        fornitore=fornitore,
        fattura_originale=originale,
        righe=righe,
        cambio=cambio,
        data_cambio=data_cambio,
        caricato_da=_testo(d.get("caricato_da"), "caricato_da", 80, obbligatorio=False),
        controllo_contenuto=controllo,
    )


def leggi(percorso: Path) -> DatiAutofattura:
    try:
        dati = json.loads(Path(percorso).read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ErroreDati(f"{percorso}: JSON non valido ({e})") from None
    if not isinstance(dati, dict):
        raise ErroreDati(f"{percorso}: atteso un oggetto JSON")
    return da_dizionario(dati)
