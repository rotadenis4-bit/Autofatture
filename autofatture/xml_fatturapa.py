"""Generazione e validazione dell'XML FatturaPA (FPR12) per TD17, TD18, TD19.

Segue le regole della skill autofatture-estero dello Studio: l'autofattura è
emessa dal cliente (cessionario/committente, SoggettoEmittente CC) a nome del
fornitore estero (RF18), con il PDF originale sempre in <Allegati>.
"""

from __future__ import annotations

import base64
import io
import re
from decimal import Decimal
from pathlib import Path

from lxml import etree

from .configurazione import Cliente, Configurazione
from .modello import NATURE_AMMESSE, DatiAutofattura

NS_P = "http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2"
NS_DS = "http://www.w3.org/2000/09/xmldsig#"
NS_XSI = "http://www.w3.org/2001/XMLSchema-instance"
CARTELLA_SCHEMI = Path(__file__).resolve().parent.parent / "schemi"
FILE_XSD = "Schema_del_file_xml_FatturaPA_v1.2.3.xsd"
FILE_XMLDSIG = "xmldsig-core-schema.xsd"
ID_FISCALE_ESTERO_ASSENTE = "99999999999"
SOGLIA_COMPRESSIONE = 800 * 1024       # oltre si ricomprime l'allegato
DIMENSIONE_MASSIMA_FILE = 5 * 1024 * 1024  # limite SDI per file

