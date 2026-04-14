import re
from io import BytesIO
from decimal import Decimal
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from pypdf import PdfReader, PdfWriter, PageObject

# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def mmx(x: float) -> float:
    return x * mm

def mmy(y: float) -> float:
    return y * mm


def _merge_overlay(template_path: str, overlay_buf: BytesIO) -> BytesIO:
    """
    Nimmt ein PDF-Template und ein in-memory erzeugtes Overlay-PDF
    und merged Seite für Seite.
    """
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

# ---------------------------------------------------------------------------
# Zahlen- / Mengen-Handling
# ---------------------------------------------------------------------------

_NUMERIC_RE = re.compile(r"^\s*\d+\s*$")

def _as_qty(v) -> int:
    """Nur echte Zahlen; bool => 0."""
    if isinstance(v, bool):
        return 0
    if isinstance(v, (int, Decimal)):
        return int(v)
    if isinstance(v, str) and _NUMERIC_RE.match(v):
        return int(v.strip())
    return 0


ALIASES = {
    "Schürzen (Einmalgebrauch)": "Schutzschürzen (Einmalgebrauch)",
    "Schürzen (Wiederverwendbar)": "Schutzschürzen (Wiederverwendbar)",
}

def _alias_for_pack(name: str) -> str:
    return ALIASES.get(name, name)


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
    "Schutzschürzen (Einmalgebrauch)": 10,
    "Schutzschürzen (Wiederverwendbar)": 1,
}

def _display_qty_from_pack(name: str, logical_qty: int) -> int:
    """
    Rechnet logische Packungs-Menge (z.B. 1 Packung à 25 Stück)
    in die Stückzahl um.
    """
    if logical_qty <= 0:
        return 0
    factor = PACK_SIZE.get(_alias_for_pack(name))
    return logical_qty * factor if factor else logical_qty


def _eur(d: Decimal | float | int) -> str:
    d = Decimal(str(d))
    s = f"{d:.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return s + "€"

def _as_dec(x) -> Decimal:
    try:
        return x if isinstance(x, Decimal) else Decimal(str(x))
    except Exception:
        return Decimal("0")

# ---------------------------------------------------------------------------
# Layout-Koordinaten für Unterschrift 2
# ---------------------------------------------------------------------------

UNTERSCHRIFT2_XY = {
    "u2_qty_wv":      {"x": 120.0, "y": 222.2, "font": "Courier-Bold", "size": 10},
    "u2_net_wv":      {"x": 161.0, "y": 218.0, "font": "Courier",      "size": 10},
    "u2_gross_wv":    {"x": 183.0, "y": 218.0, "font": "Courier",      "size": 10},
    "u2_total_net":   {"x": 161.0, "y": 212.0, "font": "Courier-Bold", "size": 10},
    "u2_total_gross": {"x": 183.0, "y": 212.0, "font": "Courier-Bold", "size": 10},
}

UNTERSCHRIFT2_ALIGN = {
    "u2_qty_wv": "left",
    "u2_net_wv": "right",
    "u2_gross_wv": "right",
    "u2_total_net": "right",
    "u2_total_gross": "right",
}

UNTERSCHRIFT2_CHECKBOX = {
    "x_mm": 25.0,
    "y_mm": 260.0,
    "char": "X",
    "font": "Courier-Bold",
    "size": 12,
}

# ---------------------------------------------------------------------------
# Helper für Unterschrift 2
# ---------------------------------------------------------------------------

def _u2_xy(field: str) -> tuple[float, float, str, int]:
    cfg = UNTERSCHRIFT2_XY.get(field, {"x": 25.0, "y": 200.0, "font": "Courier", "size": 10})
    return mmx(cfg["x"]), mmy(cfg["y"]), cfg["font"], int(cfg["size"])

def _u2_align(field: str) -> str:
    return UNTERSCHRIFT2_ALIGN.get(field, "left")

