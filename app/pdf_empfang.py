# app/pdf_empfang.py
from io import BytesIO
from decimal import Decimal
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from pypdf import PdfReader, PdfWriter, PageObject

def mmx(x): return x * mm
def mmy(y): return y * mm


def _merge_overlay(template_path: str, overlay_buf: BytesIO) -> BytesIO:
    """Fügt Overlay (Empfangstext) über die PDF-Vorlage."""
    base_reader = PdfReader(template_path)
    overlay_reader = PdfReader(overlay_buf)
    writer = PdfWriter()
    for i, page in enumerate(base_reader.pages):
        base: PageObject = page
        if i < len(overlay_reader.pages):
            base.merge_page(overlay_reader.pages[i])
        writer.add_page(base)
    out = BytesIO()
    writer.write(out)
    out.seek(0)
    return out


def render_empfang(template_path: str, patient: dict, produkte: list[dict]):
    """
    Erzeugt eine Empfangsbestätigung (PDF Overlay) für die übergebenen Produkte.
    Erwartet:
        patient = {
            "name": str,
            "versicherten_nr": str,
            "kasse": str,
            "versorgungsmonat": str,
        }
        produkte = [
            {"name": str, "qty": int, "net": Decimal, "gross": Decimal}, ...
        ]
    """
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)

    # Kopfbereich
    c.setFont("Helvetica-Bold", 12)
    c.drawString(mmx(25), mmy(265), "Empfangsbestätigung")

    c.setFont("Helvetica", 10)
    c.drawString(mmx(25), mmy(255), f"Patient: {patient.get('name', '')}")
    c.drawString(mmx(25), mmy(249), f"Versichertennr.: {patient.get('versicherten_nr', '')}")
    c.drawString(mmx(25), mmy(243), f"Pflegekasse: {patient.get('kasse', '')}")
    c.drawString(mmx(25), mmy(237), f"Versorgungsmonat: {patient.get('versorgungsmonat', '')}")

    # Tabelle
    y = 225
    c.setFont("Courier-Bold", 10)
    c.drawString(mmx(25), mmy(y), "Produkt")
    c.drawString(mmx(115), mmy(y), "Menge")
    c.drawRightString(mmx(160), mmy(y), "Netto")
    c.drawRightString(mmx(185), mmy(y), "Brutto")

    c.setFont("Courier", 10)
    y -= 6
    total_net = Decimal("0.00")
    total_gross = Decimal("0.00")

    for p in produkte:
        name = p.get("name", "")
        qty = p.get("qty", 0)
        net = Decimal(p.get("net", 0))
        gross = Decimal(p.get("gross", 0))
        total_net += net
        total_gross += gross

        c.drawString(mmx(25), mmy(y), name[:45])
        c.drawString(mmx(115), mmy(y), str(qty))
        c.drawRightString(mmx(160), mmy(y), f"{net:.2f}€")
        c.drawRightString(mmx(185), mmy(y), f"{gross:.2f}€")
        y -= 6

    # Summen
    c.setFont("Courier-Bold", 10)
    y -= 4
    c.drawRightString(mmx(160), mmy(y), f"{total_net:.2f}€")
    c.drawRightString(mmx(185), mmy(y), f"{total_gross:.2f}€")
    c.drawString(mmx(25), mmy(y), "Summe gesamt:")

    # Unterschriftsfeld
    c.setFont("Helvetica", 10)
    y -= 20
    c.drawString(mmx(25), mmy(y), "Ich bestätige den Empfang der oben genannten Hilfsmittel.")
    y -= 15
    c.line(mmx(25), mmy(y), mmx(100), mmy(y))
    c.drawString(mmx(25), mmy(y - 5), "Datum, Unterschrift Pflegebedürftiger/Angehöriger")

    c.showPage()
    c.save()
    buf.seek(0)
    return _merge_overlay(template_path, buf)