NORMA_TD = {
    "TD17": "Integrazione/autofattura art. 17 c. 2 DPR 633/72",
    "TD18": "Integrazione art. 46 DL 331/93",
    "TD19": "Integrazione/autofattura art. 17 c. 2 DPR 633/72",
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


def _id_codice(id_fiscale: str, paese: str) -> str:
    codice = re.sub(r"[^A-Za-z0-9]", "", id_fiscale).upper()
    if codice.startswith(paese) and len(codice) > len(paese):
        codice = codice[len(paese):]
    return codice or ID_FISCALE_ESTERO_ASSENTE


def nome_allegato(dati: DatiAutofattura) -> str:
    numero = re.sub(r"[^A-Za-z0-9-]+", "-", dati.fattura_originale.numero).strip("-")[:40]
    return f"originale_{numero}.pdf"


def nome_file(cliente: Cliente, progressivo: str) -> str:
    """IT<CF o P.IVA del cliente>_<progressivo>.xml, progressivo max 5 alfanumerici."""
    if not re.fullmatch(r"[A-Za-z0-9]{1,5}", progressivo):
        raise ErroreXML(f"Progressivo '{progressivo}' non valido: massimo 5 caratteri alfanumerici")
    return f"IT{cliente.id_trasmittente}_{progressivo}.xml"


def progressivo_libero(numero_af: int, usati: set[str]) -> str:
    """Numero AF + lettera (50A, poi 50B se il nome è già stato usato, es. dopo uno scarto)."""
    for lettera in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        progressivo = f"{numero_af}{lettera}"
        if len(progressivo) > 5:
            break
        if progressivo.upper() not in usati:
            return progressivo
    raise ErroreXML(f"Nessun progressivo di invio libero per il numero {numero_af}")


def prepara_allegato(pdf: bytes) -> bytes:
    """Ricomprime in scala di grigi a 150 DPI i PDF oltre 800 KB (come allegato.py)."""
    if len(pdf) <= SOGLIA_COMPRESSIONE:
        return pdf
    try:
        import pymupdf
        from PIL import Image
    except ImportError:
        return pdf  # il controllo sui 5 MB in valida() resta comunque
    sorgente = pymupdf.open(stream=pdf, filetype="pdf")
    uscita = pymupdf.open()
    for pagina in sorgente:
        pix = pagina.get_pixmap(dpi=150, colorspace=pymupdf.csGRAY)
        immagine = Image.frombytes("L", (pix.width, pix.height), pix.samples)
        buffer = io.BytesIO()
        immagine.save(buffer, "JPEG", quality=60, optimize=True)
        nuova = uscita.new_page(width=pagina.rect.width, height=pagina.rect.height)
        nuova.insert_image(nuova.rect, stream=buffer.getvalue())
    compresso = uscita.tobytes(garbage=4, deflate=True)
    return compresso if len(compresso) < len(pdf) else pdf


def genera(
    dati: DatiAutofattura,
    cliente: Cliente,
    config: Configurazione,
    pdf_originale: Path,
    progressivo: str,
) -> bytes:
    pdf = Path(pdf_originale).read_bytes()
    if not pdf.startswith(b"%PDF"):
        raise ErroreXML(f"{pdf_originale} non è un PDF")
    allegato = prepara_allegato(pdf)

    radice = etree.Element(
        f"{{{NS_P}}}FatturaElettronica",
        nsmap={"p": NS_P, "ds": NS_DS, "xsi": NS_XSI},
        versione="FPR12",
    )

    # --- Header ---
    header = _sotto(radice, "FatturaElettronicaHeader")
    trasm = _sotto(header, "DatiTrasmissione")
    id_t = _sotto(trasm, "IdTrasmittente")
    _sotto(id_t, "IdPaese", "IT")
    _sotto(id_t, "IdCodice", cliente.id_trasmittente)
    _sotto(trasm, "ProgressivoInvio", progressivo)
    _sotto(trasm, "FormatoTrasmissione", "FPR12")
    _sotto(trasm, "CodiceDestinatario", cliente.codice_destinatario)

    f = dati.fornitore
    cedente = _sotto(header, "CedentePrestatore")
    anag_c = _sotto(cedente, "DatiAnagrafici")
    id_iva_c = _sotto(anag_c, "IdFiscaleIVA")
    _sotto(id_iva_c, "IdPaese", f.paese)
    _sotto(id_iva_c, "IdCodice", _id_codice(f.id_fiscale, f.paese))
    _sotto(_sotto(anag_c, "Anagrafica"), "Denominazione", f.denominazione)
    _sotto(anag_c, "RegimeFiscale", "RF18")
    sede_c = _sotto(cedente, "Sede")
    cap_valido = bool(re.fullmatch(r"\d{5}", f.cap or ""))
    indirizzo = f.indirizzo if cap_valido or not f.cap else f"{f.indirizzo} - CP {f.cap}"
    _sotto(sede_c, "Indirizzo", indirizzo[:60])
    _sotto(sede_c, "CAP", f.cap if cap_valido else "00000")
    _sotto(sede_c, "Comune", f.comune)
    _sotto(sede_c, "Nazione", _nazione(f.paese))

    if dati.tipo_documento == "TD19":
        rf = dati.rappresentante_fiscale
        rappresentante = _sotto(header, "RappresentanteFiscale")
        anag_r = _sotto(rappresentante, "DatiAnagrafici")
        id_iva_r = _sotto(anag_r, "IdFiscaleIVA")
        _sotto(id_iva_r, "IdPaese", rf.id_paese)
        _sotto(id_iva_r, "IdCodice", _id_codice(rf.id_codice, rf.id_paese))
        _sotto(_sotto(anag_r, "Anagrafica"), "Denominazione", rf.denominazione)

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
    _sotto(doc, "Numero", cliente.numero_documento(dati.numero_af, dati.data_documento.year))
    _sotto(doc, "ImportoTotaleDocumento", _importo(dati.totale_eur))

    o = dati.fattura_originale
    causali = [f"{NORMA_TD[dati.tipo_documento]} - Ft. {o.numero} del {o.data:%d/%m/%Y} {f.denominazione}"[:200]]
    if o.divisa != "EUR":
        causali.append(
            f"Importo originale {o.totale_valuta} {o.divisa}, cambio BCE {dati.cambio} del {dati.data_cambio:%d/%m/%Y}"[:200]
        )
    if dati.iva_estera_addebitata:
        causali.append("Imponibile comprensivo dell'IVA addebitata dal fornitore, indetraibile")
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
        if riga.natura:
            _sotto(linea, "Natura", riga.natura)
    for aliquota, natura, imponibile, imposta in dati.riepilogo_iva():
        riep = _sotto(beni, "DatiRiepilogo")
        _sotto(riep, "AliquotaIVA", _importo(aliquota))
        if natura:
            _sotto(riep, "Natura", natura)
        _sotto(riep, "ImponibileImporto", _importo(imponibile))
        _sotto(riep, "Imposta", _importo(imposta))
        if not natura:
            _sotto(riep, "EsigibilitaIVA", "I")
        else:
            _sotto(riep, "RiferimentoNormativo", NATURE_AMMESSE[natura])

    pagamento = _sotto(body, "DatiPagamento")
    _sotto(pagamento, "CondizioniPagamento", "TP02")
    dettaglio = _sotto(pagamento, "DettaglioPagamento")
    _sotto(dettaglio, "ModalitaPagamento", dati.modalita_pagamento)
    _sotto(dettaglio, "DataScadenzaPagamento", o.data.isoformat())
    _sotto(dettaglio, "ImportoPagamento", _importo(dati.totale_eur))

    allegati = _sotto(body, "Allegati")
    _sotto(allegati, "NomeAttachment", nome_allegato(dati))
    _sotto(allegati, "FormatoAttachment", "PDF")
    _sotto(allegati, "DescrizioneAttachment", "Fattura originale del fornitore")
    # base64 su riga singola: Aruba e altri canali scartano il base64 a capo.
    _sotto(allegati, "Attachment", base64.b64encode(allegato).decode("ascii"))

    return etree.tostring(radice, xml_declaration=True, encoding="UTF-8", pretty_print=True)


# --- Validazione ---

def _schema_xsd() -> etree.XMLSchema | None:
    xsd = CARTELLA_SCHEMI / FILE_XSD
    if not xsd.exists():
        return None
    testo = xsd.read_text(encoding="utf-8-sig")
    locale = CARTELLA_SCHEMI / FILE_XMLDSIG
    if locale.exists():
        # Lo schema della firma si legge in locale, non da w3.org.
        testo = re.sub(
            r'schemaLocation="[^"]*xmldsig-core-schema\.xsd"',
            f'schemaLocation="{locale.as_uri()}"',
            testo,
        )
    else:
        testo = re.sub(r"<xs:import[^>]*xmldsig[^>]*/>", "", testo)
        testo = re.sub(
            r'<xs:element ref="ds:Signature"[^/]*/>',
            '<xs:any namespace="##other" processContents="lax" minOccurs="0"/>',
            testo,
        )
    documento = etree.fromstring(testo.encode("utf-8"), base_url=xsd.as_uri())
    return etree.XMLSchema(documento)


def valida(xml: bytes, nome: str | None = None, richiedi_xsd: bool = False) -> list[str]:
    """Restituisce l'elenco degli errori (vuoto se l'XML è valido).

    Oltre allo schema ufficiale, i controlli pratici della skill emersi dagli
    scarti SDI: nome file, CAP, RF18, CC, rappresentante TD19, fatture
    collegate, allegato, totali.
    """
    errori = []
    try:
        radice = etree.fromstring(xml)
    except etree.XMLSyntaxError as e:
        return [f"XML non leggibile: {e}"]

    h = "FatturaElettronicaHeader"
    b = "FatturaElettronicaBody"
    if len(xml) > DIMENSIONE_MASSIMA_FILE:
        errori.append(f"File di {len(xml) / 1024 / 1024:.1f} MB oltre il limite SDI di 5 MB")
    if nome is not None:
        m = re.fullmatch(r"IT([A-Z0-9]{11,16})_([A-Za-z0-9]{1,5})\.xml", nome)
        if not m:
            errori.append(f"Nome file '{nome}' non valido: atteso IT[CF]_[max 5 alfanumerici].xml")
        elif m.group(2) != radice.findtext(f"{h}/DatiTrasmissione/ProgressivoInvio"):
            errori.append("ProgressivoInvio diverso dal progressivo del nome file")
        elif m.group(1) != radice.findtext(f"{h}/DatiTrasmissione/IdTrasmittente/IdCodice"):
            errori.append("IdTrasmittente diverso dal codice nel nome file")

    if radice.findtext(f"{h}/SoggettoEmittente") != "CC":
        errori.append("SoggettoEmittente diverso da CC")
    if radice.findtext(f"{h}/CedentePrestatore/DatiAnagrafici/RegimeFiscale") != "RF18":
        errori.append("RegimeFiscale del cedente diverso da RF18")
    if not re.fullmatch(r"\d{5}", radice.findtext(f"{h}/CedentePrestatore/Sede/CAP") or ""):
        errori.append("CAP del cedente non di 5 cifre: usare 00000")

    tipo = radice.findtext(f"{b}/DatiGenerali/DatiGeneraliDocumento/TipoDocumento")
    paese = radice.findtext(f"{h}/CedentePrestatore/DatiAnagrafici/IdFiscaleIVA/IdPaese")
    if tipo not in ("TD17", "TD18", "TD19"):
        errori.append(f"TipoDocumento {tipo} non previsto")
    if paese == "IT":
        errori.append(f"{tipo} con cedente italiano: lo SDI lo scarterebbe")
    if tipo == "TD19" and radice.find(f"{h}/RappresentanteFiscale") is None:
        errori.append("TD19 senza blocco RappresentanteFiscale")
    if radice.find(f"{b}/DatiGenerali/DatiFattureCollegate") is None:
        errori.append("Mancano i DatiFattureCollegate")

    imponibili = Decimal("0")
    imposte = Decimal("0")
    for riep in radice.iterfind(f"{b}/DatiBeniServizi/DatiRiepilogo"):
        imponibile = Decimal(riep.findtext("ImponibileImporto"))
        imposta = Decimal(riep.findtext("Imposta"))
        aliquota = Decimal(riep.findtext("AliquotaIVA"))
        atteso = (imponibile * aliquota / 100).quantize(Decimal("0.01"))
        if abs(atteso - imposta) > Decimal("0.01"):
            errori.append(f"Imposta {imposta} non coerente con {imponibile} al {aliquota}%")
        imponibili += imponibile
        imposte += imposta
    linee = sum(
        (Decimal(e.text) for e in radice.iterfind(f"{b}/DatiBeniServizi/DettaglioLinee/PrezzoTotale")),
        Decimal("0"),
    )
    if linee != imponibili:
        errori.append(f"Somma delle linee {linee} diversa dagli imponibili {imponibili}")
    dichiarato = radice.findtext(f"{b}/DatiGenerali/DatiGeneraliDocumento/ImportoTotaleDocumento")
    if dichiarato is not None and Decimal(dichiarato) != imponibili + imposte:
        errori.append(f"ImportoTotaleDocumento {dichiarato} diverso da {imponibili + imposte}")

    allegati = radice.findall(f"{b}/Allegati")
    if not allegati:
        errori.append("Manca il PDF originale allegato")
    for allegato in allegati:
        nome_allegato_ = allegato.findtext("NomeAttachment") or ""
        if not re.search(r"\.(pdf|jpe?g|png)$", nome_allegato_, re.I):
            errori.append(f"NomeAttachment '{nome_allegato_}' senza estensione")
        contenuto = allegato.findtext("Attachment") or ""
        if "\n" in contenuto.strip():
            errori.append("Base64 dell'allegato su più righe")
        try:
            if not base64.b64decode(contenuto, validate=True).startswith(b"%PDF"):
                errori.append("L'allegato non è un PDF")
        except ValueError:
            errori.append("Allegato non in base64")

    schema = _schema_xsd()
    if schema is None:
        if richiedi_xsd:
            errori.append(f"Schema XSD assente: copiare {FILE_XSD} in {CARTELLA_SCHEMI}")
    elif not schema.validate(radice):
        errori.extend(f"XSD riga {e.line}: {e.message}" for e in schema.error_log)
    return errori