def _load_catalog() -> dict:
    """
    Versucht zuerst, einen zentralen Produkt-Katalog zu importieren.
    Fällt zurück auf das lokale PRODUCTS-Dict.
    """
    try:
        from app.models.products import PRODUCTS as CATALOG  # type: ignore
        return CATALOG or {}
    except Exception:
        try:
            from models.products import PRODUCTS as CATALOG  # type: ignore
            return CATALOG or {}
        except Exception:
            return globals().get("PRODUCTS", {}) or {}

# ---------------------------------------------------------------------------
# Renderfunktion mit Signatur-Unterstützung (Unterschrift 2)
# ---------------------------------------------------------------------------

def render_unterschrift_zwei(
    template_path: str,
    data: dict,
    positions: list | None = None,
    total_net: Decimal | None = None,
    total_vat: Decimal | None = None,   # aktuell nicht genutzt, bleibt nur für API-Kompatibilität
    total_gross: Decimal | None = None,
    mwst: Decimal = Decimal("0.19"),
    signature: BytesIO | None = None,
) -> BytesIO:
    """
    Overlay für 'unterschrift_zwei.pdf'.

    Zeichnet:
      - Menge & Zeilensummen für 'Saugende Bettschutzeinlage (Wiederverwendbar)'
      - Gesamtsummen netto/brutto
      - Checkbox (wenn WV-Menge > 0 oder data['u2_checkbox_checked'] = True)
      - optional ein Signatur-Bild (PNG) an definierter Position
    """
    produkte = data.get("produkte", {}) or {}
    WV_KEY = "Saugende Bettschutzeinlage (Wiederverwendbar)"

    # any_selected: gibt es irgendeine Position mit Menge > 0?
    if positions is not None:
        any_selected = any(_as_qty(p.get("qty", 0)) > 0 for p in positions)
    else:
        any_selected = any(_as_qty(v) > 0 for v in produkte.values())

    line_net_wv: Decimal | None = None
    line_gross_wv: Decimal | None = None

    # --- 1) Positionen verarbeiten (wenn 'positions' übergeben wurden – dein Abrechnungsmodell) ---
    # --- 1) Positionen verarbeiten (wenn 'positions' übergeben wurden – aus der DB) ---
    if positions:
        net_sum = Decimal("0")
        gross_sum = Decimal("0")

        for p in positions:
            qty = _as_qty(p.get("qty", 0))

            net_val = _as_dec(p.get("net", 0))
            gross_val = _as_dec(p.get("gross", 0))

            net_sum += net_val
            gross_sum += gross_val

            if p.get("name") == WV_KEY and qty > 0:
                line_net_wv = net_val
                line_gross_wv = gross_val

        if total_net is None:
            total_net = net_sum
        if total_gross is None:
            total_gross = gross_sum

    # --- 2) Fallback: keine 'positions' → Berechnung aus Katalog + data['produkte'] ---
    else:
        catalog = _load_catalog()
        net_sum = Decimal("0")
        vat_sum = Decimal("0")

        for name, qty_raw in produkte.items():
            qty = _as_qty(qty_raw)
            if qty <= 0:
                continue

            info = catalog.get(name) or {}
            unit_price = _as_dec(info.get("price", 0))  # netto je logische Einheit
            line_net = unit_price * qty
            line_vat = line_net * mwst
            line_gross = line_net + line_vat

            net_sum += line_net
            vat_sum += line_vat

            if name == WV_KEY:
                line_net_wv = line_net
                line_gross_wv = line_gross

        if total_net is None:
            total_net = net_sum
        if total_vat is None:
            total_vat = vat_sum
        if total_gross is None:
            total_gross = net_sum + vat_sum

    # --- WV-Menge & Checkbox-Status ---
    logical_qty = _as_qty(produkte.get(WV_KEY, 0))
    display_qty = _display_qty_from_pack(WV_KEY, logical_qty)

    checkbox_checked = data.get("u2_checkbox_checked")
    if checkbox_checked is None:
        checkbox_checked = logical_qty > 0

    # --- PDF erzeugen ---
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)

    def draw(field: str, text: str):
        x, y, f, s = _u2_xy(field)
        c.setFont(f, s)
        if _u2_align(field) == "right":
            c.drawRightString(x, y, text)
        else:
            c.drawString(x, y, text)

    # Checkbox
    if checkbox_checked:
        c.setFont(UNTERSCHRIFT2_CHECKBOX["font"], UNTERSCHRIFT2_CHECKBOX["size"])
        c.drawString(
            mmx(UNTERSCHRIFT2_CHECKBOX["x_mm"]),
            mmy(UNTERSCHRIFT2_CHECKBOX["y_mm"]),
            UNTERSCHRIFT2_CHECKBOX["char"],
        )

    # WV-Menge + WV-Zeile
    if display_qty > 0:
        draw("u2_qty_wv", str(display_qty))
        if line_net_wv is not None:
            draw("u2_net_wv", _eur(line_net_wv))
        if line_gross_wv is not None:
            draw("u2_gross_wv", _eur(line_gross_wv))

    # Gesamtsummen nur zeichnen, wenn überhaupt etwas ausgewählt wurde
    if any_selected:
        if total_net is not None:
            draw("u2_total_net", _eur(total_net))
        if total_gross is not None:
            draw("u2_total_gross", _eur(total_gross))

    # --- Signatur einfügen ---
    if signature is not None:
        try:
            sig_img = ImageReader(signature)
            # Position ggf. anpassen – aktuell eher mittig unten
            c.drawImage(
                sig_img,
                mmx(35),
                mmy(115),
                width=mmx(40),
                preserveAspectRatio=True,
                mask="auto",
            )
        except Exception as e:
            print(f"⚠️ Signatur konnte nicht eingefügt werden: {e}")

    c.showPage()
    c.save()
    buf.seek(0)
    return _merge_overlay(template_path, buf)

