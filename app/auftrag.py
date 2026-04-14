# app/auftrag.py

from datetime import datetime
from typing import Optional

# Laut Anlage 2: Länge der Auftragsdatei in Bytes = 00000348 (Version 01)
AUF_LENGTH = 348


def _init_line(length: int = AUF_LENGTH) -> list[str]:
    """
    Erstellt eine leere Auftragssatz-Zeile mit Leerzeichen (AN-Felder Default).
    """
    return [" "] * length


def _set_text(buf: list[str], start: int, end: int, value: Optional[str]):
    """
    Alphanumerische Felder (A/AN): linksbündig, mit Leerzeichen aufgefüllt.
    start/end sind 1-basiert (wie in der Anlage beschrieben).
    """
    field_len = end - start + 1
    txt = (value or "")[:field_len]
    txt = txt.ljust(field_len, " ")
    buf[start - 1 : end] = list(txt)


def _set_number(buf: list[str], start: int, end: int, value: Optional[object]):
    """
    Numerische Felder (N): rechtsbündig, mit Nullen aufgefüllt.
    """
    field_len = end - start + 1
    if value is None:
        s = ""
    else:
        s = str(value)
    s = s[-field_len:]           # nur rechte Stellen
    s = s.rjust(field_len, "0")  # links mit 0 auffüllen
    buf[start - 1 : end] = list(s)


