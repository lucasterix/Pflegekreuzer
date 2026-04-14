# app/ke0_import.py

from pathlib import Path
from typing import Dict, Any

import json

from .db import SessionLocal
from .models.kostentraeger import Kostentraeger


def _load_pflegekassen_json(base: Path) -> list[Dict[str, Any]]:
    """
    Sucht und lädt die Datei 'pflegekassen.json'.

    Suchreihenfolge:
      1. <base>/pflegekassen.json   (z.B. 'ke0/pflegekassen.json')
      2. ./pflegekassen.json        (Projekt-Root)

    Rückgabe:
      - Liste von Dicts mit den Schlüsseln wie in deiner JSON:
        name,
        address,
        Datenannahmestelle,
        Daten-E-Mail-Adresse,
        Datenannahmestelle_IK,
        Kostenträger_IK
    """
    candidates = [
        base / "pflegekassen.json",
        Path("pflegekassen.json"),
    ]

    json_path: Path | None = None
    for p in candidates:
        if p.exists():
            json_path = p
            break

    if not json_path:
        print("[PFLEGEKASSEN] Keine 'pflegekassen.json' gefunden "
              f"(gesucht in: {', '.join(str(c) for c in candidates)}).")
        return []

    print(f"[PFLEGEKASSEN] Lade Pflegekassen aus {json_path} …")

    with json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        print("[PFLEGEKASSEN] JSON-Format unerwartet – Erwartet wird eine Liste von Objekten.")
        return []

    return data


def import_ke0_directory(dir_path: str | Path = "ke0") -> None:
    """
    JSON-basierter Import der Pflegekassen.

    Liest die Datei 'pflegekassen.json' ein und legt/aktualisiert Kostenträger.

    Mapping:
      - name                        → Kostentraeger.name
      - address                     → Kostentraeger.address
      - Kostenträger_IK             → Kostentraeger.ik   (9-stellig, unique)
      - Daten-E-Mail-Adresse        → Kostentraeger.annahmestelle_email
      - Datenannahmestelle          → Kostentraeger.annahmestelle
      - Datenannahmestelle_IK       → Kostentraeger.annahmestelle_ik

    Bereits in der DB vorhandene Kostenträger (gleiche IK) werden nur
    vorsichtig ergänzt (nur leere Felder werden überschrieben).
    """

    base = Path(dir_path)
    data = _load_pflegekassen_json(base)
    if not data:
        print("[PFLEGEKASSEN] Kein Import durchgeführt (keine Daten).")
        return

    db = SessionLocal()
    try:
        # Bereits vorhandene Kostenträger nach IK indizieren
        existing_by_ik: dict[str, Kostentraeger] = {}
        for k in db.query(Kostentraeger).all():
            if k.ik:
                existing_by_ik[k.ik] = k

        count_new = 0
        count_updated = 0

        for entry in data:
            if not isinstance(entry, dict):
                continue

            name = (entry.get("name") or "").strip()
            address = (entry.get("address") or "").strip()

            # Kostenträger-IK (mit/ohne Umlaut-Variante abfangen)
            ik = (
                (entry.get("Kostenträger_IK") or entry.get("Kostentraeger_IK") or "")
                .strip()
            )

            # Datenannahmestelle (Name + IK) + E-Mail
            annahme_name = (entry.get("Datenannahmestelle") or "").strip()
            annahme_ik = (entry.get("Datenannahmestelle_IK") or "").strip()
            annahme_email = (
                entry.get("Daten-E-Mail-Adresse")
                or entry.get("Daten_Email_Adresse")
                or ""
            )
            annahme_email = annahme_email.strip()

            # Plausibilität IK
            if not ik or not ik.isdigit() or len(ik) != 9:
                print(f"[PFLEGEKASSEN] Überspringe Eintrag ohne gültige IK: {name!r} / IK={ik!r}")
                continue

            if not name:
                name = f"Kostenträger {ik}"

            existing = existing_by_ik.get(ik)

            if existing:
                # behutsam aktualisieren – nur leere Felder füllen
                changed = False

                if not existing.name and name:
                    existing.name = name
                    changed = True

                if (not existing.address) and address:
                    existing.address = address
                    changed = True

                if annahme_email and not getattr(existing, "annahmestelle_email", None):
                    existing.annahmestelle_email = annahme_email
                    changed = True

                if annahme_name and not getattr(existing, "annahmestelle", None):
                    existing.annahmestelle = annahme_name
                    changed = True

                if annahme_ik and not getattr(existing, "annahmestelle_ik", None):
                    existing.annahmestelle_ik = annahme_ik
                    changed = True

                if changed:
                    count_updated += 1

                continue

            # Neuer Kostenträger
            new_kasse = Kostentraeger(
                name=name,
                address=address or None,
                ik=ik,
                funktionskennzeichen=None,
                gueltig_ab=None,
                annahmestelle_email=annahme_email or None,
            )

            # Weitere Felder nachträglich setzen (crasht nicht, wenn Spalte fehlt)
            if annahme_name:
                new_kasse.annahmestelle = annahme_name
            if annahme_ik:
                new_kasse.annahmestelle_ik = annahme_ik

            db.add(new_kasse)
            existing_by_ik[ik] = new_kasse
            count_new += 1

        db.commit()
        print(f"[PFLEGEKASSEN] Import abgeschlossen. Neu: {count_new}, aktualisiert: {count_updated}.")
    finally:
        db.close()