# ---------------------------------------------------------------------------
# Fallback-Katalog (nur benutzt, wenn kein zentraler Katalog importiert werden kann)
# ---------------------------------------------------------------------------

from decimal import Decimal as _D

PRODUCTS = {
    "Saugende Bettschutzeinlage (Einmalgebrauch)": {"qty": 25, "price": _D("10.25")},
    "Saugende Bettschutzeinlage (Wiederverwendbar)": {"qty": 1, "price": _D("22.98")},
    "Fingerlinge": {"qty": 100, "price": _D("5.00")},
    "Einmalhandschuhe": {"qty": 100, "price": _D("9.00")},
    "Medizinische Gesichtsmaske": {"qty": 50, "price": _D("6.00")},
    "FFP2-Gesichtsmaske": {"qty": 20, "price": _D("13.00")},
    "Schutzservietten (Einmalgebrauch)": {"qty": 100, "price": _D("10.00")},
    "Schürzen (Einmalgebrauch)": {"qty": 10, "price": _D("11.00")},
    "Schürzen (Wiederverwendbar)": {"qty": 1, "price": _D("20.50")},
    "Händedesinfektionsmittel": {"qty": 5, "price": _D("6.95")},
    "Flächendesinfektionsmittel": {"qty": 5, "price": _D("5.65")},
    "Händedesinfektionstücher": {"qty": 60, "price": _D("12.00")},
    "Flächendesinfektionstücher": {"qty": 100, "price": _D("16.00")},
}

# ---------------------------------------------------------------------------
# Anlage 3 – Leistungsnachweis
# ---------------------------------------------------------------------------

# Feste Stammdaten des Leistungserbringers (Fallback)
LEIST_FIX_NAME = "SSR Medizintechnik UG (Haftungsbeschränkt)"
LEIST_FIX_IK = "330304074"
LEIST_FIX_ADDR_TEL = "Hans-Böckler-Straße 2c, 37079 Göttingen – Tel. 0551-28879514"

