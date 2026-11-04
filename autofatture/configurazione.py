"""Lettura di config.yaml: percorsi, clienti autorizzati, soglie."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

FILE_PREDEFINITO = Path(__file__).resolve().parent.parent / "config.yaml"
VARIABILE_AMBIENTE = "AUTOFATTURE_CONFIG"


class ErroreConfigurazione(Exception):
    pass


@dataclass
class Sede:
    indirizzo: str
    cap: str
    comune: str
    provincia: str = ""
    nazione: str = "IT"


@dataclass
class Cliente:
    id: str
    denominazione: str
    partita_iva: str
    codice_fiscale: str
    sede: Sede
    cartella: str
    codice_destinatario: str = "0000000"
    ultimo_af_iniziale: dict[int, int] = field(default_factory=dict)


@dataclass
class Configurazione:
    modalita: str
    trasmittente_paese: str
    trasmittente_codice: str
    percorsi: dict[str, Path]
    cartella_cliente: str
    formato_numero: str
    soglia_importo_eur: float
    todoist: dict
    email: dict
    clienti: dict[str, Cliente]

    def cliente(self, id_cliente: str) -> Cliente:
        try:
            return self.clienti[id_cliente]
        except KeyError:
            raise ErroreConfigurazione(
                f"Cliente '{id_cliente}' non autorizzato alle autofatture "
                f"(clienti ammessi: {', '.join(sorted(self.clienti))})"
            ) from None

    def cliente_per_piva(self, partita_iva: str) -> Cliente | None:
        for c in self.clienti.values():
            if c.partita_iva == partita_iva:
                return c
        return None

    def percorso_archivio(self, cliente: Cliente, anno: int) -> Path:
        relativo = self.cartella_cliente.format(cartella=cliente.cartella, anno=anno)
        return self.percorsi["clienti_radice"] / relativo

    def numero_documento(self, n: int) -> str:
        return self.formato_numero.format(n=n)


PERCORSI_OBBLIGATORI = ("coda", "lavoro", "errori", "registro", "diario", "clienti_radice")


def carica(percorso: str | Path | None = None) -> Configurazione:
    percorso = Path(percorso or os.environ.get(VARIABILE_AMBIENTE) or FILE_PREDEFINITO)
    if not percorso.exists():
        raise ErroreConfigurazione(
            f"Manca il file di configurazione {percorso}: copiare config.esempio.yaml "
            "in config.yaml e compilarlo."
        )
    dati = yaml.safe_load(percorso.read_text(encoding="utf-8")) or {}

    modalita = dati.get("modalita", "simulazione")
    if modalita not in ("simulazione", "ade"):
        raise ErroreConfigurazione("modalita deve essere 'simulazione' oppure 'ade'")

    percorsi_raw = dati.get("percorsi") or {}
    mancanti = [p for p in PERCORSI_OBBLIGATORI if p not in percorsi_raw]
    if mancanti:
        raise ErroreConfigurazione(f"In 'percorsi' mancano: {', '.join(mancanti)}")
    percorsi = {k: Path(v) for k, v in percorsi_raw.items()}

    clienti = {}
    for c in dati.get("clienti") or []:
        cliente = Cliente(
            id=str(c["id"]),
            denominazione=c["denominazione"],
            partita_iva=str(c["partita_iva"]),
            codice_fiscale=str(c.get("codice_fiscale") or c["partita_iva"]),
            sede=Sede(**c["sede"]),
            cartella=c["cartella"],
            codice_destinatario=str(c.get("codice_destinatario", "0000000")),
            ultimo_af_iniziale={int(k): int(v) for k, v in (c.get("ultimo_af_iniziale") or {}).items()},
        )
        if cliente.id in clienti:
            raise ErroreConfigurazione(f"Cliente '{cliente.id}' ripetuto in config.yaml")
        clienti[cliente.id] = cliente
    if not clienti:
        raise ErroreConfigurazione("Nessun cliente autorizzato in config.yaml")

    trasmittente = dati.get("trasmittente") or {}
    return Configurazione(
        modalita=modalita,
        trasmittente_paese=trasmittente.get("id_paese", "IT"),
        trasmittente_codice=str(trasmittente.get("id_codice", "")),
        percorsi=percorsi,
        cartella_cliente=dati.get(
            "cartella_cliente", "{cartella}/{anno}/Contabilità/IVA/Autofatture"
        ),
        formato_numero=dati.get("formato_numero", "{n}/AF"),
        soglia_importo_eur=float(dati.get("soglia_importo_eur", 20000)),
        todoist=dati.get("todoist") or {},
        email=dati.get("email") or {},
        clienti=clienti,
    )
