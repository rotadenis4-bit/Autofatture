"""Task Todoist per i problemi e mail di riepilogo."""

from __future__ import annotations

import json
import smtplib
import urllib.request
from email.message import EmailMessage

from . import credenziali
from .configurazione import Configurazione

URL_TODOIST = "https://api.todoist.com/api/v1/tasks"


def crea_task(config: Configurazione, titolo: str, descrizione: str) -> None:
    impostazioni = config.todoist
    corpo = {"content": titolo[:500], "description": descrizione[:16000]}
    if impostazioni.get("progetto_id"):
        corpo["project_id"] = str(impostazioni["progetto_id"])
    richiesta = urllib.request.Request(
        impostazioni.get("url", URL_TODOIST),
        data=json.dumps(corpo).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {credenziali.leggi('todoist_token')}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(richiesta, timeout=30) as risposta:
        if risposta.status >= 300:
            raise RuntimeError(f"Todoist ha risposto {risposta.status}")


def invia_mail(config: Configurazione, oggetto: str, testo: str, html: str | None = None) -> None:
    e = config.email
    messaggio = EmailMessage()
    messaggio["Subject"] = oggetto
    messaggio["From"] = e["mittente"]
    messaggio["To"] = ", ".join(e.get("destinatari") or ["info@studiorota.eu"])
    messaggio.set_content(testo)
    if html:
        messaggio.add_alternative(html, subtype="html")
    with smtplib.SMTP(e.get("smtp_host", "smtp.office365.com"), int(e.get("smtp_porta", 587)), timeout=60) as s:
        s.starttls()
        s.login(e.get("smtp_utente", e["mittente"]), credenziali.leggi("smtp_password"))
        s.send_message(messaggio)