# Vollständige X/Y-Map je Produkt und Feld (qty/net/gross) in mm
ANL3_XY = {
    "Saugende Bettschutzeinlage (Einmalgebrauch)": {
        "qty":   {"x": 118.0, "y": 134.8},
        "net":   {"x": 161.0, "y": 130.0},
        "gross": {"x": 183.0, "y": 130.0},
    },
    "Fingerlinge": {
        "qty":   {"x": 118.0, "y": 125.2},
        "net":   {"x": 161.0, "y": 121.0},
        "gross": {"x": 183.0, "y": 121.0},
    },
    "Einmalhandschuhe": {
        "qty":   {"x": 118.0, "y": 116.0},
        "net":   {"x": 161.0, "y": 112.0},
        "gross": {"x": 183.0, "y": 112.0},
    },
    "Medizinische Gesichtsmaske": {
        "qty":   {"x": 118.0, "y": 107.0},
        "net":   {"x": 161.0, "y": 103.0},
        "gross": {"x": 183.0, "y": 103.0},
    },
    "FFP2-Gesichtsmaske": {
        "qty":   {"x": 119.0, "y": 97.8},
        "net":   {"x": 161.0, "y": 94.0},
        "gross": {"x": 183.0, "y": 94.0},
    },
    # Akzeptiere beide Schreibweisen (Schürzen/Schutzschürzen)
    "Schutzschürzen (Einmalgebrauch)": {
        "qty":   {"x": 118.0, "y": 88.5},
        "net":   {"x": 161.0, "y": 85.0},
        "gross": {"x": 183.0, "y": 85.0},
    },
    "Schürzen (Einmalgebrauch)": {
        "qty":   {"x": 118.0, "y": 88.5},
        "net":   {"x": 161.0, "y": 85.0},
        "gross": {"x": 183.0, "y": 85.0},
    },
    "Schutzschürzen (Wiederverwendbar)": {
        "qty":   {"x": 120.0, "y": 79.5},
        "net":   {"x": 161.0, "y": 76.0},
        "gross": {"x": 183.0, "y": 76.0},
    },
    "Schürzen (Wiederverwendbar)": {
        "qty":   {"x": 120.0, "y": 79.5},
        "net":   {"x": 161.0, "y": 76.0},
        "gross": {"x": 183.0, "y": 76.0},
    },
    "Schutzservietten (Einmalgebrauch)": {
        "qty":   {"x": 118.0, "y": 70.0},
        "net":   {"x": 161.0, "y": 67.0},
        "gross": {"x": 183.0, "y": 67.0},
    },
    "Händedesinfektionsmittel": {
        "qty":   {"x": 120.0, "y": 60.5},
        "net":   {"x": 161.0, "y": 58.0},
        "gross": {"x": 183.0, "y": 58.0},
    },
    "Flächendesinfektionsmittel": {
        "qty":   {"x": 120.0, "y": 51.5},
        "net":   {"x": 161.0, "y": 49.0},
        "gross": {"x": 183.0, "y": 49.0},
    },
    "Händedesinfektionstücher": {
        "qty":   {"x": 118.0, "y": 42.0},
        "net":   {"x": 161.0, "y": 40.0},
        "gross": {"x": 183.0, "y": 40.0},
    },
    "Flächendesinfektionstücher": {
        "qty":   {"x": 118.0, "y": 33.0},
        "net":   {"x": 161.0, "y": 31.0},
        "gross": {"x": 183.0, "y": 31.0},
    },
}


def update_anlage3_xy(
    product_name: str,
    field: str,
    *,
    x_mm: float | None = None,
    y_mm: float | None = None,
) -> None:
    """
    Setzt X/Y für ein Produkt & Feld in Anlage 3.
      field ∈ {"qty","net","gross"}
    """
    if product_name not in ANL3_XY:
        ANL3_XY[product_name] = {
            "qty":   {"x": 111.0, "y": 200.0},
            "net":   {"x": 148.0, "y": 200.0},
            "gross": {"x": 172.0, "y": 200.0},
        }
    if field not in ("qty", "net", "gross"):
        return
    if x_mm is not None:
        ANL3_XY[product_name][field]["x"] = float(x_mm)
    if y_mm is not None:
        ANL3_XY[product_name][field]["y"] = float(y_mm)


