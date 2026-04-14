# app/pdf_pflegeantrag.py

from io import BytesIO
from datetime import datetime

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from PyPDF2 import PdfReader, PdfWriter  # PyPDF2 nutzt du ohnehin schon


def mmx(x: float) -> float:
    return x * mm


def mmy(y: float) -> float:
    return y * mm


def _merge_overlay(template_path: str, overlay_buf: BytesIO) -> BytesIO:
    """
    Legt das Overlay (Text) über die vorhandene PDF-Vorlage.

    template_path: Pfad zu deiner Vorlage (z.B. "app/static/Pflegeantrag.pdf")
    overlay_buf:   PDF mit den gezeichneten Texten (ReportLab)
    """
    overlay_buf.seek(0)

    base_reader = PdfReader(template_path)
    overlay_reader = PdfReader(overlay_buf)
    writer = PdfWriter()

    for i, base_page in enumerate(base_reader.pages):
        if i < len(overlay_reader.pages):
            overlay_page = overlay_reader.pages[i]
            # Text-Overlay auf die Basis-Seite legen
            base_page.merge_page(overlay_page)
        writer.add_page(base_page)

    out = BytesIO()
    writer.write(out)
    out.seek(0)
    return out


def render_pflegeantrag(template_path: str, data: dict) -> BytesIO:
    """
    Erzeugt ein ausgefülltes PDF auf Basis der Vorlage 'Pflegeantrag.pdf'.

    Erwartete Keys in data (an dein Patient-Objekt angepasst):
      - name:           "Nachname, Vorname"
      - geburtsdatum:   "DD.MM.YYYY" (String)
      - versichertennr: KV-Nummer
      - anschrift:      Straße, PLZ, Ort (eine Zeile reicht erst mal)
      - pflegekasse:    Name der Pflegekasse
    """

    # Overlay-Canvas
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)

    BASE_FONT = "Courier"
    BASE_SIZE = 11
    c.setFont(BASE_FONT, BASE_SIZE)

    name = (data.get("name") or "").strip()
    geburtsdatum = (data.get("geburtsdatum") or "").strip()
    versichertennr = (data.get("versichertennr") or "").strip()
    anschrift = (
        data.get("anschrift")
        or data.get("adresse")
        or ""
    ).strip()
    pflegekasse = (data.get("pflegekasse") or "").strip()

    # Die Koordinaten passen zur gelieferten Vorlage:
    # Erste Zeile: Name | Geburtsdatum | Versichertennummer
    c.drawString(mmx(13), mmy(263), name)
    c.drawString(mmx(63), mmy(263), geburtsdatum)
    c.drawString(mmx(101), mmy(263), versichertennr)

    # Zweite Zeile: Anschrift | Pflegekasse
    c.drawString(mmx(13), mmy(248), anschrift)
    c.drawString(mmx(111), mmy(248), pflegekasse)

    c.showPage()
    c.save()
    buf.seek(0)

    return _merge_overlay(template_path, buf)