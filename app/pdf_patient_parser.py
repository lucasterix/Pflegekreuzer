# app/pdf_patient_parser.py

from __future__ import annotations

import re
from datetime import datetime
from typing import Dict, Any, Optional, List


def _clean_lines(text: str) -> List[str]:
    lines = [ln.strip() for ln in text.splitlines()]
    return [ln for ln in lines if ln]  # leere raus


def parse_patient_from_pdf_text(text: str) -> Dict[str, Any]:
    """
    Parsen deiner Dokumentations-PDF, z.B.:

    Eberhardt George
    Dokumentation
    ...
    PERSÖNLICHE INFORMATIONEN
    Geboren: 05.10.1944 vor 81 J.
    Adresse: Elsa-Brändström-Weg 2
    37075 Göttingen
    Göttingen-Herberhausen
    Versichertennr.: W633455868
    Pflegeversicherung: Barmer
    ...

    Liefert Dict mit:
      - name
      - versichertennummer
      - geburtsdatum (ISO yyyy-mm-dd für <input type="date">)
      - address
      - pflegeversicherung_name
    """
    result: Dict[str, Any] = {
        "name": "",
        "versichertennummer": "",
        "geburtsdatum": "",
        "address": "",
        "pflegeversicherung_name": "",
    }

    lines = _clean_lines(text)

    # --- Name: Zeile vor "Dokumentation" -----------------------------
    try:
        idx_doc = next(i for i, ln in enumerate(lines) if "Dokumentation" in ln)
        if idx_doc > 0:
            result["name"] = lines[idx_doc - 1].strip()
    except StopIteration:
        # Fallback: erste Zeile, wenn alles andere schiefgeht
        if lines:
            result["name"] = lines[0]

    # --- Geburtsdatum -------------------------------------------------
    m = re.search(r"Geboren:\s*([0-9]{2}\.[0-9]{2}\.[0-9]{4})", text)
    if m:
        raw = m.group(1)
        try:
            dt = datetime.strptime(raw, "%d.%m.%Y").date()
            result["geburtsdatum"] = dt.strftime("%Y-%m-%d")  # HTML-Date-Format
        except ValueError:
            pass

    # --- Adresse: ab "Adresse:" bis zur nächsten Feld-Überschrift -----
    # Strategie:
    #   - Zeile mit "Adresse:" finden
    #   - Rest der Zeile + folgende Zeilen einsammeln,
    #     bis wir auf eine Zeile stoßen, die mit einem bekannten Label beginnt
    STOP_PREFIXES = (
        "Versichertennr.:",
        "Pflegeversicherung:",
        "Telefon:",
        "Mobil:",
        "E-Mail:",
        "BETREUERHISTORIE",
    )

    addr_lines: List[str] = []
    for i, ln in enumerate(lines):
        if ln.startswith("Adresse:"):
            first = ln.split("Adresse:", 1)[1].strip()
            if first:
                addr_lines.append(first)

            # nachfolgende Zeilen einsammeln
            j = i + 1
            while j < len(lines):
                nxt = lines[j]
                if any(nxt.startswith(pfx) for pfx in STOP_PREFIXES):
                    break
                addr_lines.append(nxt)
                j += 1
            break

    if addr_lines:
        # z.B. "Elsa-Brändström-Weg 2, 37075 Göttingen, Göttingen-Herberhausen"
        result["address"] = ", ".join(addr_lines)

    # --- Versichertennummer -------------------------------------------
    m = re.search(r"Versichertennr\.\s*:\s*([A-Z0-9]+)", text)
    if m:
        result["versichertennummer"] = m.group(1).strip()

    # --- Pflegeversicherung -------------------------------------------
    m = re.search(r"Pflegeversicherung:\s*(.+)", text)
    if m:
        result["pflegeversicherung_name"] = m.group(1).strip()

    return result