def _anl3_get_xy(name: str, field: str) -> tuple[float, float]:
    """Gibt (x,y) in Punktkoordinaten für Anlage 3 zurück."""
    m = ANL3_XY.get(name)
    if not m:
        m = ANL3_XY["Saugende Bettschutzeinlage (Einmalgebrauch)"]
    x_mm = m[field]["x"]
    y_mm = m[field]["y"]
    return mmx(x_mm), mmy(y_mm)


def render_anlage3(
    template_path: str,
    patient: dict,
    leistungserbringer: dict | None,
    produkte_pos: list,
    mwst: Decimal = Decimal("0.19"),
) -> BytesIO:
    """
    Anlage 3 (Leistungsnachweis):

    - Patientendaten aus `patient`:
        * kasse
        * name_addr_tel
        * versicherten_nr
        * versorgungsmonat
    - Leistungserbringer-Daten:
        * aus `leistungserbringer` (name, ik, addr_tel) oder Fallback LEIST_FIX_*
    - Pro Produkt getrennte X/Y für 'qty', 'net', 'gross' (siehe ANL3_XY).
    - Menge wird mit PACK_SIZE in die "Anzahl Stück" umgerechnet.
    - Preise werden mit _eur(...) formatiert.
    - Keine Gesamtsummen-Ausgabe auf der Seite.
    """
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)

    BASE_FONT = "Courier"
    QTY_FONT = "Courier-Bold"
    ANL3_BASE_SIZE = 10
    ANL3_QTY_SIZE = max(1, ANL3_BASE_SIZE - 1)  # 9pt

    # --- Patientendaten ---
    c.setFont(BASE_FONT, ANL3_BASE_SIZE)
    c.drawString(mmx(28),  mmy(251), patient.get("kasse", ""))
    c.drawString(mmx(28),  mmy(240), patient.get("name_addr_tel", ""))
    c.drawString(mmx(28),  mmy(228), patient.get("versicherten_nr", ""))

    # --- Leistungserbringer: Parameter überschreibt Fallback ---
    le = leistungserbringer or {}
    le_name = le.get("name") or LEIST_FIX_NAME
    le_ik = le.get("ik") or LEIST_FIX_IK
    le_addr_tel = le.get("addr_tel") or LEIST_FIX_ADDR_TEL

    c.drawString(mmx(28),  mmy(217), le_name)
    c.drawString(mmx(153), mmy(217), f"IK: {le_ik}")
    c.drawString(mmx(28),  mmy(205), le_addr_tel)

    c.drawString(
        mmx(28),
        mmy(194),
        f"{patient.get('versorgungsmonat', '')}",
    )

    # --- Produkte ---
    for p in produkte_pos:
        name = p.get("name")
        if not name or name not in ANL3_XY:
            continue

        # Menge (links, 9pt, fett) – mit Packungsfaktor
        logical_qty = _as_qty(p.get("qty", 0))
        display_qty = _display_qty_from_pack(name, logical_qty)

        if display_qty > 0:
            x_qty, y_qty = _anl3_get_xy(name, "qty")
            c.setFont(QTY_FONT, ANL3_QTY_SIZE)
            c.drawString(x_qty, y_qty, str(display_qty))

        # Netto / Brutto (rechtsbündig, 10pt normal)
        gross_val = _as_dec(p.get("gross", 0))
        if p.get("net") is not None:
            net_val = _as_dec(p.get("net"))
        else:
            net_val = (gross_val / (Decimal("1") + mwst)).quantize(Decimal("0.01"))

        x_net, y_net = _anl3_get_xy(name, "net")
        x_gross, y_gross = _anl3_get_xy(name, "gross")

        c.setFont(BASE_FONT, ANL3_BASE_SIZE)
        c.drawRightString(x_net,   y_net,   _eur(net_val))
        c.drawRightString(x_gross, y_gross, _eur(gross_val))

    c.showPage()
    c.save()
    buf.seek(0)
    return _merge_overlay(template_path, buf)