def build_auftragssatz(
    verfahrenskennung: str,
    transfer_nummer: str,
    absender_ik: str,
    empfaenger_ik: Optional[str] = None,
    dateiname: Optional[str] = None,
    datum_erstellung: Optional[datetime] = None,
    # fachliche Felder (2. Teil, 3. Teil, 4. Teil)
    dateigroesse_nutzdaten: Optional[int] = None,
    dateigroesse_uebertragung: Optional[int] = None,
    zeichensatz: str = "I8",                # I8 = UTF-8, I1 = ISO-8859-1
    komprimierung: str = "00",              # 00 = keine
    verschluesselungsart: str = "02",       # 02 = PKCS#7 (E-Mail-Verschlüsselung)
    elektronische_unterschrift: str = "00", # 00 = keine elektronische Signatur
    uebertragungsweg: int | str = 5,        # 5 = „anderer Weg“ (z.B. E-Mail/SMTP)
    verzoegerter_versand: Optional[str] = None,  # JJMMTTSSmm oder None
    email_absender: Optional[str] = None,
    abrechnungscode: Optional[str] = None,      # z.B. „19“ für Pflegehilfsmittel

    # aus Config
    verfahren_spezifikation: Optional[str] = None,  # Feld 28–32
    max_wiederholungen: Optional[str] = None,       # Feld 228–229
) -> str:
    """
    Baut einen Auftragssatz (Version 1.0) gemäß TA1 Anlage 2.

    - Teil 1: Allgemeine Beschreibung (Identifikator, Version, Länge, IKs, etc.)
    - Teil 2: Logging / Datumsfelder, Dateigrößen, Zeichensatz, Kompression, Verschlüsselung
    - Teil 3: KKS-Felder (Status, Wiederholung, Übertragungsweg, Infofelder)
    - Teil 4: RZ-spezifische Felder (E-Mail-Adresse Absender, Dateibezeichnung/Abrechnungscode)

    Alle Positionen sind fest (1..348).
    """

    buf = _init_line()

    # ==================================
    # 1. TEIL – Allgemeine Beschreibung
    # ==================================

    # 01–06: IDENTIFIKATOR – Konstante '500000'
    _set_text(buf, 1, 6, "500000")

    # 07–08: VERSION – '01'
    _set_number(buf, 7, 8, 1)  # '01'

    # 09–16: LÄNGE_AUFTRAG – bei Version 01 konstant '00000348'
    _set_number(buf, 9, 16, AUF_LENGTH)

    # 17–19: SEQUENZ_NR – bei dir: Nachricht nicht segmentiert → '000'
    _set_number(buf, 17, 19, 0)

    # 20–24: VERFAHREN_KENNUNG (z.B. TPFL0 / EPFL0)
    _set_text(buf, 20, 24, verfahrenskennung)

    # 25–27: TRANSFER_NUMMER, '001'..'999'
    _set_number(buf, 25, 27, transfer_nummer)

    # 28–32: VERFAHREN_KENNUNG_SPEZIFIKATION – aus Config, sonst leer
    _set_text(buf, 28, 32, verfahren_spezifikation or "")

    # 33–47: ABSENDER_EIGNER (IK des Leistungserbringers)
    _set_text(buf, 33, 47, absender_ik)

    # 48–62: ABSENDER_PHYSIKALISCH – hier identisch
    _set_text(buf, 48, 62, absender_ik)

    # 63–77: EMPFÄNGER_NUTZER – IK der Kasse / Annahmestelle
    _set_text(buf, 63, 77, empfaenger_ik or "")

    # 78–92: EMPFÄNGER_PHYSIKALISCH – meist identisch
    _set_text(buf, 78, 92, empfaenger_ik or "")

    # 93–98: FEHLER_NUMMER – '000000' (kein Fehler)
    _set_number(buf, 93, 98, 0)

    # 99–104: FEHLER_MASSNAHME – '000000'
    _set_number(buf, 99, 104, 0)

    # 105–115: DATEINAME – logischer Dateiname ohne Extension
    if dateiname is None:
        dateiname = f"{verfahrenskennung}{transfer_nummer}"
    _set_text(buf, 105, 115, dateiname)

    # 116–129: DATUM_ERSTELLUNG – JJJJMMTThhmmss
    if datum_erstellung is None:
        datum_erstellung = datetime.now()
    ts_erstellung = datum_erstellung.strftime("%Y%m%d%H%M%S")
    _set_number(buf, 116, 129, ts_erstellung)

    # ==================================
    # 2. TEIL – Logging / Dateigrößen etc.
    # ==================================

    # 130–143: DATUM_ÜBERTRAGUNG_GESENDET – Start Übermittlung (hier = Erstellungszeit)
    _set_number(buf, 130, 143, ts_erstellung)

    # 144–157: DATUM_ÜBERTRAGUNG_EMPFANGEN_START – vom Empfänger zu setzen → Nullen
    _set_number(buf, 144, 157, 0)

    # 158–171: DATUM_ÜBERTRAGUNG_EMPFANGEN_ENDE – vom Empfänger → Nullen
    _set_number(buf, 158, 171, 0)

    # 172–177: DATEIVERSION – derzeit nicht benutzt → '000000'
    _set_number(buf, 172, 177, 0)

    # 178: KORREKTUR – derzeit nicht benutzt → '0'
    _set_number(buf, 178, 178, 0)

    # 179–190: DATEIGRÖSSE_NUTZDATEN – unverschlüsselt / unkomprimiert
    if dateigroesse_nutzdaten is None:
        dateigroesse_nutzdaten = 0
    _set_number(buf, 179, 190, dateigroesse_nutzdaten)

    # 191–202: DATEIGRÖSSE_ÜBERTRAGUNG – nach Verschlüsselung/Kompression
    if dateigroesse_uebertragung is None:
        dateigroesse_uebertragung = 0
    _set_number(buf, 191, 202, dateigroesse_uebertragung)

    # 203–204: ZEICHENSATZ – z.B. „I1“, „I8“, „U8“, „BI“
    _set_text(buf, 203, 204, zeichensatz)

    # 205–206: KOMPRIMIERUNG – 00: keine, 02: gzip, 03: ZIP, 04: TRSMAIN
    _set_number(buf, 205, 206, komprimierung)

    # 207–208: VERSCHLÜSSELUNGSART – 00 oder 02 (PKCS#7)
    _set_number(buf, 207, 208, verschluesselungsart)

    # 209–210: ELEKTRONISCHE_UNTERSCHRIFT – 00 oder 02 (PKCS#7)
    _set_number(buf, 209, 210, elektronische_unterschrift)

    # ==================================
    # 3. TEIL – KKS-spezifische Felder
    # ==================================

    # 211–213: SATZFORMAT – bei DFÜ: Leerzeichen
    _set_text(buf, 211, 213, "")

    # 214–218: SATZLÄNGE – bei DFÜ: '00000'
    _set_number(buf, 214, 218, 0)

    # 219–226: BLOCKLÄNGE – bei DFÜ: '00000000'
    _set_number(buf, 219, 226, 0)

    # 227: STATUS – bei Absender: Leerzeichen
    _set_text(buf, 227, 227, " ")

    # 228–229: WIEDERHOLUNG – max. Anzahl Übertragungsversuche
    # aus Config, sonst Default '03'
    if max_wiederholungen:
        mw = str(max_wiederholungen).strip()
        if not mw.isdigit():
            mw = "3"
    else:
        mw = "3"
    _set_number(buf, 228, 229, mw)

    # 230: ÜBERTRAGUNGSWEG – 1..5, 5 = „anderer Weg“ (z.B. E-Mail/SMTP/KIM)
    _set_number(buf, 230, 230, uebertragungsweg)

    # 231–240: VERZÖGERTER_VERSAND – JJMMTTSSmm oder '0000000000'
    if verzoegerter_versand:
        _set_number(buf, 231, 240, verzoegerter_versand)
    else:
        _set_number(buf, 231, 240, 0)

    # 241–246: INFO UND FEHLERFELDER – '000000' bei erfolgreichem Auftrag
    _set_number(buf, 241, 246, 0)

    # 247–274: VARIABLES INFO-FELD – Klartextfehler / Tracking-ID; bei dir leer
    _set_text(buf, 247, 274, "")

    # ==================================
    # 4. TEIL – RZ-spezifische Informationen
    # ==================================

    # 275–318: E-MAIL-ADRESSE ABSENDER (max. 44 Zeichen im Auftragssatz)
    _set_text(buf, 275, 318, email_absender or "")

    # 319–348: DATEI_BEZEICHNUNG
    # Einfach: erste 2 Stellen = abrechnungscode, Rest Leerzeichen.
    if abrechnungscode and len(abrechnungscode) >= 1:
        code = abrechnungscode[:2]
        value = code
    else:
        value = ""
    _set_text(buf, 319, 348, value)

    # Sicherheit: Länge prüfen
    line = "".join(buf)
    if len(line) != AUF_LENGTH:
        print(f"[AUF] WARNUNG: Auftragssatz-Länge = {len(line)} (erwartet {AUF_LENGTH})")

    return line