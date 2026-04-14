# app/fixtures.py

from decimal import Decimal

# ---------------------------------------------------------------------------
# Pflegehilfsmittel-Defaults
#
# Struktur:
#   - qty             = Standard-Abgabemenge (dein „Paket“ / Monat)
#   - price           = Bruttopreis für dieses Paket
#   - positionsnummer = offizielle Pflegehilfsmittelpositionsnummer (PG 54 / PG 51)
#   - kennzeichen     = Kennzeichen PHM lt. Anlage 3 zum DA (hier überall "00")
#
# Positionsnummern und Kennzeichen stammen aus:
#   PHM_Vertrag_Verband_AC_TK_19-00-P51 – Anlage(n) Pflegehilfsmittel
# ---------------------------------------------------------------------------

PFLEGEHILFSMITTEL_DEFAULTS = {
    # -----------------------------------------------------------------------
    # PG 54 – Zum Verbrauch bestimmte Pflegehilfsmittel
    # -----------------------------------------------------------------------

    "Saugende Bettschutzeinlage (Einmalgebrauch)": {
        "qty": 25,                           # dein Paket (25 Stück)
        "price": Decimal("10.25"),           # 25 x 0,41 €
        "positionsnummer": "54.45.01.0001",  # saugende Bettschutzeinlagen, Einmalgebrauch
        "kennzeichen": "00",
    },

    "Fingerlinge": {
        "qty": 100,
        "price": Decimal("5.00"),
        "positionsnummer": "54.99.01.0001",
        "kennzeichen": "00",
    },

    "Einmalhandschuhe": {
        "qty": 100,
        "price": Decimal("9.00"),            # dein Wert, Vertrag wäre 100 x 0,08 €
        "positionsnummer": "54.99.01.1001",
        "kennzeichen": "00",
    },

    "Medizinische Gesichtsmaske": {
        "qty": 50,
        "price": Decimal("6.00"),            # dein Wert
        "positionsnummer": "54.99.01.2001",
        "kennzeichen": "00",
    },

    "FFP2-Gesichtsmaske": {
        "qty": 20,                           # dein Paket, Vertrag-Rechengröße 10 Stück
        "price": Decimal("13.00"),           # aktualisierter Netto-Preis
        "positionsnummer": "54.99.01.5001",
        "kennzeichen": "00",
    },

    "Schutzservietten (Einmalgebrauch)": {
        "qty": 100,
        "price": Decimal("10.00"),
        "positionsnummer": "54.99.01.4001",
        "kennzeichen": "00",
    },

    "Schutzschürzen (Wiederverwendbar)": {
        "qty": 1,
        "price": Decimal("20.50"),           # dein Wert, Vertrag 21,00 €
        "positionsnummer": "54.99.01.3002",
        "kennzeichen": "00",
    },

    "Händedesinfektionsmittel": {
        "qty": 5,                            # z.B. 5 x 100 ml
        "price": Decimal("6.95"),
        "positionsnummer": "54.99.02.0001",
        "kennzeichen": "00",
    },

    "Flächendesinfektionsmittel": {
        "qty": 5,
        "price": Decimal("5.65"),
        "positionsnummer": "54.99.02.0002",
        "kennzeichen": "00",
    },

    "Händedesinfektionstücher": {
        "qty": 60,
        "price": Decimal("12.00"),
        "positionsnummer": "54.99.02.0014",
        "kennzeichen": "00",
    },

    "Flächendesinfektionstücher": {
        "qty": 100,
        "price": Decimal("16.00"),
        "positionsnummer": "54.99.02.0015",
        "kennzeichen": "00",
    },

    # Abschlagspositionsnummer (Differenzbetrag), falls du sie später nutzen willst
    "Abschlagspositionsnummer (Differenzbetrag)": {
        "qty": 0,
        "price": Decimal("0.00"),
        "positionsnummer": "54.00.99.0088",
        "kennzeichen": "00",
    },

    # -----------------------------------------------------------------------
    # PG 51 – Pflegerische Hilfsmittel zur Körperpflege/Hygiene etc.
    # (Nicht zum Verbrauch bestimmt)
    # -----------------------------------------------------------------------

    "Saugende Bettschutzeinlage (Wiederverwendbar)": {
        "qty": 1,
        "price": Decimal("22.98"),           # dein Wert, Vertrag 21,00 €
        "positionsnummer": "51.40.01.4",     # laut Vertrag: 51.40.01.4
        "kennzeichen": "00",
    },
}
