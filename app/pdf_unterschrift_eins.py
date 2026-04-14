# app/pdf_unterschrift_eins.py
from io import BytesIO
from datetime import datetime
from reportlab.pdfgen import canvas
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from pypdf import PdfReader, PdfWriter, PageObject


def mmx(x: float) -> float:
    return x * mm


def mmy(y: float) -> float:
    return y * mm


def _merge_overlay(template_path: str, overlay_buf: BytesIO) -> BytesIO:
    """Legt das Overlay (Text + Unterschrift) über die vorhandene PDF-Vorlage."""
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


# ==========================
# Helfer: Datum + Spacing
# ==========================

def _normalize_datum_numeric(raw: str) -> str:
    """Wandelt Datumsangaben in Format DDMMYYYY um (rein numerisch)."""
    if not raw:
        return ""

    s = raw.strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y.%m.%d", "%d-%m-%Y"):
        try:
            dt = datetime.strptime(s, fmt)
            return f"{dt.day:02d}{dt.month:02d}{dt.year:04d}"
        except ValueError:
            pass

    only_digits = "".join(ch for ch in s if ch.isdigit())
    if len(only_digits) == 8:
        return only_digits
    return only_digits[:8]


def _draw_spaced_text_mm(
    c: Canvas,
    x_mm: float,
    y_mm: float,
    text: str,
    step_mm: float = 3.0,
    font: str = "Courier",
    size: int = 11,
    max_len: int | None = None,
) -> None:
    """Zeichnet Text Zeichen für Zeichen mit festem Abstand (z. B. für Datumsfelder)."""
    if not text:
        return

    c.saveState()
    c.setFont(font, size)

    step = step_mm * mm
    n = len(text) if max_len is None else min(max_len, len(text))

    x0 = mmx(x_mm)
    y0 = mmy(y_mm)

    for i in range(n):
        c.drawString(x0 + i * step, y0, text[i])

    c.restoreState()


# ==========================
# Konfigurierbare Koordinaten
# ==========================

# Datum-Felder
DATE1_X_MM = 91.0
DATE1_Y_MM = 167.0
DATE1_STEP_MM = 5.4

DATE2_X_MM = 28.5
DATE2_Y_MM = 107.0
DATE2_STEP_MM = 5.4

# Mitarbeitername
MITARBEITER_X_MM = 88.0
MITARBEITER_Y_MM = 158.0

# Unterschrift (Feld unten rechts)
SIG_X_MM = 92.0   # Position von links
SIG_Y_MM = 175.0  # Position von oben (!) — wird intern korrigiert
SIG_W_MM = 60.0   # Breite
SIG_H_MM = 20.0   # Höhe


def render_unterschrift_eins(template_path: str, data: dict) -> BytesIO:
    """
    Erstellt das PDF "unterschrift_eins.pdf" mit eingedrucktem Datum,
    Mitarbeitername und (optional) Signaturbild.
    """
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setFont("Courier", 11)

    beratung_datum_raw = (data.get("beratung_datum") or "").strip()
    beratung_datum2_raw = (data.get("beratung_datum_2") or "").strip()
    beratung_mitarbeiter = (data.get("beratung_mitarbeiter") or "").strip()
    name = (data.get("name") or "").strip()

    # Datum normieren
    datum1 = _normalize_datum_numeric(beratung_datum_raw)
    datum2 = _normalize_datum_numeric(beratung_datum2_raw or beratung_datum_raw)

    # === Datum 1 ===
    if datum1:
        _draw_spaced_text_mm(
            c,
            x_mm=DATE1_X_MM,
            y_mm=DATE1_Y_MM,
            text=datum1,
            step_mm=DATE1_STEP_MM,
            font="Courier",
            size=11,
            max_len=8,
        )

    # === Datum 2 ===
    if datum2:
        _draw_spaced_text_mm(
            c,
            x_mm=DATE2_X_MM,
            y_mm=DATE2_Y_MM,
            text=datum2,
            step_mm=DATE2_STEP_MM,
            font="Courier",
            size=11,
            max_len=8,
        )

    # === Mitarbeitername ===
    if beratung_mitarbeiter:
        c.drawString(mmx(MITARBEITER_X_MM), mmy(MITARBEITER_Y_MM), beratung_mitarbeiter)

    # === Unterschrift ===
    signature_png = data.get("signature_png")
    if signature_png:
        img_reader = ImageReader(signature_png)
        page_width, page_height = A4

        sig_w = mmx(SIG_W_MM)
        sig_h = mmy(SIG_H_MM)
        sig_x = mmx(SIG_X_MM)
        # Koordinatenkorrektur: ReportLab zählt von unten, unsere Werte sind „von oben“
        sig_y = page_height - mmy(SIG_Y_MM) - sig_h

        # Signaturbild einfügen
        c.drawImage(
            img_reader,
            sig_x,
            sig_y,
            width=sig_w,
            height=sig_h,
            preserveAspectRatio=True,
            mask="auto",
        )

    # Optional: Patientenname irgendwo einfügen
    # if name:
    #     c.drawString(mmx(30), mmy(180), name)

    c.showPage()
    c.save()
    buf.seek(0)

    return _merge_overlay(template_path, buf)
