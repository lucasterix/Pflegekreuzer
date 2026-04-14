# app/pdf_simple.py

from io import BytesIO
from typing import List, Dict, Any, Optional
from decimal import Decimal
import re
from datetime import datetime
import os

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics


# --- Layout (DIN-ähnlich) ---------------------------------------------------
PAGE_W, PAGE_H = A4
MARGIN_L = 25 * mm
MARGIN_R = 20 * mm
MARGIN_T = 20 * mm
MARGIN_B = 20 * mm

HEADER_H = 24 * mm
BLOCK_GAP = 6 * mm
LINE_H = 5.6 * mm
TABLE_LH = 6.0 * mm

FONT = "Helvetica"
FONT_B = "Helvetica-Bold"


# ======================================================================
# Utils
# ======================================================================

def eur(d: Decimal | float | int) -> str:
    d = d if isinstance(d, Decimal) else Decimal(str(d))
    s = f"{d:.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return s + "€"


def _safe_str(x: Any, default: str = "") -> str:
    return (x if isinstance(x, str) else "") or default


def _string_w(text: str, size: float, font: str = FONT) -> float:
    return pdfmetrics.stringWidth(text, font, size)


def _wrap_text(text: str, max_w: float, size: float = 10, font: str = FONT):
    lines_out: List[str] = []
    for raw in (text or "").splitlines() or [""]:
        words = raw.split(" ")
        line = ""
        for w in words:
            cand = (line + " " + w).strip() if line else w
            if _string_w(cand, size, font) <= max_w:
                line = cand
            else:
                if line:
                    lines_out.append(line)
                if _string_w(w, size, font) > max_w:
                    chunk = ""
                    for ch in w:
                        if _string_w(chunk + ch, size, font) <= max_w:
                            chunk += ch
                        else:
                            lines_out.append(chunk)
                            chunk = ch
                    line = chunk
                else:
                    line = w
        lines_out.append(line)
    return lines_out or [""]


def _draw_multiline(c, x, y, text, size=10, max_w=None, font=FONT, leading=LINE_H):
    c.saveState()
    c.setFont(font, size)
    lines = _wrap_text(text, max_w, size, font) if max_w else (text or "").splitlines()
    for i, line in enumerate(lines):
        c.drawString(x, y - i * leading, line)
    c.restoreState()
    return y - len(lines) * leading


def _draw_kv(
    c, x, y, kv, label_w=32 * mm, line_h=LINE_H, size=10,
    right_align_value=False, block_w=None
):
    c.saveState()
    for i, (k, v) in enumerate(kv):
        yy = y - i * line_h
        c.setFont(FONT, size)
        c.drawString(x, yy, k)
        c.setFont(FONT_B, size)
        if right_align_value and block_w:
            c.drawRightString(x + block_w, yy, v)
        else:
            c.drawString(x + label_w, yy, v)
    c.restoreState()
    return y - len(kv) * line_h


# ======================================================================
# Provider
# ======================================================================

def _provider_from_cfg(cfg: Any) -> Dict[str, str]:
    name = _safe_str(getattr(cfg, "name", ""), "Pflegehilfsmittel-Anbieter")
    ik = _safe_str(getattr(cfg, "ik", ""), "000000000")

    strasse = _safe_str(getattr(cfg, "strasse", ""))
    plz = _safe_str(getattr(cfg, "plz", ""))
    ort = _safe_str(getattr(cfg, "ort", ""))
    telefon = _safe_str(getattr(cfg, "kontakt_telefon", ""))

    addr_lines = []
    if strasse:
        addr_lines.append(strasse)
    if plz or ort:
        addr_lines.append(" ".join(x for x in [plz, ort] if x))
    addr_text = "\n".join(addr_lines)

    ust_satz = _safe_str(getattr(cfg, "ust_satz", ""), "19")

    bank_name = _safe_str(getattr(cfg, "bank_name", ""))
    bank_iban = _safe_str(getattr(cfg, "bank_iban", ""))
    bank_bic = _safe_str(getattr(cfg, "bank_bic", ""))

    if bank_iban or bank_name or bank_bic:
        parts = []
        if bank_name:
            parts.append(bank_name)
        if bank_iban:
            parts.append(f"IBAN: {bank_iban}")
        if bank_bic:
            parts.append(f"BIC: {bank_bic}")
        bank_line = " · ".join(parts)
    else:
        bank_line = "Bankverbindung: bitte IBAN/BIC in der Konfiguration hinterlegen."

    footer_line = "Vielen Dank für Ihr Vertrauen."

    return {
        "name": name,
        "addr": addr_text,
        "ik": ik,
        "telefon": telefon,
        "bank": bank_line,
        "footer": footer_line,
        "ust_satz": ust_satz,
    }


