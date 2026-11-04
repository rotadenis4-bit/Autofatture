"""Controllo automatico del PDF prima che Claude lo legga e prima dell'invio.

Cerca contenuti attivi (JavaScript, file incorporati, azioni automatiche) e testo
rivolto a un assistente AI. Non sostituisce le regole fisse di controlli.py: è
una rete in più.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

DIMENSIONE_MASSIMA = 10 * 1024 * 1024
PAGINE_MASSIME = 30
CHIAVI_PERICOLOSE = ("/JavaScript", "/JS", "/Launch", "/EmbeddedFile", "/OpenAction", "/AA", "/RichMedia", "/XFA")

FRASI_SOSPETTE = [
    r"ignor\w*\s+(le\s+|all\s+|the\s+|any\s+)?(istruzion|instruction|previous|precedent|regol)",
    r"(system|developer)\s*prompt",
    # Niente nomi di aziende AI: le loro fatture sono tipici TD17 da elaborare.
    r"(dear|caro|cara|gentile|hey|ciao)\s+(ai|ia|assistant|assistente|model|modello|claude)\b",
    r"(you\s+are|sei)\s+(now|ora|adesso)\b",
    r"(nuove|new)\s+(istruzioni|instructions)",
    r"(cambia|modifica|change|set)\s+(la\s+|the\s+)?(partita\s+iva|vat|iban|cliente|importo|numero)",
    r"(invia|send|trasmetti|inoltra|forward)\s+.{0,40}(credenzial|password|pin|token|chiav|key)",
    r"<\s*/?\s*(system|instructions?|prompt)\s*>",
    r"do\s+not\s+(tell|mention|inform)|non\s+(dire|segnalare|menzionare)",
]
_REGEX_SOSPETTE = [re.compile(r, re.IGNORECASE) for r in FRASI_SOSPETTE]
_CARATTERI_INVISIBILI = re.compile("[​-‏‪-‮⁠-⁤﻿]")


@dataclass
class EsitoVerifica:
    sicuro: bool
    problemi: list[str] = field(default_factory=list)
    pagine: int = 0
    testo: str = ""

    def descrizione(self) -> str:
        if self.sicuro:
            return f"PDF controllato: {self.pagine} pagine, nessun contenuto sospetto"
        return "PDF bloccato: " + "; ".join(self.problemi)


def _cerca_chiavi(oggetto, trovate: set, visti: set, profondita: int = 0) -> None:
    if profondita > 40:
        return
    try:
        oggetto = oggetto.get_object()
    except AttributeError:
        pass
    if id(oggetto) in visti:
        return
    visti.add(id(oggetto))
    if isinstance(oggetto, dict):
        for chiave, valore in oggetto.items():
            if chiave in CHIAVI_PERICOLOSE:
                trovate.add(chiave)
            _cerca_chiavi(valore, trovate, visti, profondita + 1)
    elif isinstance(oggetto, list):
        for valore in oggetto:
            _cerca_chiavi(valore, trovate, visti, profondita + 1)


def verifica(percorso: Path) -> EsitoVerifica:
    percorso = Path(percorso)
    problemi: list[str] = []

    dati = percorso.read_bytes()
    if not dati.startswith(b"%PDF"):
        return EsitoVerifica(False, ["il file non è un PDF"])
    if len(dati) > DIMENSIONE_MASSIMA:
        return EsitoVerifica(False, [f"file oltre {DIMENSIONE_MASSIMA // 1024 // 1024} MB"])

    try:
        lettore = PdfReader(percorso)
        if lettore.is_encrypted:
            return EsitoVerifica(False, ["PDF protetto da password"])
        pagine = len(lettore.pages)
    except (PdfReadError, ValueError, OSError) as e:
        return EsitoVerifica(False, [f"PDF non leggibile ({e})"])

    if pagine > PAGINE_MASSIME:
        problemi.append(f"{pagine} pagine: troppe per una fattura")

    trovate: set[str] = set()
    _cerca_chiavi(lettore.trailer, trovate, set())
    if trovate:
        problemi.append("contenuti attivi nel PDF: " + ", ".join(sorted(trovate)))

    testo = "\n".join((p.extract_text() or "") for p in lettore.pages[:PAGINE_MASSIME])
    if _CARATTERI_INVISIBILI.search(testo):
        problemi.append("caratteri invisibili nel testo")
    for regex in _REGEX_SOSPETTE:
        m = regex.search(testo)
        if m:
            problemi.append(f"testo sospetto: \"{m.group(0)[:60]}\"")

    return EsitoVerifica(not problemi, problemi, pagine, testo)
