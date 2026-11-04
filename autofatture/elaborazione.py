"""Coda di lavoro: dal collaboratore al server, dal server allo SDI.

Il collaboratore (tramite /autofattura in Claude Code) mette nella coda una
cartella con dati.json e originale.pdf, più il file PRONTO scritto per ultimo.
Il server, ogni 15 minuti, rifà tutti i controlli da zero, genera l'XML con il
PDF allegato, lo carica sul portale e poi controlla gli esiti.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import traceback
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from . import ade, controlli, notifiche, registro as reg, verifica_pdf, xml_fatturapa
from .configurazione import Configurazione
from .modello import DatiAutofattura, ErroreDati, leggi

FILE_DATI = "dati.json"
FILE_PDF = "originale.pdf"
FILE_PRONTO = "PRONTO"
FILE_ERRORE = "ERRORE.txt"
ERRORE_INVIO = "ERRORE_INVIO"
GIORNI_ATTESA_ESITO = 5

log = logging.getLogger("autofatture")


class Blocco(Exception):
    """Problema che ferma una singola autofattura (diventa un task)."""


def configura_diario(config: Configurazione) -> None:
    percorso = Path(config.percorsi["diario"])
    percorso.parent.mkdir(parents=True, exist_ok=True)
    if not any(isinstance(h, logging.FileHandler) for h in log.handlers):
        gestore = logging.FileHandler(percorso, encoding="utf-8")
        gestore.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(gestore)
        log.setLevel(logging.INFO)


def _slug(testo: str, massimo: int = 30) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", testo).strip("-")[:massimo] or "x"


def nome_pdf_archiviato(dati: DatiAutofattura) -> str:
    return (
        f"{dati.data_documento.isoformat()}_AF{dati.numero_af:03d}_"
        f"{_slug(dati.fornitore.denominazione, 25)}_{_slug(dati.fattura_originale.numero, 20)}.pdf"
    )


# --- Preparazione (lato collaboratore) ---

@dataclass
class Anteprima:
    dati: DatiAutofattura
    errori: list[str]
    avvisi: list[str]
    xml: bytes | None

    def riepilogo(self, config: Configurazione) -> str:
        d = self.dati
        cliente = config.clienti.get(d.cliente_id)
        righe = [
            f"Cliente:        {cliente.denominazione if cliente else d.cliente_id}",
            f"Fornitore:      {d.fornitore.denominazione} ({d.fornitore.paese})",
            f"Fattura orig.:  n. {d.fattura_originale.numero} del {d.fattura_originale.data:%d/%m/%Y}, "
            f"{d.fattura_originale.totale_valuta} {d.fattura_originale.divisa}",
            f"Autofattura:    {d.tipo_documento} n. "
            f"{cliente.numero_documento(d.numero_af, d.data_documento.year) if cliente else d.numero_af} "
            f"del {d.data_documento:%d/%m/%Y}",
        ]
        for aliquota, natura, imponibile, imposta in d.riepilogo_iva():
            voce_iva = f"{natura} esente" if natura else f"IVA {aliquota}%"
            righe.append(f"{voce_iva + ':':<16}imponibile {imponibile} €, imposta {imposta} €")
        righe.append(f"Totale:         {d.totale_eur} €  (pagamento {d.modalita_pagamento})")
        if self.errori:
            righe.append("\nBLOCCATA:")
            righe += [f"  - {e}" for e in self.errori]
        if self.avvisi:
            righe.append("\nAvvisi:")
            righe += [f"  - {a}" for a in self.avvisi]
        return "\n".join(righe)


def prepara(config: Configurazione, file_dati: Path, file_pdf: Path, oggi: date | None = None) -> Anteprima:
    """Controlli completi e XML di prova, senza scrivere nulla nella coda."""
    try:
        dati = leggi(file_dati)
    except ErroreDati as e:
        raise Blocco(f"Dati non validi: {e}") from None

    esito_pdf = verifica_pdf.verifica(file_pdf)
    errori = [] if esito_pdf.sicuro else [esito_pdf.descrizione()]
    errori += controlli.controlla(dati, config, reg.Registro(config), esito_pdf.testo, oggi)

    xml = None
    avvisi = []
    if dati.iva_estera_addebitata:
        avvisi.append(
            "Il fornitore ha addebitato IVA: è indetraibile, l'autofattura la include nell'imponibile "
            "e la fattura andrebbe fatta riemettere (il server apre un task)"
        )
    if not errori:
        cliente = config.cliente(dati.cliente_id)
        progressivo = xml_fatturapa.progressivo_libero(
            dati.numero_af, reg.Registro(config).progressivi_usati(cliente.id)
        )
        xml = xml_fatturapa.genera(dati, cliente, config, file_pdf, progressivo)
        errori += xml_fatturapa.valida(xml, xml_fatturapa.nome_file(cliente, progressivo))
        if not (xml_fatturapa.CARTELLA_SCHEMI / xml_fatturapa.FILE_XSD).exists():
            avvisi.append("Schema XSD ufficiale assente qui: la validazione completa la fa il server")
    return Anteprima(dati, errori, avvisi, xml)


def accoda(config: Configurazione, file_dati: Path, file_pdf: Path) -> Path:
    anteprima = prepara(config, file_dati, file_pdf)
    if anteprima.errori:
        raise Blocco("; ".join(anteprima.errori))
    d = anteprima.dati
    nome = f"{datetime.now():%Y%m%d-%H%M%S}_{_slug(d.cliente_id, 20)}_AF{d.numero_af:03d}_{uuid.uuid4().hex[:6]}"
    coda = Path(config.percorsi["coda"])
    temporanea = coda / f".{nome}"
    temporanea.mkdir(parents=True)
    shutil.copy2(file_dati, temporanea / FILE_DATI)
    shutil.copy2(file_pdf, temporanea / FILE_PDF)
    destinazione = coda / nome
    os.replace(temporanea, destinazione)
    (destinazione / FILE_PRONTO).write_text(datetime.now().isoformat(), encoding="utf-8")
    return destinazione


# --- Elaborazione (lato server) ---

@contextmanager
def _un_solo_server(config: Configurazione):
    blocco = Path(config.percorsi["lavoro"]) / "ELABORAZIONE_IN_CORSO.lock"
    blocco.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(blocco, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        eta = datetime.now() - datetime.fromtimestamp(blocco.stat().st_mtime)
        if eta < timedelta(hours=2):
            log.info("Elaborazione già in corso, salto questo giro")
            yield False
            return
        log.warning("Blocco di elaborazione vecchio di %s: lo rimuovo", eta)
        blocco.unlink()
        fd = os.open(blocco, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(fd)
    try:
        yield True
    finally:
        blocco.unlink(missing_ok=True)


def _segnala(config: Configurazione, titolo: str, dettaglio: str) -> None:
    log.error("%s | %s", titolo, dettaglio.replace("\n", " / "))
    try:
        notifiche.crea_task(config, titolo, dettaglio)
    except Exception as e:  # il task non deve mai fermare l'elaborazione
        log.error("Task Todoist non creato (%s): %s", e, titolo)


def _sposta_in_errori(config: Configurazione, cartella: Path, motivo: str) -> Path:
    errori = Path(config.percorsi["errori"])
    errori.mkdir(parents=True, exist_ok=True)
    destinazione = errori / cartella.name
    if destinazione.exists():
        destinazione = errori / f"{cartella.name}_{datetime.now():%H%M%S}"
    shutil.move(str(cartella), destinazione)
    (destinazione / FILE_ERRORE).write_text(motivo, encoding="utf-8")
    (destinazione / FILE_PRONTO).unlink(missing_ok=True)
    return destinazione


def _elabora_pacchetto(config: Configurazione, portale: ade.PortaleADE, cartella: Path) -> None:
    registro = reg.Registro(config)
    file_pdf = cartella / FILE_PDF
    anteprima = prepara(config, cartella / FILE_DATI, file_pdf)
    dati = anteprima.dati
    if anteprima.errori:
        raise Blocco("\n".join(anteprima.errori))
    cliente = config.cliente(dati.cliente_id)

    numero_portale = portale.ultimo_numero_af(cliente, dati.data_documento.year)
    if numero_portale is not None and numero_portale != dati.numero_af - 1:
        raise Blocco(
            f"Sul portale ADE l'ultimo AF di {cliente.denominazione} è {numero_portale}, "
            f"il registro dice {dati.numero_af - 1}: allineare prima di inviare"
        )

    progressivo = xml_fatturapa.progressivo_libero(dati.numero_af, registro.progressivi_usati(cliente.id))
    nome_xml = xml_fatturapa.nome_file(cliente, progressivo)
    xml = xml_fatturapa.genera(dati, cliente, config, file_pdf, progressivo)
    errori_xml = xml_fatturapa.valida(xml, nome_xml, richiedi_xsd=config.modalita == "ade")
    if errori_xml:
        raise Blocco("XML non valido:\n" + "\n".join(errori_xml))

    lavoro = Path(config.percorsi["lavoro"]) / cartella.name
    shutil.move(str(cartella), lavoro)
    (lavoro / FILE_PRONTO).unlink(missing_ok=True)
    file_xml = lavoro / nome_xml
    file_xml.write_bytes(xml)

    voce = reg.Voce(
        id=lavoro.name,
        cliente_id=cliente.id,
        cliente=cliente.denominazione,
        partita_iva_cliente=cliente.partita_iva,
        anno=str(dati.data_documento.year),
        numero_af=str(dati.numero_af),
        numero_documento=cliente.numero_documento(dati.numero_af, dati.data_documento.year),
        tipo_documento=dati.tipo_documento,
        data_documento=dati.data_documento.isoformat(),
        fornitore=dati.fornitore.denominazione,
        paese_fornitore=dati.fornitore.paese,
        numero_fattura_originale=dati.fattura_originale.numero,
        data_fattura_originale=dati.fattura_originale.data.isoformat(),
        imponibile_eur=str(dati.imponibile_eur),
        imposta_eur=str(dati.imposta_eur),
        file_xml=file_xml.name,
        progressivo_invio=progressivo,
        data_invio=datetime.now().isoformat(timespec="seconds"),
        stato=ERRORE_INVIO,
        caricato_da=dati.caricato_da,
    )
    # Registrata prima dell'invio: se il caricamento si interrompe a metà il
    # numero resta occupato finché qualcuno non verifica sul portale.
    registro.aggiungi(voce)
    try:
        caricamento = portale.carica(cliente, file_xml)
    except Exception as e:
        _segnala(
            config,
            f"Autofattura {voce.numero_documento} {cliente.denominazione}: invio non riuscito",
            f"Errore durante il caricamento sul portale: {e}\n"
            f"Verificare sul portale se il file {file_xml.name} è stato ricevuto.\n"
            f"Se NON è stato ricevuto, nel registro mettere stato SCARTATA e ricaricare il PDF.\n"
            f"File in {lavoro}",
        )
        return

    simulazione = isinstance(portale, ade.PortaleSimulato)
    if dati.iva_estera_addebitata and not simulazione:
        _segnala(
            config,
            f"Far riemettere la fattura {dati.fattura_originale.numero} di {dati.fornitore.denominazione}",
            f"Il fornitore ha addebitato IVA (indetraibile). Autofattura {voce.numero_documento} "
            f"di {cliente.denominazione} emessa su imponibile + IVA addebitata.",
        )
    registro.aggiorna(
        voce.id,
        stato=reg.SIMULATA if simulazione else reg.IN_ATTESA,
        identificativo_sdi=caricamento.identificativo,
        esito=caricamento.messaggio,
    )
    log.info(
        "Caricata %s %s (%s) id %s", voce.numero_documento, cliente.denominazione,
        file_xml.name, caricamento.identificativo,
    )
    if simulazione:
        destinazione = Path(config.percorsi["lavoro"]) / "SIMULAZIONE" / nome_pdf_archiviato(dati)
        destinazione.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(lavoro / FILE_PDF, destinazione)
        registro.aggiorna(voce.id, pdf_archiviato=str(destinazione))


def _archivia(config: Configurazione, voce: reg.Voce) -> Path:
    lavoro = Path(config.percorsi["lavoro"]) / voce.id
    dati = leggi(lavoro / FILE_DATI)
    cliente = config.cliente(voce.cliente_id)
    cartella = config.percorso_archivio(cliente, int(voce.anno))
    cartella.mkdir(parents=True, exist_ok=True)
    destinazione = cartella / nome_pdf_archiviato(dati)
    if destinazione.exists():
        raise Blocco(f"Nell'archivio esiste già {destinazione}")
    shutil.copy2(lavoro / FILE_PDF, destinazione)
    archivio_xml = Path(config.percorsi["lavoro"]) / "INVIATE" / voce.id
    archivio_xml.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(lavoro), archivio_xml)
    return destinazione


def controlla_esiti(config: Configurazione, portale: ade.PortaleADE) -> None:
    registro = reg.Registro(config)
    for voce in registro.in_attesa():
        cliente = config.cliente(voce.cliente_id)
        titolo = f"Autofattura {voce.numero_documento} {cliente.denominazione}"
        try:
            esito = portale.esito(cliente, voce.identificativo_sdi)
        except Exception as e:
            log.error("%s: esito non leggibile (%s)", titolo, e)
            continue
        if esito is None:
            inviata = datetime.fromisoformat(voce.data_invio)
            if datetime.now() - inviata > timedelta(days=GIORNI_ATTESA_ESITO):
                _segnala(config, f"{titolo}: esito SDI non arrivato",
                         f"Inviata il {inviata:%d/%m/%Y}, id {voce.identificativo_sdi}. Verificare sul portale.")
                registro.aggiorna(voce.id, esito=f"Esito non arrivato dopo {GIORNI_ATTESA_ESITO} giorni")
            continue

        if esito.stato in reg.STATI_OK:
            try:
                archiviato = _archivia(config, voce)
            except Exception as e:
                registro.aggiorna(voce.id, stato=esito.stato, esito=esito.descrizione)
                _segnala(config, f"{titolo}: inviata ma PDF non archiviato", str(e))
                continue
            registro.aggiorna(voce.id, stato=esito.stato, esito=esito.descrizione, pdf_archiviato=str(archiviato))
            log.info("%s %s, PDF in %s", titolo, esito.stato, archiviato)
        else:
            duplicato = "00404" in esito.descrizione
            registro.aggiorna(voce.id, stato=reg.DUPLICATO_SDI if duplicato else reg.SCARTATA, esito=esito.descrizione)
            lavoro = Path(config.percorsi["lavoro"]) / voce.id
            cartella = _sposta_in_errori(config, lavoro, f"Scartata dallo SDI: {esito.descrizione}") if lavoro.exists() else lavoro
            if duplicato:
                istruzioni = (
                    f"Lo SDI ha già un documento {voce.numero_documento} di questo fornitore e data: "
                    "verificare sul portale. Se è un vero doppione non fare nulla; altrimenti "
                    "ricaricare il PDF con il numero AF successivo (questo resta occupato)."
                )
            else:
                istruzioni = f"Il numero {voce.numero_documento} si riusa: correggere e ricaricare il PDF con lo stesso numero."
            _segnala(
                config, f"{titolo}: SCARTATA dallo SDI",
                f"Motivo: {esito.descrizione}\nFile in {cartella}\n{istruzioni}",
            )


def elabora(config: Configurazione) -> int:
    """Un giro completo: coda e poi esiti. Restituisce quante autofatture ha caricato."""
    configura_diario(config)
    caricate = 0
    with _un_solo_server(config) as via_libera:
        if not via_libera:
            return 0
        portale = ade.apri(config)
        try:
            coda = Path(config.percorsi["coda"])
            coda.mkdir(parents=True, exist_ok=True)
            for cartella in sorted(p for p in coda.iterdir() if (p / FILE_PRONTO).exists()):
                try:
                    _elabora_pacchetto(config, portale, cartella)
                    caricate += 1
                except Exception as e:
                    motivo = str(e) if isinstance(e, Blocco) else f"{e}\n\n{traceback.format_exc()}"
                    destinazione = _sposta_in_errori(config, cartella, motivo)
                    _segnala(config, f"Autofattura bloccata: {cartella.name}", f"{motivo}\n\nFile in {destinazione}")
            controlla_esiti(config, portale)
        finally:
            portale.chiudi()
    return caricate


# --- Riepilogo mensile ---

def mese_precedente(oggi: date | None = None) -> tuple[int, int]:
    primo = (oggi or date.today()).replace(day=1)
    ultimo_mese = primo - timedelta(days=1)
    return ultimo_mese.year, ultimo_mese.month


def riepilogo(config: Configurazione, anno: int, mese: int) -> tuple[str, str]:
    voci = reg.Registro(config).voci()
    prefisso = f"{anno:04d}-{mese:02d}"
    del_mese = [v for v in voci if v.data_documento.startswith(prefisso) and v.stato != reg.SIMULATA]

    problemi = (reg.SCARTATA, reg.DUPLICATO_SDI, ERRORE_INVIO)
    sistemati = {(v.cliente_id, v.anno, v.numero_af) for v in voci if v.stato not in problemi + (reg.SIMULATA,)}
    aperti = [
        v for v in voci
        if v.stato in problemi and (v.cliente_id, v.anno, v.numero_af) not in sistemati
    ]
    cartella_errori = Path(config.percorsi["errori"])
    bloccate = sorted(p.name for p in cartella_errori.iterdir() if p.is_dir()) if cartella_errori.exists() else []

    oggetto = f"Autofatture con data documento {mese:02d}/{anno} - riepilogo"
    righe = [f"Autofatture con data documento {mese:02d}/{anno}", ""]
    for cliente_id in sorted({v.cliente_id for v in del_mese}):
        proprie = sorted((v for v in del_mese if v.cliente_id == cliente_id), key=lambda v: int(v.numero_af))
        imponibile = sum((Decimal(v.imponibile_eur) for v in proprie), Decimal("0"))
        imposta = sum((Decimal(v.imposta_eur) for v in proprie), Decimal("0"))
        righe.append(f"{proprie[0].cliente} ({proprie[0].partita_iva_cliente})")
        for v in proprie:
            righe.append(
                f"  {v.numero_documento:<10} {v.tipo_documento} {v.data_documento}  {v.fornitore[:30]:<30} "
                f"imp. {v.imponibile_eur:>10}  IVA {v.imposta_eur:>9}  {v.stato}"
            )
        righe.append(f"  Totale: imponibile {imponibile} €, IVA {imposta} €")
        righe.append("")
    if not del_mese:
        righe += ["Nessuna autofattura nel mese.", ""]

    if aperti or bloccate:
        righe.append("DA SISTEMARE ENTRO IL 15:")
        righe += [f"  - {v.cliente} {v.numero_documento}: {v.stato} {v.esito}" for v in aperti]
        righe += [f"  - bloccata in coda: {nome}" for nome in bloccate]
    else:
        righe.append("Nessuno scarto o blocco aperto.")
    return oggetto, "\n".join(righe)
