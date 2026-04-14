# app/pdf_antrag_kasse.py

import re
from io import BytesIO
from decimal import Decimal

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from pypdf import PdfReader, PdfWriter, PageObject


def mmx(x: float) -> float:
    return x * mm


def mmy(y: float) -> float:
    return y * mm


def _merge_overlay(template_path: str, overlay_buf: BytesIO) -> BytesIO:
    """Legt das Overlay (Text) über die vorhandene PDF-Vorlage."""
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


# ---------------- Mengen-Handling ----------------

_NUMERIC_RE = re.compile(r"^\s*\d+\s*$")


def _as_qty(v) -> int:
    """Nur echte Zahlen; bool => 0."""
    if isinstance(v, bool):
        return 0
    if isinstance(v, int):
        return int(v)
    if isinstance(v, Decimal):
        return int(v)
    if isinstance(v, str) and _NUMERIC_RE.match(v):
        return int(v.strip())
    return 0


# Aliasse: kurze Namen (Form/Products) -> Packungsgrößen-Namen
ALIASES = {
    "Schürzen (Einmalgebrauch)": "Schutzschürzen (Einmalgebrauch)",
    "Schürzen (Wiederverwendbar)": "Schutzschürzen (Wiederverwendbar)",
}


def _alias_for_pack(name: str) -> str:
    return ALIASES.get(name, name)


# Packungsgrößen (was 1 „logische Packung“ in Stück bedeutet)
PACK_SIZE = {
    "Saugende Bettschutzeinlage (Einmalgebrauch)": 25,
    "Saugende Bettschutzeinlage (Wiederverwendbar)": 1,
    "Fingerlinge": 100,
    "Einmalhandschuhe": 100,
    "Medizinische Gesichtsmaske": 50,
    "FFP2-Gesichtsmaske": 20,
    "Schutzservietten (Einmalgebrauch)": 100,
    "Händedesinfektionsmittel": 5,
    "Flächendesinfektionsmittel": 5,
    "Händedesinfektionstücher": 60,
    "Flächendesinfektionstücher": 100,
    # Schürzen via Alias + direkte Einträge:
    "Schutzschürzen (Einmalgebrauch)": 10,
    "Schutzschürzen (Wiederverwendbar)": 1,
    "Schürzen (Einmalgebrauch)": 10,
    "Schürzen (Wiederverwendbar)": 1,
}


def _display_qty_from_pack(name: str, logical_qty: int) -> int:
    """logische Packungen -> Stückzahl gemäß PACK_SIZE."""
    if logical_qty <= 0:
        return 0
    factor = PACK_SIZE.get(_alias_for_pack(name))
    return logical_qty * factor if factor else logical_qty


# ---------------- Rendering-Helper ----------------

def _draw_fixed_advance_text(
    c: canvas.Canvas,
    x: float,
    y: float,
    text: str,
    step_mm: float = 3.8,
    font: str = "Courier",
    size: int = 12,
    max_len: int | None = None,
):
    """Monospace-Kästchen (für DOB/VSNR)."""
    if not text:
        return
    c.saveState()
    c.setFont(font, size)
    step = step_mm * mm
    n = len(text) if max_len is None else min(max_len, len(text))
    for i in range(n):
        c.drawString(x + i * step, y, text[i])
    c.restoreState()


def _swap_name_order(full_name: str) -> str:
    """'Vorname Nachname' -> 'Nachname Vorname' (oder Komma entfernen bei 'Nachname, Vorname')."""
    if not full_name:
        return ""
    s = " ".join(full_name.strip().split())
    if "," in s:
        a = [p.strip() for p in s.split(",", 1)]
        if len(a) == 2 and a[0] and a[1]:
            return f"{a[0]} {a[1]}"
    parts = s.split(" ")
    return f"{parts[-1]} {' '.join(parts[:-1])}" if len(parts) >= 2 else s


# ---------------- Anlage 2: Checkboxen + Mengen-Koordinaten ----------------

# Checkboxen (PG 54 „zum Verbrauch“, PG 51 „nicht zum Verbrauch“)
ANL2_CHECKBOX_POS = {
    "non_reusable": {"x_mm": 25.0, "y_mm": 212.0},  # oben bei PG 54
    "reusable":     {"x_mm": 25.0, "y_mm": 72.0},   # unten bei PG 51
}


def update_checkbox_coord(which: str, *, x_mm: float | None = None, y_mm: float | None = None) -> None:
    """Optional Koordinaten der Checkboxen anpassbar."""
    if which in ANL2_CHECKBOX_POS:
        if x_mm is not None:
            ANL2_CHECKBOX_POS[which]["x_mm"] = float(x_mm)
        if y_mm is not None:
            ANL2_CHECKBOX_POS[which]["y_mm"] = float(y_mm)


# Mengen-Positionen je Produkt (links ausgerichtete Zahl)
ANL2_QTY_X_MM = 151.0
ANL2_QTY_Y = {
    "Saugende Bettschutzeinlage (Einmalgebrauch)": 174.0,
    "Fingerlinge":                                   167.0,
    "Einmalhandschuhe":                              157.0,
    "Medizinische Gesichtsmaske":                    148.0,
    "FFP2-Gesichtsmaske":                            140.0,
    "Schürzen (Einmalgebrauch)":                     131.0,
    "Schürzen (Wiederverwendbar)":                   122.0,
    "Schutzservietten (Einmalgebrauch)":             113.0,
    "Händedesinfektionsmittel":                      104.0,
    "Flächendesinfektionsmittel":                     95.0,
    "Händedesinfektionstücher":                       86.0,
    "Flächendesinfektionstücher":                     81.0,
    "Saugende Bettschutzeinlage (Wiederverwendbar)":  43.0,
}

