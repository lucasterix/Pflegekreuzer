# app/seed_hilfsmittel.py

from app.db import SessionLocal
from app.models.hilfsmittel import PflegeHilfsmittel
from app.fixtures import PFLEGEHILFSMITTEL_DEFAULTS


def _remove_obsolete_hilfsmittel(db):
    obsolete_names = ["Schutzschürzen (Einmalgebrauch)"]
    deleted = db.query(PflegeHilfsmittel).filter(PflegeHilfsmittel.bezeichnung.in_(obsolete_names)).delete(synchronize_session=False)
    if deleted:
        db.commit()
        print(f"[SEED] Entfernte {deleted} veraltete Pflegehilfsmittel: {', '.join(obsolete_names)}")


def seed_hilfsmittel():
    db = SessionLocal()
    try:
        _remove_obsolete_hilfsmittel(db)
        # Wenn schon Daten drin sind, nichts tun
        count = db.query(PflegeHilfsmittel).count()
        if count > 0:
            print(f"[SEED] Pflegehilfsmittel bereits vorhanden ({count} Einträge) – nichts zu tun.")
            return

        print("[SEED] Pflegehilfsmittel werden initial angelegt ...")

        for name, data in PFLEGEHILFSMITTEL_DEFAULTS.items():
            hm = PflegeHilfsmittel(
                bezeichnung=name,
                packungsgroesse=data["qty"],
                preis_brutto=data["price"],
                positionsnummer=data.get("positionsnummer", ""),
                kennzeichen=data.get("kennzeichen", "03"),
            )
            db.add(hm)

        db.commit()
        print("[SEED] Pflegehilfsmittel erfolgreich angelegt.")
    finally:
        db.close()


if __name__ == "__main__":
    seed_hilfsmittel()