def _parse_bank_lines(bank_str: str) -> List[str]:
    s = re.sub(r"\s+", " ", (bank_str or "").strip())
    if not s:
        return []
    return [s]


def _right_footer_lines(provider: Dict[str, str]) -> List[str]:
    lines = []
    name = provider.get("name") or ""
    ik = provider.get("ik") or ""
    addr = provider.get("addr") or ""
    tel = provider.get("telefon") or ""
    footer = provider.get("footer") or ""

    if name:
        lines.append(name)
    if ik:
        lines.append(f"IK: {ik}")

    addr_parts = [ln.strip() for ln in addr.splitlines() if ln.strip()]
    if addr_parts:
        lines.append(", ".join(addr_parts))
    if tel:
        lines.append(f"Tel.: {tel}")
    if footer:
        lines.append(footer)

    return lines


def _draw_footer(c: canvas.Canvas, provider: Dict[str, str]):
    yb = MARGIN_B + 14 * mm
    c.setLineWidth(0.3)
    c.line(MARGIN_L, yb, PAGE_W - MARGIN_R, yb)

    c.setFont(FONT, 8.7)

    bank_lines = _parse_bank_lines(provider.get("bank", ""))
    for i, line in enumerate(bank_lines):
        c.drawString(MARGIN_L, yb - 4.2 * mm - i * (4.2 * mm), line)

    r_lines = _right_footer_lines(provider)
    for i, line in enumerate(r_lines):
        c.drawRightString(
            PAGE_W - MARGIN_R,
            yb - 4.2 * mm - i * (4.2 * mm),
            line,
        )


# ======================================================================
# Header (mit Logo)
# ======================================================================

def _draw_header(c: canvas.Canvas, title: str, logo_path: Optional[str]):
    """
    Zeichnet den Dokumenttitel links und – falls vorhanden – das Logo rechts.
    """
    top_y = PAGE_H - MARGIN_T

    # Titel
    c.setFont(FONT_B, 16)
    c.drawString(MARGIN_L, top_y - 4 * mm, title)

    # Logo rechts
    if logo_path and os.path.exists(logo_path):
        try:
            logo_h = 18 * mm
            logo_w = 18 * mm
            c.drawImage(
                logo_path,
                PAGE_W - MARGIN_R - logo_w,
                top_y - logo_h,
                width=logo_w,
                height=logo_h,
                preserveAspectRatio=True,
                mask="auto",
            )
        except Exception:
            # Logo-Fehler sollen nicht die gesamte Rechnung sprengen
            pass

    # Trennlinie
    line_y = top_y - HEADER_H
    c.setLineWidth(0.5)
    c.line(MARGIN_L, line_y, PAGE_W - MARGIN_R, line_y)

    return line_y - 2 * mm


# ======================================================================
# Hilfsfunktionen
# ======================================================================

def _format_address_block(addr: str) -> str:
    s = (addr or "").strip()
    if not s:
        return ""
    if "," in s:
        left, right = s.split(",", 1)
        return left.strip() + "\n" + right.strip()
    m = re.search(r"\b(\d{4,5})\s+([^\n]+)$", s)
    if m:
        pre = s[:m.start()].strip(" ,")
        post = f"{m.group(1)} {m.group(2)}".strip()
        if pre and post:
            return pre + "\n" + post
    return s


