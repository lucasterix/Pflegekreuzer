# app/models/abrechnung.py

from datetime import datetime
from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Numeric,
    ForeignKey,
    Boolean,
)
from sqlalchemy.orm import relationship

from ..db import Base


class Abrechnung(Base):
    __tablename__ = "abrechnungen"

    id = Column(Integer, primary_key=True, index=True)

    # Verknüpfung zum Patienten
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)

    # Verknüpfung zur Pflegekasse / Kostenträger
    kasse_id = Column(Integer, ForeignKey("kostentraeger.id"), nullable=True)

    # Abrechnungsmonat als "YYYY-MM"
    abrechnungsmonat = Column(String, nullable=False)

    # Gesamtbetrag (brutto) für diese Abrechnung
    gesamt_betrag = Column(Numeric(10, 2), nullable=False, default=0)

    # Erstellzeitpunkt der Abrechnung
    created_at = Column(DateTime, default=datetime.utcnow)

    # Zeitpunkt des Versands (E-Mail / Datenaustausch)
    gesendet_am = Column(DateTime, nullable=True)

    # NEU: Storno-Flag + Zeitpunkt
    storniert = Column(Boolean, nullable=False, default=False)
    storniert_am = Column(DateTime, nullable=True)

    # Beziehungen
    patient = relationship("Patient", backref="abrechnungen")
    kasse = relationship("Kostentraeger")
    positionen = relationship(
        "AbrechnungsPosition",
        back_populates="abrechnung",
        cascade="all, delete-orphan",
    )


class AbrechnungsPosition(Base):
    __tablename__ = "abrechnungspositionen"

    id = Column(Integer, primary_key=True, index=True)

    abrechnung_id = Column(Integer, ForeignKey("abrechnungen.id"), nullable=False)
    hilfsmittel_id = Column(Integer, ForeignKey("pflegehilfsmittel.id"), nullable=False)

    menge = Column(Integer, nullable=False)
    einzelpreis = Column(Numeric(10, 2), nullable=False)
    betrag_gesamt = Column(Numeric(10, 2), nullable=False)

    abrechnung = relationship("Abrechnung", back_populates="positionen")
    hilfsmittel = relationship("PflegeHilfsmittel")