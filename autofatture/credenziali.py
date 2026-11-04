"""Credenziali cifrate nel Gestore credenziali di Windows (tramite keyring).

Si inseriscono una volta sul server con `python -m autofatture imposta-credenziali`:
i caratteri non vengono mostrati e le credenziali non finiscono mai in file,
log, chat o nel registro.
"""

from __future__ import annotations

import getpass

import keyring

SERVIZIO = "autofatture-studio-rota"

VOCI = {
    "entratel_utente": "Entratel - nome utente",
    "entratel_password": "Entratel - password",
    "entratel_pin": "Entratel - PIN",
    "todoist_token": "Todoist - token API",
    "smtp_password": "Posta in uscita - password",
}


class CredenzialeMancante(Exception):
    pass


def leggi(nome: str) -> str:
    valore = keyring.get_password(SERVIZIO, nome)
    if not valore:
        raise CredenzialeMancante(
            f"Manca la credenziale '{VOCI.get(nome, nome)}': lanciare "
            "IMPOSTA_CREDENZIALI.bat sul server"
        )
    return valore


def imposta_interattivo(nomi: list[str] | None = None) -> None:
    for nome in nomi or list(VOCI):
        presente = keyring.get_password(SERVIZIO, nome) is not None
        stato = " (già impostata, Invio per lasciarla)" if presente else ""
        valore = getpass.getpass(f"{VOCI[nome]}{stato}: ")
        if valore:
            keyring.set_password(SERVIZIO, nome, valore)
    print("Credenziali salvate nel Gestore credenziali di Windows.")