def _draw_totals_box(
    c, x_right, y, total_net, total_vat, total_gross, ust_satz
):
    pad_x = 3 * mm
    pad_y = 2 * mm
    row_h = TABLE_LH

    label_w = 32 * mm
    value_w = 28 * mm
    box_w = label_w + value_w + 2 * pad_x
    x = x_right - box_w

    box_h = 3 * row_h + 2 * pad_y
    c.setLineWidth(0.5)
    c.rect(x, y - box_h, box_w, box_h)

    yy = y - pad_y

    def row(label, value, bold=False):
        nonlocal yy
        yy -= row_h
        c.setFont(FONT_B if bold else FONT, 10)
        c.drawString(x + pad_x, yy, label)
        c.drawRightString(x + pad_x + label_w + value_w, yy, value)

    vat_label = f"MwSt gesamt ({ust_satz}%)" if ust_satz else "MwSt gesamt"

    row("Summe netto:", eur(total_net))
    row(vat_label + ":", eur(total_vat))
    row("Summe brutto:", eur(total_gross), bold=True)

    return y - box_h


def _fmt_versorgungsmonat(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return "-"
    m = re.match(r"^\s*(\d{4})-(\d{2})(?:-\d{2})?\s*$", s)
    if m:
        return f"{m.group(2)}/{m.group(1)}"
    return s


# ======================================================================
# Hauptfunktion
# ======================================================================

def make_invoice_pdf(
    cfg: Any,
    provider: Dict[str, Any],
    patient: Dict[str, Any],
    positions: List[Dict[str, Any]],
    total_net: Optional[Decimal] = None,
    total_vat: Optional[Decimal] = None,
    total_gross: Optional[Decimal] = None,
    logo_path: Optional[str] = None,
) -> BytesIO:
    """
    Erzeugt eine Rechnung als PDF, inkl. korrekter MwSt-Berechnung.
    """

    # Provider-Daten zusammenführen
    provider_full = dict(_provider_from_cfg(cfg))
    provider_full.update({k: v for k, v in provider.items() if v is not None})

    # USt-Satz sicher extrahieren und als Decimal behandeln
    try:
        ust_satz = Decimal(str(provider_full.get("ust_satz", "19")).replace(",", "."))
    except Exception:
        ust_satz = Decimal("19")

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)

    # Header (mit Logo)
    y = _draw_header(c, "Rechnung", logo_path)
    y -= BLOCK_GAP

    # Kopfbereich
    col_gap = 12 * mm
    total_w = PAGE_W - MARGIN_L - MARGIN_R
    left_w = total_w * 0.54
    right_w = total_w - left_w - col_gap

    kassename = _safe_str(patient.get("pflegekasse"), "")
    kasse_addr = _safe_str(patient.get("pflegekasse_address"), "")
    recipient = kassename or "Pflegekasse"
    if kasse_addr:
        recipient += "\n" + _format_address_block(kasse_addr)

    y_left = _draw_multiline(
        c, MARGIN_L, y, recipient, size=10, font=FONT_B, max_w=left_w
    )

    sender_lines = []
    if provider_full.get("name"):
        sender_lines.append(provider_full["name"])
    if provider_full.get("addr"):
        sender_lines.append(provider_full["addr"])
    if provider_full.get("ik"):
        sender_lines.append(f"IK: {provider_full['ik']}")
    sender = "\n".join(sender_lines)

    x_right_col = MARGIN_L + left_w + col_gap
    y_right = _draw_multiline(c, x_right_col, y, sender, size=10, max_w=right_w)
    y_right -= BLOCK_GAP / 2

    rechnungsnr = datetime.now().strftime("RE-%Y%m%d-%H%M%S")
    vm_raw = _safe_str(patient.get("versorgungsmonat")) or _safe_str(
        patient.get("leistungsmonat")
    )
    versorgungsmonat = _fmt_versorgungsmonat(vm_raw)

    y_right = _draw_kv(
        c,
        x_right_col,
        y_right,
        [
            ("Rechnungs-Nr.:", rechnungsnr),
            ("Rechnungsdatum:", datetime.now().strftime("%d.%m.%Y")),
            ("Versorgungsmonat:", versorgungsmonat),
        ],
        label_w=30 * mm,
        line_h=LINE_H,
        size=10,
        right_align_value=True,
        block_w=right_w,
    )

    y = min(y_left, y_right) - BLOCK_GAP

    pname = _safe_str(patient.get("name"), "Unbekannt")
    paddr = _safe_str(patient.get("adresse"), "")
    pdob = _safe_str(patient.get("geburtsdatum"), "")
    pvsnr = _safe_str(patient.get("versichertennr"), "")

    y = _draw_kv(
        c,
        MARGIN_L,
        y,
        [
            ("Kassenpatient:", pname),
            ("Anschrift:", paddr),
            ("Geburtsdatum:", pdob),
            ("Vers.-Nr.:", pvsnr),
        ],
        label_w=36 * mm,
        line_h=LINE_H,
        size=10,
    ) - BLOCK_GAP

    # Betreff
    c.setFont(FONT_B, 11)
    c.drawString(MARGIN_L, y, "Betreff: Abrechnung Pflegehilfsmittel § 40 SGB XI")
    y -= 8 * mm

    y = _draw_multiline(
        c,
        MARGIN_L,
        y,
        "Wir stellen die folgenden Leistungen in Rechnung:",
        size=10,
        max_w=PAGE_W - MARGIN_L - MARGIN_R,
    ) - BLOCK_GAP / 2

    # Tabellenlayout
    content_w = PAGE_W - MARGIN_L - MARGIN_R
    ratios = [0.54, 0.08, 0.14, 0.10, 0.14]
    widths = [content_w * r for r in ratios]
    xs = [MARGIN_L]
    for w in widths[:-1]:
        xs.append(xs[-1] + w)

    headers = ["Artikel", "Menge", "Einzelpreis", "MwSt", "Brutto"]

    def _table_header(ypos):
        c.setFont(FONT_B, 9.5)
        for i, h in enumerate(headers):
            c.drawString(xs[i], ypos, h)
        ypos -= TABLE_LH
        c.setLineWidth(0.4)
        c.line(MARGIN_L, ypos, MARGIN_L + content_w, ypos)
        ypos -= TABLE_LH
        c.setFont(FONT, 9.5)
        return ypos

    def _maybe_new_page(ypos):
        if ypos < MARGIN_B + 45 * mm:
            _draw_footer(c, provider_full)
            c.showPage()
            ny = _draw_header(c, "Rechnung", logo_path) - BLOCK_GAP
            ny = _table_header(ny)
            return ny
        return ypos

    y = _table_header(y)
    max_name_w = widths[0] - 2

    total_net_calc = Decimal("0.00")
    total_vat_calc = Decimal("0.00")

    def _col_center(i):
        return xs[i] + widths[i] / 2

    for pos in positions:
        y = _maybe_new_page(y)

        name = str(pos.get("name", ""))
        qty = Decimal(pos.get("qty", 0))
        unit = Decimal(pos.get("unit_price", 0))

        net = (unit * qty).quantize(Decimal("0.01"))
        vat = (net * ust_satz / Decimal("100")).quantize(Decimal("0.01"))
        gross = (net + vat).quantize(Decimal("0.01"))

        total_net_calc += net
        total_vat_calc += vat

        name_lines = _wrap_text(name, max_name_w, size=9.5, font=FONT)
        for i, line in enumerate(name_lines):
            if i == 0:
                c.drawString(xs[0], y, line)
                c.drawCentredString(_col_center(1), y, str(qty))
                c.drawCentredString(_col_center(2), y, eur(unit))
                c.drawCentredString(_col_center(3), y, eur(vat))
                c.drawCentredString(_col_center(4), y, eur(gross))
            else:
                c.drawString(xs[0], y, line)
            y -= TABLE_LH
            y = _maybe_new_page(y)

    # Summen neu berechnen, falls extern nicht übergeben
    total_net = total_net or total_net_calc.quantize(Decimal("0.01"))
    total_vat = total_vat or total_vat_calc.quantize(Decimal("0.01"))
    total_gross = total_gross or (total_net + total_vat).quantize(Decimal("0.01"))

    y -= 2 * mm
    c.setLineWidth(0.5)
    c.line(MARGIN_L, y, MARGIN_L + content_w, y)
    y -= 5 * mm

    y = _draw_totals_box(
        c,
        MARGIN_L + content_w,
        y,
        total_net,
        total_vat,
        total_gross,
        f"{ust_satz}",
    )

    y -= 8 * mm
    c.setFont(FONT, 9)
    c.drawString(MARGIN_L, y, "Zahlungsziel: 14 Tage ohne Abzug.")
    y -= 5 * mm
    c.drawString(MARGIN_L, y, f"Verwendungszweck: {rechnungsnr} – {pname}")

    _draw_footer(c, provider_full)

    c.showPage()
    c.save()
    buf.seek(0)
    return buf

# Rückwärtskompatibilität
make_summary_pdf = make_invoice_pdf