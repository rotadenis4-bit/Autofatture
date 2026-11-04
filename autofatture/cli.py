"""Comandi: python -m autofatture <comando>."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from . import configurazione, credenziali, elaborazione, notifiche, registro as reg, verifica_pdf


def _numeri_in_coda(config, cliente_id: str, anno: int) -> list[int]:
    numeri = []
    coda = Path(config.percorsi["coda"])
    if not coda.exists():
        return numeri
    for cartella in coda.iterdir():
        file_dati = cartella / elaborazione.FILE_DATI
        if not file_dati.exists():
            continue
        try:
            d = json.loads(file_dati.read_text(encoding="utf-8"))
            if d.get("cliente_id") == cliente_id and str(d.get("data_documento", "")).startswith(str(anno)):
                numeri.append(int(d["numero_af"]))
        except (ValueError, KeyError, TypeError):
            continue
    return numeri


def cmd_clienti(config, args) -> int:
    anno = args.anno or date.today().year
    registro = reg.Registro(config)
    elenco = []
    for c in config.clienti.values():
        ultimo = registro.ultimo_numero(c.id, anno)
        in_coda = _numeri_in_coda(config, c.id, anno)
        prossimo = max([ultimo] + in_coda) + 1
        elenco.append({
            "id": c.id,
            "denominazione": c.denominazione,
            "partita_iva": c.partita_iva,
            "anno": anno,
            "ultimo_af_registro": ultimo,
            "in_coda": sorted(in_coda),
            "prossimo_af": prossimo,
            "prossimo_numero_documento": c.numero_documento(prossimo, anno),
            "anagrafica_da_completare": c.campi_da_completare(),
        })
    print(json.dumps(elenco, ensure_ascii=False, indent=2))
    return 0


def cmd_verifica_pdf(config, args) -> int:
    esito = verifica_pdf.verifica(Path(args.pdf))
    print(json.dumps({"sicuro": esito.sicuro, "pagine": esito.pagine, "problemi": esito.problemi}, ensure_ascii=False))
    return 0 if esito.sicuro else 2


def cmd_anteprima(config, args) -> int:
    try:
        anteprima = elaborazione.prepara(config, Path(args.dati), Path(args.pdf))
    except elaborazione.Blocco as e:
        print(f"BLOCCATA: {e}")
        return 2
    print(anteprima.riepilogo(config))
    if anteprima.xml and args.xml:
        Path(args.xml).write_bytes(anteprima.xml)
        print(f"\nXML di prova (non inviato): {args.xml}")
    return 2 if anteprima.errori else 0


def cmd_accoda(config, args) -> int:
    dati = json.loads(Path(args.dati).read_text(encoding="utf-8"))
    anno = int(str(dati.get("data_documento", "0000"))[:4])
    if int(dati.get("numero_af", 0)) in _numeri_in_coda(config, dati.get("cliente_id"), anno):
        print("BLOCCATA: questo numero AF è già in coda per il cliente; attendere l'elaborazione del server (15 minuti)")
        return 2
    try:
        cartella = elaborazione.accoda(config, Path(args.dati), Path(args.pdf))
    except elaborazione.Blocco as e:
        print(f"BLOCCATA: {e}")
        return 2
    print(f"In coda: {cartella}")
    return 0


def cmd_elabora(config, args) -> int:
    caricate = elaborazione.elabora(config)
    print(f"Autofatture caricate in questo giro: {caricate}")
    return 0


def cmd_riepilogo(config, args) -> int:
    if args.mese:
        anno, mese = (int(x) for x in args.mese.split("-"))
    else:
        anno, mese = elaborazione.mese_precedente()
    oggetto, testo = elaborazione.riepilogo(config, anno, mese)
    if args.invia:
        notifiche.invia_mail(config, oggetto, testo)
        print(f"Riepilogo inviato a {', '.join(config.email.get('destinatari') or ['info@studiorota.eu'])}")
    else:
        print(oggetto)
        print()
        print(testo)
    return 0


def cmd_imposta_credenziali(config, args) -> int:
    sconosciute = [v for v in args.voci if v not in credenziali.VOCI]
    if sconosciute:
        print(f"Voci sconosciute: {', '.join(sconosciute)}", file=sys.stderr)
        return 1
    credenziali.imposta_interattivo(args.voci or None)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="autofatture", description="Autofatture TD17/TD18/TD19 Studio Rota")
    parser.add_argument("--config", help="percorso di config.yaml")
    sotto = parser.add_subparsers(dest="comando", required=True)

    p = sotto.add_parser("clienti", help="clienti autorizzati e prossimo numero AF")
    p.add_argument("--anno", type=int)
    p.set_defaults(funzione=cmd_clienti)

    p = sotto.add_parser("verifica-pdf", help="controllo del PDF prima della lettura")
    p.add_argument("pdf")
    p.set_defaults(funzione=cmd_verifica_pdf)

    p = sotto.add_parser("anteprima", help="controlli e XML di prova, senza accodare")
    p.add_argument("dati")
    p.add_argument("pdf")
    p.add_argument("--xml", help="dove salvare l'XML di prova")
    p.set_defaults(funzione=cmd_anteprima)

    p = sotto.add_parser("accoda", help="manda l'autofattura al server")
    p.add_argument("dati")
    p.add_argument("pdf")
    p.set_defaults(funzione=cmd_accoda)

    p = sotto.add_parser("elabora", help="(server) elabora la coda e controlla gli esiti")
    p.set_defaults(funzione=cmd_elabora)

    p = sotto.add_parser("riepilogo", help="riepilogo del mese (predefinito: mese precedente)")
    p.add_argument("--mese", help="AAAA-MM")
    p.add_argument("--invia", action="store_true", help="invia la mail invece di stamparla")
    p.set_defaults(funzione=cmd_riepilogo)

    p = sotto.add_parser("imposta-credenziali", help="(server) salva le credenziali cifrate")
    p.add_argument("voci", nargs="*", help=f"una o più tra: {', '.join(credenziali.VOCI)} (predefinito: tutte)")
    p.set_defaults(funzione=cmd_imposta_credenziali)

    args = parser.parse_args(argv)
    try:
        config = configurazione.carica(args.config)
    except configurazione.ErroreConfigurazione as e:
        print(f"ERRORE: {e}", file=sys.stderr)
        return 1
    return args.funzione(config, args)
