"""Registro delle autofatture (CSV con separatore ';', apribile in Excel).

È la fonte della numerazione AF: l'ultimo numero di un cliente è il più alto tra
quello iniziale in config.yaml e quelli del registro non scartati. Un numero
scartato dallo SDI si riusa per il nuovo invio.
"""

from __future__ import annotations

import csv
import os
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from pathlib import Path

from .configurazione import Configurazione

IN_ATTESA = "IN_ATTESA_ESITO"
CONSEGNATA = "CONSEGNATA"
MANCATA_CONSEGNA = "MANCATA_CONSEGNA"
SCARTATA = "SCARTATA"
# Scarto 00404: lo SDI ha già un documento con lo stesso numero, che quindi resta occupato.
DUPLICATO_SDI = "SCARTATA_DUPLICATO"
SIMULATA = "SIMULATA"
STATI_OK = (CONSEGNATA, MANCATA_CONSEGNA)


@dataclass
class Voce:
    id: str
    cliente_id: str
    cliente: str
    partita_iva_cliente: str
    anno: str
    numero_af: str
    numero_documento: str
    tipo_documento: str
    data_documento: str
    fornitore: str
    paese_fornitore: str
    numero_fattura_originale: str
    data_fattura_originale: str
    imponibile_eur: str
    imposta_eur: str
    file_xml: str
    progressivo_invio: str
    data_invio: str
    stato: str
    identificativo_sdi: str = ""
    esito: str = ""
    pdf_archiviato: str = ""
    caricato_da: str = ""


CAMPI = [f.name for f in fields(Voce)]


class Registro:
    def __init__(self, config: Configurazione):
        self.config = config
        self.percorso = Path(config.percorsi["registro"])

    # --- lettura ---

    def voci(self) -> list[Voce]:
        if not self.percorso.exists():
            return []
        with self.percorso.open(encoding="utf-8-sig", newline="") as f:
            return [Voce(**{k: r.get(k, "") or "" for k in CAMPI}) for r in csv.DictReader(f, delimiter=";")]

    def ultimo_numero(self, cliente_id: str, anno: int) -> int:
        cliente = self.config.clienti[cliente_id]
        numeri = [cliente.ultimo_af_iniziale.get(anno, 0)]
        numeri += [
            int(v.numero_af)
            for v in self.voci()
            if v.cliente_id == cliente_id and v.anno == str(anno) and v.stato not in (SCARTATA, SIMULATA)
        ]
        return max(numeri)

    def progressivi_usati(self, cliente_id: str) -> set[str]:
        """Progressivi dei file già trasmessi per il cliente (il nome file deve essere unico)."""
        return {
            v.progressivo_invio.upper()
            for v in self.voci()
            if v.cliente_id == cliente_id and v.stato != SIMULATA and v.progressivo_invio
        }

    def duplicato(self, cliente_id: str, fornitore: str, numero_originale: str) -> Voce | None:
        chiave = (fornitore.casefold().strip(), numero_originale.casefold().strip())
        for v in self.voci():
            if (
                v.cliente_id == cliente_id
                and v.stato not in (SCARTATA, SIMULATA)
                and (v.fornitore.casefold().strip(), v.numero_fattura_originale.casefold().strip()) == chiave
            ):
                return v
        return None

    def in_attesa(self) -> list[Voce]:
        return [v for v in self.voci() if v.stato == IN_ATTESA]

    # --- scrittura ---

    @contextmanager
    def _blocco(self, attesa_massima: float = 30.0):
        blocco = self.percorso.with_suffix(".lock")
        inizio = time.monotonic()
        while True:
            try:
                fd = os.open(blocco, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                break
            except FileExistsError:
                if time.monotonic() - inizio > attesa_massima:
                    raise TimeoutError(f"Registro bloccato da {blocco}: verificare che nessun altro lo stia scrivendo")
                time.sleep(0.5)
        try:
            os.write(fd, f"{os.getpid()} {datetime.now().isoformat()}".encode())
            os.close(fd)
            yield
        finally:
            blocco.unlink(missing_ok=True)

    def _scrivi(self, voci: list[Voce]) -> None:
        self.percorso.parent.mkdir(parents=True, exist_ok=True)
        temporaneo = self.percorso.with_suffix(".tmp")
        with temporaneo.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=CAMPI, delimiter=";")
            w.writeheader()
            for v in voci:
                w.writerow(asdict(v))
        os.replace(temporaneo, self.percorso)

    def aggiungi(self, voce: Voce) -> None:
        with self._blocco():
            voci = self.voci()
            if any(v.id == voce.id for v in voci):
                raise ValueError(f"Voce {voce.id} già nel registro")
            voci.append(voce)
            self._scrivi(voci)

    def aggiorna(self, id_voce: str, **campi) -> Voce:
        with self._blocco():
            voci = self.voci()
            for v in voci:
                if v.id == id_voce:
                    for k, valore in campi.items():
                        if k not in CAMPI:
                            raise KeyError(k)
                        setattr(v, k, str(valore))
                    self._scrivi(voci)
                    return v
        raise KeyError(f"Voce {id_voce} non trovata nel registro")
