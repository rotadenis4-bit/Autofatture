"""Generazione e validazione dell'XML FatturaPA (FPR12) per TD17, TD18, TD19.

L'autofattura è emessa dal cliente dello Studio (cessionario/committente) a nome
del fornitore estero. Il PDF originale viene sempre incluso in <Allegati>.
"""

from __future__ import annotations

import base64
import re
from decimal import Decimal
from pathlib import Path

from lxml import etree

from .configurazione import Cliente, Configurazione
from .modello import DatiAutofattura

NS_P = "http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2"
NS_DS = "http://www.w3.org/2000/09/xmldsig#"
NS_XSI = "http://www.w3.org/2001/XMLSchema-instance"
CARTELLA_SCHEMI = Path(__file__).resolve().parent.parent / "schemi"
FILE_XSD = "Schema_del_file_xml_FatturaPA_v1.2.2.xsd"
FILE_XMLDSIG = "xmldsig-core-schema.xsd"
ID_FISCALE_ESTERO_ASSENTE = "99999999999"

DESCRIZIONE_TD = {
    "TD17": "Integrazione/autofattura per acquisto servizi dall'estero",
    "TD18": "Integrazione per acquisto di beni intracomunitari",
    "TD19": "Integrazione/autofattura per acquisto di beni ex art. 17 c.2 DPR 633/72",
}
NORMA_TD = {
    "TD17": "art. 17 c.2 DPR 633/72",
    "TD18": "artt. 46 e 47 DL 331/93",
    "TD19": "art. 17 c.2 DPR 633/72",
}


class ErroreXML(Exception):
    pass


def _importo(valore: Decimal) -> str:
    return f"{valore:.2f}"


def _sotto(padre, nome: str, testo=None):
    el = etree.SubElement(padre, nome)
    if testo is not None:
        el.text = str(testo)
    return el


def _nazione(paese: str) -> str:
    # Nella partita IVA la Grecia è EL, nell'indirizzo ISO 3166 è GR.
    return "GR" if paese == "EL" else paese


def nome_allegato(dati: DatiAutofattura) -> str:
    fornitore = re.sub(r"[^A-Za-z0-9]+", "_", dati.fornitore.denominazione).strip("_")[:25]
    numero = re.sub(r"[^A-Za-z0-9-]+", "-", dati.fattura_originale.numero).strip("-")[:20]
    return f"Fattura_{fornitore}_{numero}.pdf"


def nome_file(config: Configurazione, progressivo: int) -> str:
    """IT<codice trasmittente>_<progressivo alfanumerico di 5 caratteri>.xml"""
    if progressivo < 1:
        raise ErroreXML("Il progressivo di invio parte da 1")
    cifre = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    testo = ""
    n = progressivo
    while n:
        n, r = divmod(n, 36)
        testo = cifre[r] + testo
    if len(testo) > 5:
        raise ErroreXML("Progressivo di invio esaurito")
    return f"{config.trasmittente_paese}{config.trasmittente_codice}_{testo.zfill(5)}.xml"


