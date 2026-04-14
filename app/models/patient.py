from sqlalchemy import Column, Integer, String, ForeignKey, Date
from sqlalchemy.orm import relationship

from ..db import Base


class Patient(Base):
    __tablename__ = "patients"

    id = Column(Integer, primary_key=True, index=True)

    # Vollständiger Name des Patienten
    name = Column(String, nullable=False)

    # Versichertennummer (frei als Text)
    versichertennummer = Column(String, nullable=False)

    # Geburtsdatum des Patienten (für PDF zwingend wichtig)
    geburtsdatum = Column(Date, nullable=True)

    # Adresse als Textblock (Straße + PLZ+Ort in einem Feld)
    address = Column(String, nullable=True)

    # Verknüpfung zur Pflegekasse / Kostenträger
    kasse_id = Column(Integer, ForeignKey("kostentraeger.id"), nullable=True)
    kasse = relationship("Kostentraeger")

    # Dateiname des unterschriebenen Erstantrags / Leistungsnachweises (PDF)
    unterschriebener_antrag = Column(String, nullable=True)