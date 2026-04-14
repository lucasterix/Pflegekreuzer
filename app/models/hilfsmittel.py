from sqlalchemy import Column, Integer, String, Numeric
from ..db import Base

class PflegeHilfsmittel(Base):
    __tablename__ = "pflegehilfsmittel"

    id = Column(Integer, primary_key=True, index=True)

    # z.B. "Einmalhandschuhe"
    bezeichnung = Column(String, nullable=False, unique=True)

    # z.B. HMV-Nummer oder interner Code – vorerst Platzhalter
    positionsnummer = Column(String, nullable=False, default="")

    # Kennzeichen Pflegehilfsmittel:
    # z.B. "03" = Verbrauchsartikel (Platzhalter für jetzt)
    kennzeichen = Column(String, nullable=False, default="03")

    # Anzahl Stück pro Packung (dein qty)
    packungsgroesse = Column(Integer, nullable=False)

    # Preis brutto pro Packung
    preis_brutto = Column(Numeric(10, 2), nullable=False)