def genera(
    dati: DatiAutofattura,
    cliente: Cliente,
    config: Configurazione,
    pdf_originale: Path,
    progressivo_invio: int,
) -> bytes:
    pdf = Path(pdf_originale).read_bytes()
    if not pdf.startswith(b"%PDF"):
        raise ErroreXML(f"{pdf_originale} non è un PDF")

    radice = etree.Element(
        f"{{{NS_P}}}FatturaElettronica",
        nsmap={"p": NS_P, "ds": NS_DS, "xsi": NS_XSI},
        versione="FPR12",
    )
    radice.set(f"{{{NS_XSI}}}schemaLocation", f"{NS_P} {FILE_XSD}")

    # --- Header ---
    header = _sotto(radice, "FatturaElettronicaHeader")
    trasm = _sotto(header, "DatiTrasmissione")
    id_t = _sotto(trasm, "IdTrasmittente")
    _sotto(id_t, "IdPaese", config.trasmittente_paese)
    _sotto(id_t, "IdCodice", config.trasmittente_codice)
    _sotto(trasm, "ProgressivoInvio", str(progressivo_invio).zfill(5))
    _sotto(trasm, "FormatoTrasmissione", "FPR12")
    _sotto(trasm, "CodiceDestinatario", cliente.codice_destinatario)

    f = dati.fornitore
    cedente = _sotto(header, "CedentePrestatore")
    anag_c = _sotto(cedente, "DatiAnagrafici")
    id_iva_c = _sotto(anag_c, "IdFiscaleIVA")
    _sotto(id_iva_c, "IdPaese", f.paese)
    id_codice = re.sub(r"[^A-Za-z0-9]", "", f.id_fiscale)
    if id_codice.upper().startswith(f.paese):
        id_codice = id_codice[len(f.paese):]
    _sotto(id_iva_c, "IdCodice", id_codice or ID_FISCALE_ESTERO_ASSENTE)
    _sotto(_sotto(anag_c, "Anagrafica"), "Denominazione", f.denominazione)
    _sotto(anag_c, "RegimeFiscale", "RF18")
    sede_c = _sotto(cedente, "Sede")
    cap_valido = re.fullmatch(r"\d{5}", f.cap or "")
    indirizzo = f.indirizzo if cap_valido or not f.cap else f"{f.indirizzo} {f.cap}"
    _sotto(sede_c, "Indirizzo", indirizzo[:60])
    _sotto(sede_c, "CAP", f.cap if cap_valido else "00000")
    _sotto(sede_c, "Comune", f.comune)
    _sotto(sede_c, "Nazione", _nazione(f.paese))

    cess = _sotto(header, "CessionarioCommittente")
    anag_cc = _sotto(cess, "DatiAnagrafici")
    id_iva_cc = _sotto(anag_cc, "IdFiscaleIVA")
    _sotto(id_iva_cc, "IdPaese", "IT")
    _sotto(id_iva_cc, "IdCodice", cliente.partita_iva)
    _sotto(anag_cc, "CodiceFiscale", cliente.codice_fiscale)
    _sotto(_sotto(anag_cc, "Anagrafica"), "Denominazione", cliente.denominazione)
    sede_cc = _sotto(cess, "Sede")
    _sotto(sede_cc, "Indirizzo", cliente.sede.indirizzo)
    _sotto(sede_cc, "CAP", cliente.sede.cap)
    _sotto(sede_cc, "Comune", cliente.sede.comune)
    if cliente.sede.provincia:
        _sotto(sede_cc, "Provincia", cliente.sede.provincia)
    _sotto(sede_cc, "Nazione", cliente.sede.nazione)

    _sotto(header, "SoggettoEmittente", "CC")

    # --- Body ---
    body = _sotto(radice, "FatturaElettronicaBody")
    generali = _sotto(body, "DatiGenerali")
    doc = _sotto(generali, "DatiGeneraliDocumento")
    _sotto(doc, "TipoDocumento", dati.tipo_documento)
    _sotto(doc, "Divisa", "EUR")
    _sotto(doc, "Data", dati.data_documento.isoformat())
    _sotto(doc, "Numero", config.numero_documento(dati.numero_af))
    _sotto(doc, "ImportoTotaleDocumento", _importo(dati.totale_eur))

    o = dati.fattura_originale
    causali = [
        f"{DESCRIZIONE_TD[dati.tipo_documento]} - {NORMA_TD[dati.tipo_documento]}",
        f"Rif. fattura n. {o.numero} del {o.data:%d/%m/%Y} di {f.denominazione}"[:200],
    ]
    if o.divisa != "EUR":
        causali.append(
            f"Importo originale {o.totale_valuta} {o.divisa}, cambio BCE {dati.cambio} "
            f"del {dati.data_cambio:%d/%m/%Y}"[:200]
        )
    for testo in causali:
        _sotto(doc, "Causale", testo)

    collegata = _sotto(generali, "DatiFattureCollegate")
    _sotto(collegata, "IdDocumento", o.numero)
    _sotto(collegata, "Data", o.data.isoformat())

    beni = _sotto(body, "DatiBeniServizi")
    for i, riga in enumerate(dati.righe, 1):
        linea = _sotto(beni, "DettaglioLinee")
        imponibile = dati.imponibile_riga_eur(riga)
        _sotto(linea, "NumeroLinea", i)
        _sotto(linea, "Descrizione", riga.descrizione)
        _sotto(linea, "PrezzoUnitario", _importo(imponibile))
        _sotto(linea, "PrezzoTotale", _importo(imponibile))
        _sotto(linea, "AliquotaIVA", _importo(riga.aliquota))
    for aliquota, imponibile, imposta in dati.riepilogo_iva():
        riep = _sotto(beni, "DatiRiepilogo")
        _sotto(riep, "AliquotaIVA", _importo(aliquota))
        _sotto(riep, "ImponibileImporto", _importo(imponibile))
        _sotto(riep, "Imposta", _importo(imposta))
        _sotto(riep, "EsigibilitaIVA", "I")

    allegati = _sotto(body, "Allegati")
    _sotto(allegati, "NomeAttachment", nome_allegato(dati))
    _sotto(allegati, "FormatoAttachment", "PDF")
    _sotto(allegati, "DescrizioneAttachment", "Fattura originale del fornitore")
    _sotto(allegati, "Attachment", base64.b64encode(pdf).decode("ascii"))

    return etree.tostring(radice, xml_declaration=True, encoding="UTF-8", pretty_print=True)