_ANL2_QTY_X_OVERRIDE: dict[str, float] = {}


def update_anlage2_coord(product_name: str, *, x_mm: float | None = None, y_mm: float | None = None) -> None:
    """Optional: Koordinaten im laufenden Betrieb anpassbar."""
    if y_mm is not None:
        ANL2_QTY_Y[product_name] = float(y_mm)
    if x_mm is not None:
        _ANL2_QTY_X_OVERRIDE[product_name] = float(x_mm)


def _qty_xy_for(product_name: str) -> tuple[float, float]:
    x_mm = _ANL2_QTY_X_OVERRIDE.get(product_name, ANL2_QTY_X_MM)
    y_mm = ANL2_QTY_Y.get(
        product_name,
        ANL2_QTY_Y.get("Saugende Bettschutzeinlage (Einmalgebrauch)", 174.0),
    )
    return mmx(x_mm), mmy(y_mm)


QTY_CHARSPACE_MM = 3


def render_antrag_kasse(template_path: str, data: dict) -> BytesIO:
    """
    Overlay für antrag.pdf (Anlage 2).

    Erwartet in data:
      - name
      - geburtsdatum  (z.B. '1950-02-01' oder '01.02.1950')
      - versichertennr
      - anschrift / adresse
      - pflegekasse
      - produkte: dict {Produktname -> logische Menge in Packungen}
      - beratung_datum (optional, 'YYYY-MM-DD')
      - beratung_mitarbeiter (optional)
    """
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)

    BASE_FONT = "Courier"
    BASE_SIZE = 10
    c.setFont(BASE_FONT, BASE_SIZE)

    name = data.get("name", "") or ""
    geb_raw = data.get("geburtsdatum", "") or ""
    vsnr = data.get("versichertennr", "") or ""
    anschrift = data.get("anschrift") or data.get("adresse") or ""
    pflegekasse = data.get("pflegekasse", "") or ""
    produkte = data.get("produkte") or {}
    beratung_datum = data.get("beratung_datum") or ""
    beratung_mitarbeiter = data.get("beratung_mitarbeiter") or ""

    # Name in "Nachname Vorname"
    c.drawString(mmx(25), mmy(248), _swap_name_order(name))

    # Geburtsdatum normalisieren -> DDMMYYYY für Kästchen
    dob_clean = re.sub(r"\D", "", geb_raw)
    if len(dob_clean) == 8 and "-" not in geb_raw and "." not in geb_raw:
        # evtl. 'YYYYMMDD' -> 'DDMMYYYY'
        dob_clean = dob_clean[6:8] + dob_clean[4:6] + dob_clean[0:4]

    _draw_fixed_advance_text(
        c,
        mmx(73),
        mmy(251),
        dob_clean[:8],
        step_mm=5.5,
        font=BASE_FONT,
        size=12.5,
        max_len=8,
    )
    _draw_fixed_advance_text(
        c,
        mmx(135),
        mmy(251),
        vsnr,
        step_mm=6.0,
        font=BASE_FONT,
        size=12.5,
    )

    # Anschrift & Pflegekasse
    c.setFont(BASE_FONT, BASE_SIZE)
    c.drawString(mmx(25), mmy(234), anschrift)
    c.drawString(mmx(138), mmy(234), pflegekasse)

    # ---------------- Checkboxen PG 54 / PG 51 ----------------
    REUSABLE_KEY = "Saugende Bettschutzeinlage (Wiederverwendbar)"

    has_pg54 = any(
        (name_prod != REUSABLE_KEY) and _as_qty(qty) > 0
        for name_prod, qty in produkte.items()
    )
    has_pg51 = _as_qty(produkte.get(REUSABLE_KEY, 0)) > 0

    cx1 = mmx(ANL2_CHECKBOX_POS["non_reusable"]["x_mm"])
    cy1 = mmy(ANL2_CHECKBOX_POS["non_reusable"]["y_mm"])
    cx2 = mmx(ANL2_CHECKBOX_POS["reusable"]["x_mm"])
    cy2 = mmy(ANL2_CHECKBOX_POS["reusable"]["y_mm"])

    if has_pg54:
        c.drawString(cx1, cy1, "X")
    if has_pg51:
        c.drawString(cx2, cy2, "X")

    # ---------------- Mengen in Tabelle ----------------
    c.setFont(BASE_FONT, 12)
    for name_prod, logical_v in produkte.items():
        logical_qty = _as_qty(logical_v)
        display_qty = _display_qty_from_pack(name_prod, logical_qty)
        if display_qty <= 0:
            continue

        x, y = _qty_xy_for(name_prod)
        t = c.beginText()
        t.setTextOrigin(x, y)
        t.setFont(BASE_FONT, 12)
        t.setCharSpace(QTY_CHARSPACE_MM * mm)
        t.textLine(str(display_qty))
        c.drawText(t)

    c.showPage()
    c.save()
    buf.seek(0)

    return _merge_overlay(template_path, buf)
