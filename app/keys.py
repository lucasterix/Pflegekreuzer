# app/keys.py

"""
Fallback-Konstanten für TA3 / TA1-Schlüssel.
Alles, was aus der DB-Konfiguration kommt, hat Vorrang.
"""

# Rechnungsart (TA3 2.1) – 1 = Rechnung vom Leistungserbringer direkt an die Kasse
RECHNUNGSART = "1"

# Art der abgegebenen Leistung (TA3 2.4) – 06 = Pflegehilfsmittel
ART_LEISTUNG = "06"

# Vergütungsart (TA3 2.5) – 05 = Pflegehilfsmittel
VERGUETUNGSART = "05"

# Qualifikationsabhängige Vergütung (TA3 2.6) – bei Hilfsmitteln meist 0
QUAL_VERG = "0"

# Verarbeitungskennzeichen (TA3 2.3) – 01 = Standardabrechnung
VERARBEITUNGSKENNZEICHEN = "01"

# Standard-Leistungserbringergruppe (Abrechnungscode + Tarifkennzeichen)
ABRECHNUNGSCODE_DEFAULT = "19"      # z.B. „sonstiger Pflegehilfsmittellieferant“
TARIFKENNZEICHEN_DEFAULT = "00000"  # wird später durch Bundesland-Spezial ersetzt

# Währung
CURRENCY = "EUR"


def leistungserbringergruppe(
    abrechnungscode: str | None,
    tarifkennzeichen: str | None,
) -> str:
    """
    Baut den 7-stelligen Schlüssel: 2-stelliger Abrechnungscode + 5-stelliges Tarifkennzeichen.
    """
    code = (abrechnungscode or ABRECHNUNGSCODE_DEFAULT).zfill(2)
    tarif = (tarifkennzeichen or TARIFKENNZEICHEN_DEFAULT).zfill(5)
    return f"{code}{tarif}"