# --- Validazione ---

OBBLIGATORI = (
    "FatturaElettronicaHeader/DatiTrasmissione/IdTrasmittente/IdCodice",
    "FatturaElettronicaHeader/DatiTrasmissione/ProgressivoInvio",
    "FatturaElettronicaHeader/DatiTrasmissione/CodiceDestinatario",
    "FatturaElettronicaHeader/CedentePrestatore/DatiAnagrafici/IdFiscaleIVA/IdPaese",
    "FatturaElettronicaHeader/CedentePrestatore/DatiAnagrafici/IdFiscaleIVA/IdCodice",
    "FatturaElettronicaHeader/CedentePrestatore/Sede/Nazione",
    "FatturaElettronicaHeader/CessionarioCommittente/DatiAnagrafici/IdFiscaleIVA/IdCodice",
    "FatturaElettronicaBody/DatiGenerali/DatiGeneraliDocumento/TipoDocumento",
    "FatturaElettronicaBody/DatiGenerali/DatiGeneraliDocumento/Data",
    "FatturaElettronicaBody/DatiGenerali/DatiGeneraliDocumento/Numero",
    "FatturaElettronicaBody/DatiBeniServizi/DettaglioLinee",
    "FatturaElettronicaBody/DatiBeniServizi/DatiRiepilogo",
    "FatturaElettronicaBody/Allegati/Attachment",
)


def _schema_xsd() -> etree.XMLSchema | None:
    xsd = CARTELLA_SCHEMI / FILE_XSD
    if not xsd.exists():
        return None
    testo = xsd.read_text(encoding="utf-8")
    locale = CARTELLA_SCHEMI / FILE_XMLDSIG
    if locale.exists():
        # Evita di scaricare lo schema della firma da w3.org a ogni validazione.
        testo = re.sub(
            r'schemaLocation="[^"]*xmldsig-core-schema\.xsd"',
            f'schemaLocation="{locale.as_uri()}"',
            testo,
        )
    documento = etree.fromstring(testo.encode("utf-8"), base_url=xsd.as_uri())
    return etree.XMLSchema(documento)


def valida(xml: bytes, richiedi_xsd: bool = False) -> list[str]:
    """Restituisce l'elenco degli errori (vuoto se l'XML è valido)."""
    errori = []
    try:
        radice = etree.fromstring(xml)
    except etree.XMLSyntaxError as e:
        return [f"XML non leggibile: {e}"]

    for percorso in OBBLIGATORI:
        if radice.find(percorso) is None:
            errori.append(f"Manca {percorso}")

    tipo = radice.findtext("FatturaElettronicaBody/DatiGenerali/DatiGeneraliDocumento/TipoDocumento")
    paese = radice.findtext(
        "FatturaElettronicaHeader/CedentePrestatore/DatiAnagrafici/IdFiscaleIVA/IdPaese"
    )
    if tipo in ("TD17", "TD18", "TD19") and paese == "IT":
        errori.append(f"{tipo} con cedente italiano: lo SDI lo scarterebbe")

    totale = Decimal("0")
    for riep in radice.iterfind("FatturaElettronicaBody/DatiBeniServizi/DatiRiepilogo"):
        imponibile = Decimal(riep.findtext("ImponibileImporto"))
        imposta = Decimal(riep.findtext("Imposta"))
        aliquota = Decimal(riep.findtext("AliquotaIVA"))
        atteso = (imponibile * aliquota / 100).quantize(Decimal("0.01"))
        if abs(atteso - imposta) > Decimal("0.01"):
            errori.append(f"Imposta {imposta} non coerente con {imponibile} al {aliquota}%")
        totale += imponibile + imposta
    dichiarato = radice.findtext(
        "FatturaElettronicaBody/DatiGenerali/DatiGeneraliDocumento/ImportoTotaleDocumento"
    )
    if dichiarato is not None and Decimal(dichiarato) != totale:
        errori.append(f"ImportoTotaleDocumento {dichiarato} diverso da {totale}")

    allegato = radice.findtext("FatturaElettronicaBody/Allegati/Attachment") or ""
    try:
        if not base64.b64decode(allegato, validate=True).startswith(b"%PDF"):
            errori.append("L'allegato non è il PDF originale")
    except ValueError:
        errori.append("Allegato non in base64")

    schema = _schema_xsd()
    if schema is None:
        if richiedi_xsd:
            errori.append(f"Schema XSD assente: copiare {FILE_XSD} in {CARTELLA_SCHEMI}")
    elif not schema.validate(radice):
        errori.extend(f"XSD riga {e.line}: {e.message}" for e in schema.error_log)
    return errori
