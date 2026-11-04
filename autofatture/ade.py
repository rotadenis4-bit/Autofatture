"""Collegamento al portale Fatture e Corrispettivi dell'Agenzia delle Entrate.

Il programma può fare solo tre cose sul portale:
  1. leggere l'ultimo numero AF emesso da un cliente;
  2. caricare un XML già validato;
  3. leggere l'esito SDI di un file caricato.
Non esistono comandi per altre pagine (cassetto fiscale, F24, deleghe...).

In modalità 'simulazione' non si collega a nulla: l'XML viene copiato nella
cartella di lavoro e l'esito è SIMULATA. È la modalità di prova, che si ferma
prima dell'invio allo SDI.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .configurazione import Cliente, Configurazione


@dataclass
class Caricamento:
    identificativo: str
    messaggio: str


@dataclass
class Esito:
    stato: str  # CONSEGNATA, MANCATA_CONSEGNA, SCARTATA
    descrizione: str


class PortaleADE:
    def ultimo_numero_af(self, cliente: Cliente, anno: int) -> int | None:
        """Ultimo numero AF emesso nel portale, o None se non verificabile."""
        raise NotImplementedError

    def carica(self, cliente: Cliente, file_xml: Path) -> Caricamento:
        raise NotImplementedError

    def esito(self, cliente: Cliente, identificativo: str) -> Esito | None:
        """None finché lo SDI non ha ancora risposto."""
        raise NotImplementedError

    def chiudi(self) -> None:
        pass


class PortaleSimulato(PortaleADE):
    def __init__(self, cartella: Path):
        self.cartella = Path(cartella) / "SIMULAZIONE"

    def ultimo_numero_af(self, cliente, anno):
        return None

    def carica(self, cliente, file_xml):
        self.cartella.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file_xml, self.cartella / Path(file_xml).name)
        return Caricamento(
            identificativo=f"SIM-{datetime.now():%Y%m%d%H%M%S}",
            messaggio="Simulazione: XML NON inviato allo SDI",
        )

    def esito(self, cliente, identificativo):
        return Esito("SIMULATA", "Simulazione: nessun invio")


class PortaleEntratel(PortaleADE):
    """Accesso con credenziali Entratel tramite browser automatico (Playwright).

    DA COMPLETARE SUL SERVER: i passaggi sul portale vanno registrati sulle
    pagine reali (non raggiungibili dal cloud). Fino ad allora ogni metodo
    segnala l'errore e l'invio torna manuale, con un task in Todoist.
    """

    URL_ACCESSO = "https://telematici.agenziaentrate.gov.it/Main/login.jsp"

    def __init__(self, config: Configurazione):
        self.config = config
        self._browser = None
        self._pagina = None

    def _accedi(self):
        if self._pagina is not None:
            return self._pagina
        from playwright.sync_api import sync_playwright

        from . import credenziali

        utente = credenziali.leggi("entratel_utente")
        password = credenziali.leggi("entratel_password")
        pin = credenziali.leggi("entratel_pin")
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=True)
        self._pagina = self._browser.new_page()
        self._pagina.goto(self.URL_ACCESSO)
        # TODO (sul server): compilare utente/password/PIN nella scheda Entratel,
        # entrare in Fatture e Corrispettivi e scegliere l'utenza di lavoro
        # (incaricato per conto del cliente). Le credenziali non vanno mai
        # scritte nei log.
        del utente, password, pin
        raise NotImplementedError("Login Entratel da registrare sulle pagine reali del portale")

    def ultimo_numero_af(self, cliente, anno):
        self._accedi()
        # TODO: Fatture e Corrispettivi > Consultazione > Fatture emesse,
        # filtro anno e tipo TD17/TD18/TD19, leggere il numero AF più alto.
        raise NotImplementedError

    def carica(self, cliente, file_xml):
        self._accedi()
        # TODO: Fatture e Corrispettivi > Trasmissione > Upload file fattura,
        # caricare file_xml, confermare e leggere l'identificativo SDI.
        raise NotImplementedError

    def esito(self, cliente, identificativo):
        self._accedi()
        # TODO: Monitoraggio dei file trasmessi, cercare l'identificativo e
        # leggere la ricevuta (RC consegna, MC mancata consegna, NS scarto).
        raise NotImplementedError

    def chiudi(self):
        if self._browser is not None:
            self._browser.close()
            self._playwright.stop()
        self._browser = self._pagina = None


def apri(config: Configurazione) -> PortaleADE:
    if config.modalita == "ade":
        return PortaleEntratel(config)
    return PortaleSimulato(config.percorsi["lavoro"])
