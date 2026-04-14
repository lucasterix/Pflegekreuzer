# app/pdf_signature.py
from io import BytesIO
from typing import Optional
from pdf2image import convert_from_path
from PIL import Image


def extract_signature_from_pflegeantrag(
    pdf_path: str,
    *,
    dpi: int = 300,
    box: Optional[tuple[int, int, int, int]] = None,
) -> BytesIO:
    """
    Extrahiert die Unterschrift aus der ersten Seite eines unterschriebenen Pflegeantrags-PDF.

    Args:
        pdf_path: Pfad zur unterschriebenen Antrag-PDF.
        dpi: Auflösung für das Rendern der PDF-Seite (Standard: 300).
        box: Tuple (left, upper, right, lower) in Pixeln – Bereich für die Signatur.
             Wenn None, wird ein Standardbereich (rechts unten) verwendet.

    Returns:
        BytesIO-Objekt mit der PNG-Unterschrift (bereit für ReportLab ImageReader).
    """
    # ---- PDF -> PIL Image (erste Seite) ----
    pages = convert_from_path(pdf_path, dpi=dpi, first_page=1, last_page=1)
    if not pages:
        raise ValueError("Keine Seiten im PDF gefunden.")

    page: Image.Image = pages[0]
    width, height = page.size

    # ---- Crop-Bereich bestimmen ----
    if box is None:
        # 🧭 Diesen Bereich bei Bedarf anpassen
        left = int(width * 0.35)
        right = int(width * 0.90)
        upper = int(height * 0.80)  # oben
        lower = int(height * 0.88)  # unten
        box = (left, upper, right, lower)

    # ---- Croppen ----
    signature_img = page.crop(box)

    # ---- In Memory als PNG speichern ----
    output = BytesIO()
    signature_img.save(output, format="PNG")
    output.seek(0)

    return output