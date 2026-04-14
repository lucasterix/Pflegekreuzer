# app/models/kostentraeger.py

from sqlalchemy import Column, Integer, String
from ..db import Base


class Kostentraeger(Base):
    __tablename__ = "kostentraeger"

    id = Column(Integer, primary_key=True, index=True)

    # Name der Pflegekasse / des Kostenträgers
    # ⚠️ NICHT mehr unique, weil derselbe Name in KE0 mit mehreren IKs vorkommen kann
    name = Column(String, nullable=False)

    # Adresse (z.B. "Straße 1, 12345 Ort")
    address = Column(String, nullable=True)

    # Routing-IK / Institutionskennzeichen aus VKG (9-stellig)
    # IK soll systemweit eindeutig sein
    ik = Column(String, nullable=True, unique=True, index=True)

    # Funktionskennzeichen aus FKT+.. (z.B. "01" = aktiv)
    funktionskennzeichen = Column(String, nullable=True)

    # Gültig-ab-Datum aus VDT (im Format JJJJMMTT, z.B. "20100701")
    gueltig_ab = Column(String, nullable=True)

    # Name der Datenannahmestelle (aus JSON-Feld "Datenannahmestelle", z.B. "BITMARCK GmbH")
    annahmestelle = Column(String, nullable=True)

    # IK der Datenannahmestelle (aus JSON-Feld "Datenannahmestelle_IK")
    annahmestelle_ik = Column(String, nullable=True)

    # optionale E-Mail der Datenannahmestelle (aus DFU / JSON-Feld "Daten-E-Mail-Adresse")
    annahmestelle_email = Column(String, nullable=True)

    @property
    def aktiv(self) -> bool:
        """
        Sehr einfache Heuristik:
        - '01' → aktiv
        - alles andere → eher inaktiv / speziell
        (Wir zeigen im Frontend zusätzlich den FKT-Rohcode an.)
        """
        if self.funktionskennzeichen is None:
            # keine Info -> eher als aktiv behandeln
            return True
        return self.funktionskennzeichen == "01"