"""Lettura di config.yaml: percorsi, clienti autorizzati, soglie."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

FILE_PREDEFINITO = Path(__file__).resolve().parent.parent / "config.yaml"
VARIABILE_AMBIENTE = "AUTOFATTURE_CONFIG"


SEGNAPOSTO = "DA_COMPLETARE"


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
    id_trasmittente: str = ""
    formato_numero: str = "{n}/AF"
    codice_destinatario: str = "0000000"
    ultimo_af_iniziale: dict[int, int] = field(default_factory=dict)

    def campi_da_completare(self) -> list[str]:
        valori = {
            "partita_iva": self.partita_iva,
            "codice_fiscale": self.codice_fiscale,
            "id_trasmittente": self.id_trasmittente,
            "sede.indirizzo": self.sede.indirizzo,
            "sede.cap": self.sede.cap,
            "sede.comune": self.sede.comune,
            "cartella": self.cartella,
        }
        return [k for k, v in valori.items() if not v or SEGNAPOSTO in v]

    def numero_documento(self, n: int, anno: int) -> str:
        return self.formato_numero.format(n=n, anno=anno, aa=f"{anno % 100:02d}")


@dataclass
class Configurazione:
    modalita: str
    percorsi: dict[str, Path]
    cartella_cliente: str
    soglia_importo_eur: float
    todoist: dict
    email: dict
    clienti: dict[str, Cliente]

    def cliente(self, id_cliente: str) -> Cliente:
        try:
            cliente = self.clienti[id_cliente]
        except KeyError:
            raise ErroreConfigurazione(
                f"Cliente '{id_cliente}' non autorizzato alle autofatture "
                f"(clienti ammessi: {', '.join(sorted(self.clienti))})"
            ) from None
        mancanti = cliente.campi_da_completare()
        if mancanti:
            raise ErroreConfigurazione(
                f"Anagrafica di {cliente.denominazione} incompleta in config.yaml: {', '.join(mancanti)}"
            )
        return cliente

    def cliente_per_piva(self, partita_iva: str) -> Cliente | None:
        for c in self.clienti.values():
            if c.partita_iva == partita_iva:
                return c
        return None

    def percorso_archivio(self, cliente: Cliente, anno: int) -> Path:
        relativo = self.cartella_cliente.format(cartella=cliente.cartella, anno=anno)
        return self.percorsi["clienti_radice"] / relativo



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
        partita_iva = str(c["partita_iva"]).upper().removeprefix("IT")
        if SEGNAPOSTO not in partita_iva and not re.fullmatch(r"\d{11}", partita_iva):
            raise ErroreConfigurazione(f"P.IVA di {c['denominazione']} non valida: {c['partita_iva']}")
        cliente = Cliente(
            id=str(c["id"]),
            denominazione=c["denominazione"],
            partita_iva=partita_iva,
            codice_fiscale=str(c.get("codice_fiscale") or partita_iva).upper(),
            sede=Sede(**c["sede"]),
            cartella=c["cartella"],
            # Società: P.IVA. Ditte individuali e persone fisiche: CF di 16 caratteri (scarto 00300).
            id_trasmittente=str(c.get("id_trasmittente") or partita_iva).upper(),
            formato_numero=c.get("formato_numero", dati.get("formato_numero", "{n}/AF")),
            codice_destinatario=str(c.get("codice_destinatario", "0000000")),
            ultimo_af_iniziale={int(k): int(v) for k, v in (c.get("ultimo_af_iniziale") or {}).items()},
        )
        if cliente.id in clienti:
            raise ErroreConfigurazione(f"Cliente '{cliente.id}' ripetuto in config.yaml")
        clienti[cliente.id] = cliente
    if not clienti:
        raise ErroreConfigurazione("Nessun cliente autorizzato in config.yaml")

    return Configurazione(
        modalita=modalita,
        percorsi=percorsi,
        cartella_cliente=dati.get(
            "cartella_cliente", "{cartella}/{anno}/Contabilità/IVA/Autofatture"
        ),
        soglia_importo_eur=float(dati.get("soglia_importo_eur", 20000)),
        todoist=dati.get("todoist") or {},
        email=dati.get("email") or {},
        clienti=clienti,
    )
