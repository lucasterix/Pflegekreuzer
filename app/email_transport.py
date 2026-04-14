# app/email_transport.py

import smtplib
from email.message import EmailMessage
from pathlib import Path
from datetime import datetime

from .models.settings import Einstellungen


def _file_info_for_body(path: Path, auf_timestamp: datetime | None = None) -> str:
    """
    Erzeugt den Body-Eintrag: <Name>, <Size>, <JJJJMMTT:HHMMSS>
    Wenn auf_timestamp gesetzt ist, wird dieses Datum/Zeitfeld genutzt
    (z.B. aus AUF 116-129). Sonst Dateisystemzeit.
    """
    size = path.stat().st_size
    if auf_timestamp:
        ts = auf_timestamp.strftime("%Y%m%d:%H%M%S")
    else:
        mtime = datetime.fromtimestamp(path.stat().st_mtime)
        ts = mtime.strftime("%Y%m%d:%H%M%S")
    return f"{path.name}, {size}, {ts}"


def send_datenaustausch_mail(
    cfg: Einstellungen,
    sender_ik: str,
    empfaenger_email: str,
    auf_path: Path,
    nutzdaten_path: Path,
    auf_erstellzeit: datetime | None = None,
):
    """
    Versendet eine E-Mail gemäß Anlage 7:
      - Betreff = IK des Absenders
      - genau 2 Anhänge: AUF + Nutzdaten
      - Body mit Dateiinformationen + Kontaktdaten
    """

    if not cfg.smtp_server or not cfg.email_absender:
        raise RuntimeError("SMTP-Server oder Absender-E-Mail in der Konfiguration fehlt.")

    msg = EmailMessage()
    msg["From"] = cfg.email_absender
    msg["To"] = empfaenger_email
    msg["Subject"] = sender_ik  # IK des Absenders, keine Umlaute

    # Body gemäß Anlage 7
    lines: list[str] = []

    # 1. AUF
    lines.append(_file_info_for_body(auf_path, auf_erstellzeit))
    # 2. Nutzdaten
    lines.append(_file_info_for_body(nutzdaten_path, auf_erstellzeit))

    # optionale Kontaktdaten
    firma = cfg.name or "Leistungserbringer"
    lines.append(firma)
    if cfg.kontakt_person:
        lines.append(cfg.kontakt_person)
    if cfg.email_absender:
        lines.append(cfg.email_absender)
    if cfg.kontakt_telefon:
        lines.append(cfg.kontakt_telefon)
    if cfg.kontakt_fax:
        lines.append(cfg.kontakt_fax)

    msg.set_content("\r\n".join(lines))

    # Anhänge (genau zwei)
    for path in (auf_path, nutzdaten_path):
        with path.open("rb") as f:
            data = f.read()
        msg.add_attachment(
            data,
            maintype="application",
            subtype="octet-stream",
            filename=path.name,
        )

    # SMTP versenden
    use_tls = bool(getattr(cfg, "smtp_use_tls", True))
    server = cfg.smtp_server
    port = cfg.smtp_port or (587 if use_tls else 25)

    if use_tls:
        with smtplib.SMTP(server, port) as s:
            s.starttls()
            if cfg.smtp_user and cfg.smtp_password:
                s.login(cfg.smtp_user, cfg.smtp_password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(server, port) as s:
            if cfg.smtp_user and cfg.smtp_password:
                s.login(cfg.smtp_user, cfg.smtp_password)
            s.send_message(msg)