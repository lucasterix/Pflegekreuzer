from sqlalchemy import Column, Integer, String, Boolean, Numeric
from ..db import Base


class Einstellungen(Base):
    __tablename__ = "einstellungen"

    id = Column(Integer, primary_key=True, index=True)

    # ==========================
    # Stammdaten Leistungserbringer
    # ==========================
    name = Column(String, nullable=True)
    strasse = Column(String, nullable=True)
    plz = Column(String, nullable=True)
    ort = Column(String, nullable=True)

    # IK des Leistungserbringers (9-stellig, Pflicht)
    ik = Column(String, nullable=False)

    # KIM-Adresse (optional, falls KIM zusätzlich verwendet wird)
    kim_adresse = Column(String, nullable=True)

    # ==========================
    # Abrechnung / TA3 / PFL_ABR
    # ==========================
    bundesland = Column(String, nullable=True)
    abrechnungscode = Column(String, nullable=True)
    tarifkennzeichen = Column(String, nullable=True)

    # Verfahrenskennung TPFL0 (Test) / EPFL0 (Echt)
    verfahrenskennung = Column(String, nullable=False, default="TPFL0")

    # Umsatzsteuer
    ust_pflichtig = Column(Boolean, nullable=False, default=False)
    ust_satz = Column(String, nullable=True)

    # Übermittlungsmedium (z.B. "2" = E-Mail (SMTP) nach Anlage 7)
    # "1" könnte z.B. KIM/DFÜ sein, wird bei dir aber nicht genutzt.
    uebermittlungsmedium = Column(String, nullable=True, default="2")

    # Zeichensatz für EDIFACT / XML (I1/I8/…)
    zeichensatz = Column(String, nullable=True)

    # ==========================
    # AUF-spezifische Einstellungen (TA1)
    # ==========================

    # 28–32: VERFAHREN_KENNUNG_SPEZIFIKATION (z.B. Nachrichtentyp / Variante)
    verfahren_spezifikation = Column(String, nullable=True)

    # 205–206: KOMPRIMIERUNG (00 = keine, 02 = gzip, 03 = ZIP, …)
    komprimierung = Column(String, nullable=False, default="00")

    # 207–208: VERSCHLÜSSELUNGSART (00 = keine, 02 = PKCS#7)
    # Du nutzt PKCS#7-Container per E-Mail → Default "02".
    verschluesselungsart = Column(String, nullable=False, default="02")

    # 209–210: ELEKTRONISCHE_UNTERSCHRIFT (00 = keine, 02 = PKCS#7)
    # Du arbeitest mit papierhaft unterschriebenen Dokumenten → Default "00".
    elektronische_unterschrift = Column(String, nullable=False, default="00")

    # 228–229: max. Anzahl Übertragungswiederholungen (z.B. "03")
    max_wiederholungen = Column(String, nullable=True)

    # 230: Übertragungsweg (5 = anderer Weg, z.B. E-Mail/SMTP)
    uebertragungsweg = Column(String, nullable=True, default="5")

    # ==========================
    # SMTP / E-Mail (Anlage 7 – E-Mail-Verfahren)
    # ==========================

    # SMTP-Serverdaten
    smtp_server = Column(String, nullable=True)
    smtp_port = Column(Integer, nullable=True)
    smtp_user = Column(String, nullable=True)
    smtp_password = Column(String, nullable=True)

    # TLS (STARTTLS) verwenden?
    smtp_use_tls = Column(Boolean, nullable=False, default=True)

    # Absender-E-Mail für den Versand nach Anlage 7
    email_absender = Column(String, nullable=True)

    # optionale Kontaktdaten für den Mail-Body
    kontakt_person = Column(String, nullable=True)
    kontakt_telefon = Column(String, nullable=True)
    kontakt_fax = Column(String, nullable=True)

    # Standard-E-Mail-Adresse der Datenannahmestelle (Fallback,
    # falls beim Kostenträger keine spezifische Annahmestellen-Adresse hinterlegt ist)
    default_annahmestelle_email = Column(String, nullable=True)