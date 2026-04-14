# app/main.py

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse

from .db import Base, engine, SessionLocal
from .models import hilfsmittel, kostentraeger, patient, abrechnung, settings  # noqa: F401
from .models.hilfsmittel import PflegeHilfsmittel
from .routes import ui
from .routes.bank_import import router as bank_router
from .fixtures import PFLEGEHILFSMITTEL_DEFAULTS
from .ke0_import import import_ke0_directory


# ==============================
#   Login / Auth
# ==============================

# App-Login (globaler Zugang)
APP_LOGIN_USER = "abrechnung@froehlichdienste.de"
APP_LOGIN_PASSWORD = "FrohZeit123"
APP_AUTH_COOKIE_NAME = "app_auth"

# Passwort für die Konfig-Seite (separat)
CONFIG_PASSWORD = "Einheitsfront1A+"
AUTH_COOKIE_NAME = "cfg_auth"


def _remove_obsolete_hilfsmittel(db):
    obsolete_names = ["Schutzschürzen (Einmalgebrauch)"]
    deleted = db.query(PflegeHilfsmittel).filter(PflegeHilfsmittel.bezeichnung.in_(obsolete_names)).delete(synchronize_session=False)
    if deleted:
        db.commit()
        print(f"[SEED] Entfernte {deleted} veraltete Pflegehilfsmittel: {', '.join(obsolete_names)}")


def seed_hilfsmittel():
    """
    Initiale Pflegehilfsmittel aus den Fixtures in die Datenbank schreiben,
    falls die Tabelle noch leer ist.
    """
    db = SessionLocal()
    try:
        _remove_obsolete_hilfsmittel(db)
        count = db.query(PflegeHilfsmittel).count()
        if count == 0:
            print("[SEED] Leere Tabelle 'pflegehilfsmittel' – befülle aus Fixtures …")
            for name, cfg in PFLEGEHILFSMITTEL_DEFAULTS.items():
                item = PflegeHilfsmittel(
                    bezeichnung=name,
                    positionsnummer=cfg.get("positionsnummer", ""),
                    kennzeichen=cfg.get("kennzeichen", "00"),
                    packungsgroesse=cfg["qty"],
                    preis_brutto=cfg["price"],
                )
                db.add(item)
            db.commit()
            print("[SEED] Pflegehilfsmittel-Defaults erfolgreich angelegt.")
        else:
            print(f"[SEED] {count} Pflegehilfsmittel bereits vorhanden – kein Seeding nötig.")
    finally:
        db.close()


# ==============================
#   DB-Struktur & Initialdaten
# ==============================
Base.metadata.create_all(bind=engine)
seed_hilfsmittel()
import_ke0_directory()


# ==============================
#   FastAPI-App
# ==============================
app = FastAPI(title="Pflegehilfsmittel Abrechnung (MVP)")


# ==============================
#   Globaler Login-Schutz
# ==============================
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path

    # 1) Öffentliche Pfade (ohne Login erreichbar)
    if (
        path.startswith("/static") or       # CSS, JS, Bilder
        path.startswith("/login") or        # globale Login-Seite
        path.startswith("/config-login") or # Konfig-Login
        path.startswith("/docs") or         # Swagger, falls du es nutzen willst
        path.startswith("/openapi.json") or   # OpenAPI
        path.startswith("/api/bank/")
    ):
        return await call_next(request)

    # 2) Globaler App-Login (Cookie "app_auth")
    app_auth = request.cookies.get(APP_AUTH_COOKIE_NAME)
    if app_auth != "ok":
        # Noch nicht eingeloggt → auf /login
        return RedirectResponse(url="/login", status_code=303)

    # 3) Zusätzlicher Schutz für /config (separate Credentials)
    if path.startswith("/config"):
        cfg_auth = request.cookies.get(AUTH_COOKIE_NAME)
        if cfg_auth != "ok":
            return RedirectResponse(url="/config-login", status_code=303)

    # 4) alles andere normal weiterreichen
    return await call_next(request)


# ==============================
#   Static & Routen
# ==============================
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(ui.router)
app.include_router(bank_router)
