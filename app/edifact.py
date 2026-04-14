# app/edifact.py

from datetime import datetime
from decimal import Decimal
from typing import Iterable, List, Optional

from .models.abrechnung import Abrechnung, AbrechnungsPosition
from .models.patient import Patient
from .models.kostentraeger import Kostentraeger
from .models.settings import Einstellungen
from . import keys


def _seg(tag: str, *parts: str) -> str:
    """ Baut EDIFACT-Segment → _seg("UNH","ID","INVOIC") -> UNH+ID+INVOIC' """
    return "+".join([tag, *parts]) + "'"


def _money(dec: Decimal) -> str:
    """ Format für Beträge nach EDIFACT → 12.30 -> 12,30 """
    return f"{dec:.2f}".replace(".", ",")


def build_edifact_from_abrechnung(
    abrechnung: Abrechnung,
    cfg: Optional[Einstellungen] = None,
) -> bytes:
    """
    Baut INVOIC-EDIFACT gemäß TA3.
    Nutzt TA3-Schlüssel aus config (Abrechnungscode + Tarifkennzeichen).
    """

    patient: Patient = abrechnung.patient
    kasse: Optional[Kostentraeger] = abrechnung.kasse
    positionen: Iterable[AbrechnungsPosition] = abrechnung.positionen

    now = datetime.now()
    nachrichten_ref = f"PFL{abrechnung.id}"
    rechnungsnummer = f"R{abrechnung.id:06d}"

    # Rechnungsmonat → exaktes TA3-Rechnungsdatum = 1. des Monats
    if abrechnung.abrechnungsmonat and "-" in abrechnung.abrechnungsmonat:
        jahr, monat = abrechnung.abrechnungsmonat.split("-", 1)
        datum_rechnung = f"{jahr}{monat}01"
    else:
        datum_rechnung = now.strftime("%Y%m%d")

    # ==========================================================
    #   TA3-Schlüssel aus CONFIG
    # ==========================================================
    sender_ik = cfg.ik if (cfg and cfg.ik) else "000000000"
    abrechnungscode = cfg.abrechnungscode if cfg else None
    tarifkennzeichen = cfg.tarifkennzeichen if cfg else None
    empfaenger_ik = (kasse.ik if (kasse and kasse.ik) else "999999999")

    # ❗ HARTE VALIDIERUNG (OPTION A)
    if not abrechnungscode or not tarifkennzeichen:
        raise ValueError(
            f"EDIFACT kann nicht erzeugt werden – TA3 nicht vollständig.\n"
            f"Abrechnungscode: {abrechnungscode}, Tarifkennzeichen: {tarifkennzeichen}\n"
            "Bitte in /config korrekt hinterlegen."
        )

    leistungserbringergruppe = keys.leistungserbringergruppe(
        abrechnungscode,
        tarifkennzeichen,
    )

    # ==========================================================
    #   SEGMENTE AUFBAU
    # ==========================================================
    segmente: List[str] = []

    segmente.append("UNA:+.? '")  # Syntaxrahmen

    segmente.append(_seg(
        "UNB",
        "UNOA:1",                # Zeichensatz
        sender_ik,
        empfaenger_ik,
        now.strftime("%y%m%d") + ":" + now.strftime("%H%M"),
        nachrichten_ref
    ))

    segmente.append(_seg("UNH", nachrichten_ref, "INVOIC:D:96A:UN"))
    segmente.append(_seg("BGM", "380", rechnungsnummer, "9"))
    segmente.append(_seg("DTM", f"137:{datum_rechnung}:102"))

    # NAD – Beteiligte
    segmente.append(_seg("NAD", "SU", f"{sender_ik}::9"))       # Leistungserbringer
    segmente.append(_seg("NAD", "DP", f"{empfaenger_ik}::9"))   # Kostenträger
    segmente.append(_seg("NAD", "PE", (patient.name or "").replace("+", " ")))

    segmente.append(_seg("CUX", f"2:{keys.CURRENCY}"))  # EUR

    # FTX – TA3-Parameter (⚠ kritisch für Kassenannahme)
    segmente.append(_seg(
        "FTX", "ZZZ", "", "",
        f"RART:{keys.RECHNUNGSART}:"
        f"LGRP:{leistungserbringergruppe}:"
        f"VKENN:{keys.VERARBEITUNGSKENNZEICHEN}"
    ))

    # ==========================================================
    #   POSITIONSDATEN
    # ==========================================================
    laufende_pos = 1
    gesamt = Decimal("0.00")

    for pos in positionen:
        hm = pos.hilfsmittel
        posnr = (hm.positionsnummer or "").replace("+", " ")

        segmente.append(_seg("LIN", str(laufende_pos), "", f"{posnr}:SRV"))
        segmente.append(_seg(
            "ELS",
            f"{keys.ART_LEISTUNG}:{keys.VERGUETUNGSART}:{keys.QUAL_VERG}:{hm.positionsnummer}"
        ))
        segmente.append(_seg("QTY", f"47:{pos.menge}"))
        segmente.append(_seg("PRI", f"AAA:{_money(pos.einzelpreis)}"))
        segmente.append(_seg("MOA", f"203:{_money(pos.betrag_gesamt)}"))

        gesamt += pos.betrag_gesamt
        laufende_pos += 1

    segmente.append(_seg("MOA", f"39:{_money(gesamt)}"))

    # Abschluss
    segmente.append(_seg("UNT", str(len(segmente)-2), nachrichten_ref))
    segmente.append(_seg("UNZ", "1", nachrichten_ref))

    return "\n".join(segmente).encode("latin-1", errors="replace")