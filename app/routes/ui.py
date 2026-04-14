# app/routes/ui.py

from fastapi import (
    APIRouter,
    Request,
    Form,
    Depends,
    UploadFile,
    File,
    HTTPException,
    Query,
)
from fastapi.responses import (
    RedirectResponse,
    FileResponse,
    StreamingResponse,
    JSONResponse,
    HTMLResponse,
)
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func
from decimal import Decimal
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Tuple
from weasyprint import HTML
from PyPDF2 import PdfReader as LegacyPdfReader
from pypdf import PdfReader, PdfWriter
from io import BytesIO

import xml.etree.ElementTree as ET
import base64
import uuid
import urllib.parse
import os
import json
import shutil

from ..db import SessionLocal
from ..models.hilfsmittel import PflegeHilfsmittel
from ..models.kostentraeger import Kostentraeger
from ..models.patient import Patient
from ..models.abrechnung import Abrechnung, AbrechnungsPosition
from ..models.settings import Einstellungen
from ..validation import validate_pfl_file
from ..edifact import build_edifact_from_abrechnung
from ..signing import sign_edifact
from ..auftrag import build_auftragssatz
from ..email_transport import send_datenaustausch_mail
from ..pdf_simple import make_invoice_pdf
from ..pdf_patient_parser import parse_patient_from_pdf_text
from ..pdf_pflegeantrag import render_pflegeantrag
from ..pdf_antrag_kasse import render_antrag_kasse
from ..pdf_unterschrift_eins import render_unterschrift_eins
from app.pdf_signature import extract_signature_from_pflegeantrag
from app.pdf_tools import render_anlage3, render_unterschrift_zwei
from app.pdf_combine import combine_pdfs
from ..config import (
    APP_LOGIN_USER,
    APP_LOGIN_PASSWORD,
    CONFIG_PASSWORD,
    APP_AUTH_COOKIE_NAME,
    APP_AUTH_COOKIE_SECRET,
    AUTH_COOKIE_NAME,
    CFG_AUTH_COOKIE_SECRET,
    SESSION_COOKIE_SECURE,
    SESSION_COOKIE_SAMESITE,
)
from ..auth import (
    create_signed_cookie,
    verify_signed_cookie,
    verify_password,
)

# ==============================
#   Tarifkennzeichen-Defaults (TA3)
# ==============================
TARIFKENNZEICHEN_DEFAULTS: dict[str, str] = {
    "BW": "01000",  # Baden-Württemberg
    "BY": "02000",  # Bayern
    "HE": "06000",  # Hessen
    "NI": "07000",  # Niedersachsen
    "NW": "08000",  # Nordrhein-Westfalen
    "BE": "23000",  # Berlin
}

# Dummy-Mail für Testbetrieb (falls keine echte Annahmestellen-Mail hinterlegt ist)
DUMMY_KASSEN_EMAIL = "dummy-kasse@example.org"

# Standard-MwSt (wird im Code aber durch cfg.ust_… übersteuert, wo sinnvoll)
MWST_DEFAULT = Decimal("0.19")

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


# ==============================
#   DB-Session Helper
# ==============================
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ==============================
#   Namespaces PFL_DAT / BASIS / ABR
# ==============================
NS_DAT = "http://www.gkv-datenaustausch.de/XMLSchema/PFL_DAT/2.2"
NS_BAS = "http://www.gkv-datenaustausch.de/XMLSchema/PFL_basis/2.2"
NS_ABR = "http://www.gkv-datenaustausch.de/XMLSchema/PFL_ABR/2.2"

ET.register_namespace("dat", NS_DAT)
ET.register_namespace("bas", NS_BAS)
ET.register_namespace("abr", NS_ABR)

def get_abrechnung_export_dir(abrechnung: Abrechnung) -> Path:
    """
    Liefert den Archiv-Ordner für eine Abrechnung:

    exports/
      <patient_id>_<slug-name>/
        <abrechnungsmonat>/

    Beispiel:
      exports/12_Lucas_Schmutz/2025-03/
    """
    patient = abrechnung.patient

    raw_name = (patient.name or f"patient_{abrechnung.patient_id}").strip()
    safe_name = (
        "".join(c for c in raw_name if c.isalnum() or c in ("-", "_", " "))
        .strip()
        .replace(" ", "_")
        or f"patient_{abrechnung.patient_id}"
    )

    base = Path("exports")
    patient_dir = base / f"{abrechnung.patient_id}_{safe_name}"
    month_dir = patient_dir / abrechnung.abrechnungsmonat

    month_dir.mkdir(parents=True, exist_ok=True)
    return month_dir


def get_patient_export_dir(patient: Patient) -> Path:
    """
    Liefert den Export-Ordner für patientenbezogene Dateien
    (z.B. unterschriebener Antrag):

    exports/
      <patient_id>_<slug-name>/

    Beispiel:
      exports/12_Lucas_Schmutz/
    """
    raw_name = (patient.name or f"patient_{patient.id}").strip()
    safe_name = (
        "".join(c for c in raw_name if c.isalnum() or c in ("-", "_", " "))
        .strip()
        .replace(" ", "_")
        or f"patient_{patient.id}"
    )

    base = Path("exports")
    patient_dir = base / f"{patient.id}_{safe_name}"
    patient_dir.mkdir(parents=True, exist_ok=True)
    return patient_dir


# ==============================
#   Startseite
# ==============================
@router.get("/")
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# ==============================
#   Pflegehilfsmittel
# ==============================
@router.get("/hilfsmittel")
def list_hilfsmittel(request: Request, db: Session = Depends(get_db)):
    items = db.query(PflegeHilfsmittel).all()
    return templates.TemplateResponse(
        "hilfsmittel.html",
        {"request": request, "items": items},
    )


@router.post("/hilfsmittel")
def create_hilfsmittel(
    bezeichnung: str = Form(...),
    positionsnummer: str = Form(...),
    kennzeichen: str = Form(...),
    packungsgroesse: int = Form(...),
    preis_brutto: float = Form(...),
    db: Session = Depends(get_db),
):
    item = PflegeHilfsmittel(
        bezeichnung=bezeichnung,
        positionsnummer=positionsnummer,
        kennzeichen=kennzeichen,
        packungsgroesse=packungsgroesse,
        preis_brutto=preis_brutto,
    )
    db.add(item)
    db.commit()
    return RedirectResponse(url="/hilfsmittel", status_code=303)


# ==============================
#   Kostenträger
# ==============================
@router.get("/kassen")
def list_kassen(request: Request, db: Session = Depends(get_db)):
    items = db.query(Kostentraeger).order_by(Kostentraeger.name.asc()).all()
    return templates.TemplateResponse(
        "kassen.html",
        {"request": request, "items": items},
    )


# ==============================
#   Patienten
# ==============================
@router.get("/patients")
def list_patients(request: Request, db: Session = Depends(get_db)):
    patients = db.query(Patient).order_by(Patient.name.asc()).all()
    kassen = db.query(Kostentraeger).order_by(Kostentraeger.name.asc()).all()
    return templates.TemplateResponse(
        "patients.html",
        {"request": request, "patients": patients, "kassen": kassen},
    )


@router.post("/patients/{patient_id}/update")
def update_patient(
    patient_id: int,
    name: str = Form(...),
    versichertennummer: str = Form(...),
    geburtsdatum: str = Form(""),
    address: str = Form(""),
    kasse_id: str = Form(""),
    db: Session = Depends(get_db),
):
    patient = db.get(Patient, patient_id)
    if not patient:
        return RedirectResponse(url="/patients", status_code=303)

    patient.name = name
    patient.versichertennummer = versichertennummer

    # Geburtsdatum aktualisieren (optional)
    if geburtsdatum.strip():
        try:
            patient.geburtsdatum = datetime.strptime(
                geburtsdatum.strip(), "%Y-%m-%d"
            ).date()
        except ValueError:
            # Ungültiges Datum ignorieren
            pass

    patient.address = address or None
    patient.kasse_id = int(kasse_id) if kasse_id else None

    db.add(patient)
    db.commit()

    return RedirectResponse(url="/patients", status_code=303)


@router.post("/patients/{patient_id}/delete")
def delete_patient(
    patient_id: int,
    db: Session = Depends(get_db),
):
    patient = db.get(Patient, patient_id)
    if not patient:
        return RedirectResponse(url="/patients", status_code=303)

    # Alle Abrechnungen + Positionen zu diesem Patienten entfernen
    abrechnungen = db.query(Abrechnung).filter(Abrechnung.patient_id == patient_id).all()
    for abr in abrechnungen:
        # Positionen der Abrechnung löschen
        for pos in list(abr.positionen):
            db.delete(pos)
        # Abrechnung selbst löschen
        db.delete(abr)

    # Jetzt den Patienten löschen
    db.delete(patient)

    try:
        db.commit()
    except Exception:
        db.rollback()
    return RedirectResponse(url="/patients", status_code=303)


@router.post("/patients/{patient_id}/antrag_upload")
async def upload_unterschriebener_antrag(
    patient_id: int,
    antrag_pdf: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    Speichert einen unterschriebenen Antrag als PDF im Patienten-Ordner:
      exports/<id>_<Name>/Unterschriebener_Antrag.pdf
    und hinterlegt den vollen Pfad in patient.unterschriebener_antrag.
    """
    patient = db.get(Patient, patient_id)
    if not patient:
        return HTMLResponse("Patient nicht gefunden.", status_code=404)

    # Nur PDF akzeptieren (grober Check)
    content_type = (antrag_pdf.content_type or "").lower()
    filename_lower = (antrag_pdf.filename or "").lower()

    if "pdf" not in content_type and not filename_lower.endswith(".pdf"):
        return HTMLResponse("Bitte eine PDF-Datei hochladen.", status_code=400)

    # Zielordner: exports/<id>_<Name>/
    base_dir = get_patient_export_dir(patient)
    target_path = base_dir / "Unterschriebener_Antrag.pdf"

    data = await antrag_pdf.read()
    with target_path.open("wb") as f:
        f.write(data)

    # Pfad in der DB merken (voller Pfad als String)
    patient.unterschriebener_antrag = str(target_path)
    db.add(patient)
    db.commit()

    # Frontend erwartet nur ok + reload
    return JSONResponse({"ok": True})


@router.get("/patients/{patient_id}/antrag_download")
def download_unterschriebener_antrag(
    patient_id: int,
    db: Session = Depends(get_db),
):
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient nicht gefunden")

    if not patient.unterschriebener_antrag:
        raise HTTPException(
            status_code=404,
            detail="Kein unterschriebener Antrag hochgeladen",
        )

    filepath = Path(patient.unterschriebener_antrag)
    if not filepath.is_file():
        raise HTTPException(status_code=404, detail="Datei fehlt auf dem Server")

    return FileResponse(
        path=str(filepath),
        media_type="application/pdf",
        filename=filepath.name,
    )


@router.post("/patients")
def create_patient(
    name: str = Form(...),
    versichertennummer: str = Form(...),
    geburtsdatum: str = Form(""),
    address: str = Form(""),
    kasse_id: str = Form(""),
    db: Session = Depends(get_db),
):
    # Geburtsdatum optional parsen (YYYY-MM-DD vom <input type="date">)
    geburtsdatum_dt = None
    if geburtsdatum.strip():
        try:
            geburtsdatum_dt = datetime.strptime(
                geburtsdatum.strip(), "%Y-%m-%d"
            ).date()
        except ValueError:
            geburtsdatum_dt = None  # ungültiges Datum ignorieren

    patient = Patient(
        name=name,
        versichertennummer=versichertennummer,
        geburtsdatum=geburtsdatum_dt,
        address=address or None,
        kasse_id=int(kasse_id) if kasse_id else None,
    )
    db.add(patient)
    db.commit()
    return RedirectResponse(url="/patients", status_code=303)


# ==============================
#   Abrechnungen – Erfassung
# ==============================
@router.get("/abrechnungen")
def list_abrechnungen(
    request: Request,
    monat: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    Abrechnungsübersicht mit Monatsfokus.
    """
    if not monat:
        monat = datetime.now().strftime("%Y-%m")

    # Nur NICHT stornierte Abrechnungen dieses Monats anzeigen
    abrechnungen_monat = (
        db.query(Abrechnung)
        .filter(
            Abrechnung.abrechnungsmonat == monat,
            Abrechnung.storniert.is_(False),
        )
        .order_by(Abrechnung.created_at.asc())
        .all()
    )

    patients_all = db.query(Patient).order_by(Patient.name.asc()).all()

    # "Letzter abgerechneter Monat" nur aus NICHT stornierten Abrechnungen
    letzte_monate_raw = (
        db.query(
            Abrechnung.patient_id,
            func.max(Abrechnung.abrechnungsmonat),
        )
        .filter(Abrechnung.storniert.is_(False))
        .group_by(Abrechnung.patient_id)
        .all()
    )
    letzte_monate_by_patient = {pid: abr_monat for (pid, abr_monat) in letzte_monate_raw}

    # Zusätzlich: erster abgerechneter Monat pro Patient (für Erstversorgung)
    erste_monate_raw = (
        db.query(
            Abrechnung.patient_id,
            func.min(Abrechnung.abrechnungsmonat),
        )
        .filter(Abrechnung.storniert.is_(False))
        .group_by(Abrechnung.patient_id)
        .all()
    )
    erste_monate_by_patient = {pid: abr_monat for (pid, abr_monat) in erste_monate_raw}

    for p in patients_all:
        setattr(p, "letzter_abrechnungsmonat", letzte_monate_by_patient.get(p.id))
        export_dir = get_patient_export_dir(p)
        antrag_path = export_dir / f"Antrag_inkl_Unterschrift_{p.name.replace(' ', '_')}.pdf"
        setattr(p, "antrag_generiert", bool(getattr(p, "antrag_generiert", False)) or antrag_path.exists())

    # Patienten, die für diesen Monat bereits eine (nicht stornierte) Abrechnung haben
    patient_ids_mit_abrechnung_monat = {a.patient_id for a in abrechnungen_monat}

    offene_patients: List[Patient] = []
    bereits_abgerechnete_patients: List[Patient] = []

    for p in patients_all:
        if p.id in patient_ids_mit_abrechnung_monat:
            bereits_abgerechnete_patients.append(p)
        else:
            offene_patients.append(p)

    hilfsmittel = db.query(PflegeHilfsmittel).all()

    # Patient, der in DIESEM Monat zum ersten Mal abgerechnet wird?
    erste_abrechnung = None
    for a in abrechnungen_monat:
        first_month = erste_monate_by_patient.get(a.patient_id)
        if first_month == monat:
            erste_abrechnung = a
            break

    # Hinweistext für den Nutzer (z. B. "Antrag erfolgreich erzeugt")
    hinweis_text = None
    if request.query_params.get("antrag_generiert") == "1":
        hinweis_text = "✅ Antrag Krankenkasse wurde erfolgreich im Export gespeichert."

    return templates.TemplateResponse(
        "abrechnungen.html",
        {
            "request": request,
            "monat": monat,
            "offene_patients": offene_patients,
            "bereits_abgerechnete_patients": bereits_abgerechnete_patients,
            "abrechnungen_monat": abrechnungen_monat,
            "hilfsmittel": hilfsmittel,
            "erste_abrechnung": erste_abrechnung,  # <-- für Antrag Krankenkasse
            "hinweis_text": hinweis_text,          # <-- optional für UI
        },
    )


@router.get("/patients/{patient_id}/pflegeantrag")
def generate_pflegeantrag(
    patient_id: int,
    db: Session = Depends(get_db),
):
    patient = db.get(Patient, patient_id)
    if not patient:
        return RedirectResponse(url="/patients", status_code=303)

    kasse = patient.kasse

    geburtsdatum_str = (
        patient.geburtsdatum.strftime("%d.%m.%Y")
        if getattr(patient, "geburtsdatum", None)
        else ""
    )

    data = {
        "name": patient.name or "",
        "geburtsdatum": geburtsdatum_str,
        "versichertennr": patient.versichertennummer or "",
        "anschrift": patient.address or "",
        "pflegekasse": kasse.name if kasse else "",
    }

    # Pfad zur PDF-Vorlage anpassen, falls du sie anders ablegst
    template_path = str(Path("app/static/Pflegeantrag.pdf"))

    pdf_buf = render_pflegeantrag(template_path, data)

    # Dateiname etwas hübsch machen
    raw_name = (patient.name or f"patient_{patient.id}").strip()
    safe_name = (
        "".join(c for c in raw_name if c.isalnum() or c in ("-", "_", " "))
        .strip()
        .replace(" ", "_")
        or f"patient_{patient.id}"
    )

    filename = f"Pflegeantrag_{safe_name}.pdf"

    return StreamingResponse(
        pdf_buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/abrechnungen/{abrechnung_id}/antrag_kasse")
def generate_antrag_kasse(
    abrechnung_id: int,
    beratung_datum: Optional[str] = Query(None),
    beratung_mitarbeiter: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Erzeugt antrag.pdf mit Daten aus der Abrechnung als Overlay.
    Wird aus abrechnungen.html über den Button "Antrag Krankenkasse generieren"
    aufgerufen, inkl. Beratungsgesprächs-Datum & -Mitarbeiter.
    """
    abrechnung = db.get(Abrechnung, abrechnung_id)
    if not abrechnung:
        raise HTTPException(status_code=404, detail="Abrechnung nicht gefunden")

    patient = abrechnung.patient
    if not patient:
        raise HTTPException(
            status_code=400, detail="Abrechnung hat keinen Patienten"
        )

    # Pflegekasse: aus Abrechnung, sonst aus Patient
    kasse = abrechnung.kasse or getattr(patient, "kasse", None)
    kasse_name = kasse.name if kasse else ""

    # Produkte: Hilfsmittel-Bezeichnung -> Menge in Packungen
    produkte: dict[str, int] = {}
    for pos in abrechnung.positionen:
        hm = getattr(pos, "hilfsmittel", None)
        if not hm:
            continue
        name = hm.bezeichnung
        qty = int(getattr(pos, "menge", 0) or 0)
        produkte[name] = produkte.get(name, 0) + qty

    data = {
        "name": patient.name or "",
        "geburtsdatum": patient.geburtsdatum.strftime("%d.%m.%Y")
        if patient.geburtsdatum
        else "",
        "versichertennr": patient.versichertennummer or "",
        "anschrift": patient.address or "",
        "pflegekasse": kasse_name,
        "produkte": produkte,
        "beratung_datum": beratung_datum or "",
        "beratung_mitarbeiter": beratung_mitarbeiter or "",
    }

    # Pfad zu antrag.pdf – leg die Datei z.B. unter app/static/antrag.pdf ab
    template_path = str(Path("app/static/antrag.pdf"))

    pdf_buf = render_antrag_kasse(template_path, data)

    filename = f"Antrag_Krankenkasse_Abrechnung_{abrechnung.id}.pdf"
    headers = {"Content-Disposition": f'inline; filename="{filename}"'}
    return StreamingResponse(pdf_buf, media_type="application/pdf", headers=headers)


# oben im File ergänzen:
# import json  (ist oben schon importiert)


@router.get("/patients/{patient_id}/antrag_kasse")
def generate_antrag_kasse_patient(
    patient_id: int,
    beratung_datum: Optional[str] = Query(None),
    beratung_mitarbeiter: Optional[str] = Query(None),
    produkte_json: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Erzeugt einen Antrag für die Krankenkasse auf Basis von antrag.pdf,
    direkt aus der Erfassungsmaske heraus (ohne gespeicherte Abrechnung).

    Produkte (Hilfsmittel + Mengen) kommen als JSON über 'produkte_json'
    aus dem Frontend und werden zusätzlich im Patienten-Export-Ordner
    archiviert.
    """
    patient = db.get(Patient, patient_id)
    if not patient:
        return RedirectResponse(url="/patients", status_code=303)

    kasse = patient.kasse

    geburtsdatum_str = (
        patient.geburtsdatum.strftime("%d.%m.%Y")
        if getattr(patient, "geburtsdatum", None)
        else ""
    )

    # Produkte aus JSON übernehmen: { "Saugende Bettschutzeinlage (Einmalgebrauch)": 2, ... }
    produkte: dict[str, int] = {}
    if produkte_json:
        try:
            raw = json.loads(produkte_json)
            if isinstance(raw, dict):
                for k, v in raw.items():
                    try:
                        q = int(v)
                    except (TypeError, ValueError):
                        q = 0
                    if q > 0:
                        produkte[str(k)] = q
        except json.JSONDecodeError:
            pass

    data = {
        "name": patient.name or "",
        "geburtsdatum": geburtsdatum_str,
        "versichertennr": patient.versichertennummer or "",
        "anschrift": patient.address or "",
        "pflegekasse": kasse.name if kasse else "",
        "produkte": produkte,
        "beratung_datum": beratung_datum or "",
        "beratung_mitarbeiter": beratung_mitarbeiter or "",
    }

    template_path = str(Path("app/static/antrag.pdf"))

    pdf_buf = render_antrag_kasse(template_path, data)

    # Hübscher Dateiname
    raw_name = (patient.name or f"patient_{patient.id}").strip()
    safe_name = (
        "".join(c for c in raw_name if c.isalnum() or c in ("-", "_", " "))
        .strip()
        .replace(" ", "_")
        or f"patient_{patient.id}"
    )

    filename = f"Antrag_Krankenkasse_{safe_name}.pdf"

    # 🗂️ Im Patienten-Export-Ordner speichern
    export_dir = get_patient_export_dir(patient)
    export_dir.mkdir(parents=True, exist_ok=True)
    file_path = export_dir / filename

    pdf_bytes = pdf_buf.getvalue()
    with file_path.open("wb") as f:
        f.write(pdf_bytes)

    # Für den Download noch einmal als Stream zurückgeben
    pdf_stream = BytesIO(pdf_bytes)

    return StreamingResponse(
        pdf_stream,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

# ==============================
#   Globaler Login
# ==============================
@router.get("/login")
def login_form(request: Request):
    error = request.query_params.get("error")
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": error},
    )


@router.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    u = (username or "").strip()
    p = (password or "").strip()

    if u == APP_LOGIN_USER and verify_password(p, APP_LOGIN_PASSWORD):
        resp = RedirectResponse(url="/", status_code=303)
        token = create_signed_cookie("ok", APP_AUTH_COOKIE_SECRET)
        resp.set_cookie(
            APP_AUTH_COOKIE_NAME,
            token,
            max_age=60 * 60 * 8,
            httponly=True,
            secure=SESSION_COOKIE_SECURE,
            samesite=SESSION_COOKIE_SAMESITE,
        )
        return resp

    # Falsche Logindaten → Fehler anzeigen
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "error": "Benutzername oder Passwort ist falsch.",
        },
        status_code=401,
    )


@router.get("/logout")
def logout():
    resp = RedirectResponse(url="/login", status_code=303)
    # Cookie löschen
    resp.delete_cookie(APP_AUTH_COOKIE_NAME)
    return resp

@router.get("/patients/{patient_id}/unterschrift_eins")
def generate_unterschrift_eins_patient(
    patient_id: int,
    beratung_datum: str | None = Query(None),
    beratung_mitarbeiter: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """
    Erstellt unterschrift_eins.pdf.
    Falls ein unterschriebener Antrag existiert, wird daraus automatisch
    die Signatur extrahiert und in das neue PDF integriert.
    """
    from pathlib import Path as _Path

    patient = db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient nicht gefunden")

    # 1️⃣ Pfad zum unterschriebenen Antrag finden
    signed_pdf_path = None
    if getattr(patient, "unterschriebener_antrag", None):
        p = _Path(patient.unterschriebener_antrag)
        if p.is_file():
            signed_pdf_path = p
    else:
        # Fallback: älteres Archivschema
        legacy = _Path(f"app/static/archiv/patient_{patient_id}/pflegeantrag_unterschrieben.pdf")
        if legacy.is_file():
            signed_pdf_path = legacy

    # 2️⃣ Signatur extrahieren (falls vorhanden)
    signature_png_buf = None
    if signed_pdf_path and signed_pdf_path.exists():
        try:
            signature_png_buf = extract_signature_from_pflegeantrag(str(signed_pdf_path))
            print(f"[SIGNATURE] Erfolgreich extrahiert aus {signed_pdf_path}")
        except Exception as e:
            print("[SIGNATURE] Fehler beim Extrahieren:", repr(e))
            signature_png_buf = None
    else:
        print("[SIGNATURE] Kein unterschriebener Antrag gefunden")

    # 3️⃣ Daten für das PDF
    data = {
        "name": patient.name or "",
        "beratung_datum": beratung_datum or "",
        "beratung_mitarbeiter": beratung_mitarbeiter or "",
        "signature_png": signature_png_buf,  # kann None sein
    }

    # 4️⃣ PDF erzeugen
    template_path = str(Path("app/static/unterschrift_eins.pdf"))
    out_buf = render_unterschrift_eins(template_path, data)

    # 5️⃣ Datei im Patienten-Exportordner speichern
    raw_name = (patient.name or f"patient_{patient.id}").strip()
    safe_name = (
        "".join(c for c in raw_name if c.isalnum() or c in ("-", "_", " "))
        .strip()
        .replace(" ", "_")
        or f"patient_{patient.id}"
    )

    monat_str = datetime.now().strftime("%Y-%m")
    filename = f"Beratungsnachweis_{safe_name}_{monat_str}.pdf"

    export_dir = get_patient_export_dir(patient)
    export_dir.mkdir(parents=True, exist_ok=True)
    save_path = export_dir / filename

    with save_path.open("wb") as f:
        f.write(out_buf.getvalue())

    out_buf.seek(0)

    print(f"[PDF] Beratungsnachweis gespeichert unter {save_path}")

    # 6️⃣ Zurückgeben als Download
    return StreamingResponse(
        out_buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/archiv/{patient_id}/antrag_download")
def download_archived_antrag_inkl_unterschrift(
    patient_id: int,
    db: Session = Depends(get_db),
):
    """
    Liefert die archivierte PDF-Datei 'Antrag_inkl_Unterschrift_<name>.pdf'
    aus dem Export-Ordner des Patienten.
    Kein Neurendern, nur Download der vorhandenen Datei.
    """
    patient = db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient nicht gefunden.")

    export_dir = get_patient_export_dir(patient)
    if not export_dir.exists():
        raise HTTPException(status_code=404, detail="Export-Ordner nicht gefunden.")

    # Den Patientennamen in eine saubere Form bringen (wie beim Speichern)
    raw_name = (patient.name or f"patient_{patient.id}").strip()
    safe_name = (
        "".join(c for c in raw_name if c.isalnum() or c in ("-", "_", " "))
        .strip()
        .replace(" ", "_")
        or f"patient_{patient.id}"
    )

    # Gespeicherter Antrag heißt immer so:
    filename = f"Antrag_inkl_Unterschrift_{safe_name}.pdf"
    file_path = export_dir / filename

    # Wenn Datei fehlt, prüfe, ob evtl. ähnliche Varianten existieren (z. B. mit Datum)
    if not file_path.exists():
        matches = sorted(
            export_dir.glob(f"Antrag_inkl_Unterschrift_{safe_name}*.pdf"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if matches:
            file_path = matches[0]
        else:
            raise HTTPException(
                status_code=404,
                detail=f"Archivierter Antrag '{filename}' wurde nicht gefunden.",
            )

    return FileResponse(
        path=str(file_path),
        media_type="application/pdf",
        filename=file_path.name,
    )


@router.get("/patients/{patient_id}/antrag_komplett")
def generate_antrag_komplett(
    patient_id: int,
    produkte_json: str | None = Query(None),
    beratung_datum: str | None = Query(None),
    beratung_mitarbeiter: str | None = Query(None),
    monat: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """
    Erzeugt EIN kombiniertes PDF:
      - Seite 1: Antrag Krankenkasse (antrag.pdf)
      - Seite 2: Beratungsnachweis/Unterschrift (mit Signatur)
    """
    patient = db.get(Patient, patient_id)
    if not patient:
        return RedirectResponse(url="/patients", status_code=303)

    # Produkte aus JSON (vom Frontend)
    try:
        produkte = json.loads(produkte_json or "{}")
    except Exception:
        produkte = {}

    # ---------- Antrag Krankenkasse ----------
    antrag_data = {
        "name": patient.name or "",
        "geburtsdatum": patient.geburtsdatum.strftime("%d.%m.%Y")
        if getattr(patient, "geburtsdatum", None)
        else "",
        "versichertennr": patient.versichertennummer or "",
        "anschrift": patient.address or "",
        "pflegekasse": patient.kasse.name if getattr(patient, "kasse", None) else "",
        "produkte": produkte,
        "beratung_datum": beratung_datum or "",
        "beratung_mitarbeiter": beratung_mitarbeiter or "",
    }
    antrag_template = str(Path("app/static/antrag.pdf"))
    antrag_buf = render_antrag_kasse(antrag_template, antrag_data)
    antrag_buf.seek(0)

    # ---------- Unterschriftsseite ----------
    signature_png_buf = None
    if getattr(patient, "unterschriebener_antrag", None):
        p = Path(patient.unterschriebener_antrag)
        if p.exists():
            try:
                signature_png_buf = extract_signature_from_pflegeantrag(str(p))
                print(f"[SIGNATURE] Signatur für Antrag-Komplett extrahiert aus {p}")
            except Exception as e:
                print("[SIGNATURE] Fehler bei Antrag-Komplett:", repr(e))

    unterschrift_data = {
        "name": patient.name or "",
        "beratung_datum": beratung_datum or "",
        "beratung_mitarbeiter": beratung_mitarbeiter or "",
        "signature_png": signature_png_buf,
    }
    unterschrift_template = str(Path("app/static/unterschrift_eins.pdf"))
    unterschrift_buf = render_unterschrift_eins(unterschrift_template, unterschrift_data)
    unterschrift_buf.seek(0)

    # ---------- Zusammenführen ----------
    writer = PdfWriter()
    antrag_reader = PdfReader(antrag_buf)
    unterschrift_reader = PdfReader(unterschrift_buf)

    for page in antrag_reader.pages:
        writer.add_page(page)
    for page in unterschrift_reader.pages:
        writer.add_page(page)

    out_buf = BytesIO()
    writer.write(out_buf)
    out_buf.seek(0)

    # ---------- Speichern & Stream ----------
    raw_name = (patient.name or f"patient_{patient.id}").strip()
    safe_name = (
        "".join(c for c in raw_name if c.isalnum() or c in ("-", "_", " "))
        .strip()
        .replace(" ", "_")
        or f"patient_{patient.id}"
    )
    filename = f"Antrag_inkl_Unterschrift_{safe_name}.pdf"

    export_dir = get_patient_export_dir(patient)
    export_dir.mkdir(parents=True, exist_ok=True)
    file_path = export_dir / filename
    with file_path.open("wb") as f:
        f.write(out_buf.getvalue())

    out_buf.seek(0)
    patient.antrag_generiert = True
    db.add(patient)
    db.commit()
    return StreamingResponse(
        out_buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/patients/{patient_id}/antrag_final_download")
def download_antrag_final(patient_id: int, db: Session = Depends(get_db)):
    """
    Lädt den finalen Antrag (Antrag_inkl_Unterschrift_<Name>.pdf) aus dem Export-Archiv.
    """
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient nicht gefunden")

    export_dir = get_patient_export_dir(patient)
    safe_name = patient.name.replace(" ", "_")
    filename = f"Antrag_inkl_Unterschrift_{safe_name}.pdf"
    file_path = export_dir / filename

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Finaler Antrag nicht gefunden")

    return FileResponse(
        path=file_path,
        filename=filename,
        media_type="application/pdf",
    )


@router.post("/abrechnungen/{abrechnung_id}/storno")
def storno_abrechnung(
    abrechnung_id: int,
    monat: str = Form(...),
    db: Session = Depends(get_db),
):
    """
    Markiert eine Abrechnung als storniert.
    Die Daten bleiben im Archiv sichtbar, erscheinen aber nicht mehr
    in der laufenden Monatsübersicht / beim Versand.
    """
    abr = db.get(Abrechnung, abrechnung_id)
    if not abr:
        return RedirectResponse(
            url=f"/abrechnungen?monat={monat}", status_code=303
        )

    if abr.storniert:
        return RedirectResponse(
            url=f"/abrechnungen?monat={monat}", status_code=303
        )

    abr.storniert = True
    abr.storniert_am = datetime.utcnow()
    db.add(abr)
    db.commit()

    return RedirectResponse(
        url=f"/abrechnungen?monat={monat}",
        status_code=303,
    )


# ==============================
#   Konfig-Login (Template-basiert)
# ==============================
@router.get("/config-login")
def config_login_form(request: Request, error: str | None = None):
    return templates.TemplateResponse(
        "config_login.html", {"request": request, "error": error}
    )


@router.post("/config-login")
async def config_login_submit(
    request: Request,
    password: str = Form(...),
):
    pw = (password or "").strip()

    if verify_password(pw, CONFIG_PASSWORD):
        resp = RedirectResponse(url="/config", status_code=303)
        token = create_signed_cookie("ok", CFG_AUTH_COOKIE_SECRET)
        resp.set_cookie(
            AUTH_COOKIE_NAME,
            token,
            max_age=60 * 60 * 8,  # 8 Stunden
            httponly=True,
            secure=SESSION_COOKIE_SECURE,
            samesite=SESSION_COOKIE_SAMESITE,
        )
        return resp

    # Falsches Passwort
    return templates.TemplateResponse(
        "config_login.html",
        {
            "request": request,
            "error": "Falsches Passwort. Der Steuermann lässt dich noch nicht an die Stellschrauben. 🚢",
        },
        status_code=401,
    )


@router.post("/abrechnungen")
def create_abrechnung(
    patient_id: int = Form(...),
    abrechnungsmonat: str = Form(...),
    hilfsmittel_id: List[str] = Form(...),
    menge: List[str] = Form(...),
    storniere_alt: str = Form("0"),
    beratung_datum: str = Form(""),
    beratung_mitarbeiter: str = Form(""),
    db: Session = Depends(get_db),
):
    patient = db.get(Patient, patient_id)
    if not patient:
        return RedirectResponse(url="/abrechnungen", status_code=303)

    # 👉 Merken, ob es VOR dieser Abrechnung schon eine Abrechnung für diesen Patienten gab
    hatte_schon_abrechnung = (
        db.query(Abrechnung)
        .filter(Abrechnung.patient_id == patient_id)
        .count()
        > 0
    )

    # Optional: vorhandene Abrechnung im selben Monat stornieren
    if storniere_alt == "1":
        alte_abrechnungen = (
            db.query(Abrechnung)
            .filter(
                Abrechnung.patient_id == patient_id,
                Abrechnung.abrechnungsmonat == abrechnungsmonat,
                Abrechnung.storniert.is_(False),
            )
            .all()
        )
        for abr_alt in alte_abrechnungen:
            abr_alt.storniert = True
            abr_alt.storniert_am = datetime.utcnow()
            db.add(abr_alt)
        db.commit()

    kasse_id = patient.kasse_id

    abr = Abrechnung(
        patient_id=patient_id,
        kasse_id=kasse_id,
        abrechnungsmonat=abrechnungsmonat,
        gesamt_betrag=Decimal("0.00"),
    )
    db.add(abr)
    db.commit()
    db.refresh(abr)

    gesamt = Decimal("0.00")

    for hm_id_raw, qty_raw in zip(hilfsmittel_id, menge):
        if not hm_id_raw or not qty_raw:
            continue

        try:
            hm_id = int(hm_id_raw)
            qty_int = int(qty_raw)
        except ValueError:
            continue

        if qty_int <= 0:
            continue

        hm = db.get(PflegeHilfsmittel, hm_id)
        if not hm:
            continue

        einzel = Decimal(str(hm.preis_brutto))
        betrag = einzel * qty_int

        pos = AbrechnungsPosition(
            abrechnung_id=abr.id,
            hilfsmittel_id=hm.id,
            menge=qty_int,
            einzelpreis=einzel,
            betrag_gesamt=betrag,
        )
        db.add(pos)
        gesamt += betrag

    abr.gesamt_betrag = gesamt
    db.commit()

    # 🔹 HIER: unterschrift_eins.pdf NUR bei ERSTER Abrechnung dieses Patienten erzeugen
    if not hatte_schon_abrechnung and (beratung_datum or beratung_mitarbeiter):
        try:
            template_path = str(Path("app/static/unterschrift_eins.pdf"))

            data = {
                "beratung_datum": beratung_datum,
                "beratung_mitarbeiter": beratung_mitarbeiter,
            }

            pdf_buf = render_unterschrift_eins(template_path, data)

            # Im Patienten-Exportordner ablegen
            export_dir = get_patient_export_dir(patient)
            export_dir.mkdir(parents=True, exist_ok=True)

            raw_name = (patient.name or f"patient_{patient.id}").strip()
            safe_name = (
                "".join(c for c in raw_name if c.isalnum() or c in ("-", "_", " "))
                .strip()
                .replace(" ", "_")
                or f"patient_{patient.id}"
            )

            filename = f"Beratungsnachweis_{safe_name}_{abrechnungsmonat}.pdf"
            file_path = export_dir / filename

            with file_path.open("wb") as f:
                f.write(pdf_buf.getvalue())

        except Exception as e:
            # Wenn hier etwas schiefgeht, soll die Abrechnung trotzdem angelegt sein.
            print("[UNTERSCHRIFT_EINS] Fehler beim Erzeugen:", repr(e))

    return RedirectResponse(
        url=f"/abrechnungen?monat={abrechnungsmonat}",
        status_code=303,
    )


# ==============================
#   Rechnung (PDF) erzeugen
# ==============================
@router.get("/abrechnungen/{abrechnung_id}/rechnung")
def export_abrechnung_rechnung(
    abrechnung_id: int,
    db: Session = Depends(get_db),
):
    abrechnung = db.get(Abrechnung, abrechnung_id)
    if not abrechnung:
        return RedirectResponse(url="/abrechnungen", status_code=303)

    patient = abrechnung.patient
    kasse = abrechnung.kasse
    cfg = db.get(Einstellungen, 1)

    # === Patient- & Kassen-Daten ============================================
    kasse_address = ""
    if kasse:
        kasse_address = getattr(kasse, "address", "") or ""

    patient_dict = {
        "name": patient.name,
        "adresse": patient.address or "",
        "geburtsdatum": getattr(patient, "geburtsdatum", None).strftime(
            "%d.%m.%Y"
        )
        if getattr(patient, "geburtsdatum", None)
        else "",
        "versichertennr": patient.versichertennummer,
        "pflegekasse": kasse.name if kasse else "",
        "pflegekasse_address": kasse_address,
        "versorgungsmonat": abrechnung.abrechnungsmonat,
    }

    # === Provider-Daten aus der DB-Config für pdf_simple ====================
    if cfg:
        addr_parts = []
        if cfg.strasse:
            addr_parts.append(cfg.strasse.strip())
        ort_block = " ".join(
            p for p in [(cfg.plz or "").strip(), (cfg.ort or "").strip()] if p
        ).strip()
        if ort_block:
            addr_parts.append(ort_block)

        provider = {
            "name": cfg.name or "",
            "address": "\n".join(addr_parts),
            "ik": (cfg.ik or "").strip(),
        }
    else:
        provider = {
            "name": "",
            "address": "",
            "ik": "",
        }

    # === MwSt-Konfiguration =================================================
    ust_pflichtig = False
    ust_satz = Decimal("0")

    if cfg:
        ust_pflichtig = bool(cfg.ust_pflichtig)
        try:
            ust_satz = Decimal(str(cfg.ust_satz or "0"))
        except Exception:
            ust_satz = Decimal("0")

    positions_list: List[dict] = []
    total_net = Decimal("0.00")
    total_vat = Decimal("0.00")
    total_gross = Decimal(str(abrechnung.gesamt_betrag or "0.00"))

    for pos in abrechnung.positionen:
        brutto = Decimal(str(pos.betrag_gesamt))

        if ust_pflichtig and ust_satz > 0:
            faktor = Decimal("1") + (ust_satz / Decimal("100"))
            net = (brutto / faktor).quantize(Decimal("0.01"))
            vat = (brutto - net).quantize(Decimal("0.01"))
        else:
            net = brutto
            vat = Decimal("0.00")

        positions_list.append(
            {
                "name": pos.hilfsmittel.bezeichnung,
                "qty": pos.menge,
                "unit_price": Decimal(str(pos.einzelpreis)),
                "net": net,
                "vat": vat,
            }
        )

        total_net += net
        total_vat += vat

    if total_gross == Decimal("0.00"):
        total_gross = total_net + total_vat

    # Logo-Pfad für die Rechnung
    logo_path = str(Path("app/static/logo_klein.png"))

    pdf_buf = make_invoice_pdf(
        cfg=cfg,
        provider=provider,
        patient=patient_dict,
        positions=positions_list,
        total_net=total_net,
        total_vat=total_vat,
        total_gross=total_gross,
        logo_path=logo_path,
    )

    # === PDF im Archivordner ablegen =======================================
    export_dir = get_abrechnung_export_dir(abrechnung)
    export_dir.mkdir(parents=True, exist_ok=True)

    raw_name = (patient.name or f"patient_{patient.id}").strip()
    safe_name = (
        "".join(c for c in raw_name if c.isalnum() or c in ("-", "_", " "))
        .strip()
        .replace(" ", "_")
        or f"patient_{patient.id}"
    )

    monat_str = abrechnung.abrechnungsmonat or "unbekannt"

    filename = f"Rechnung_{safe_name}_{monat_str}.pdf"
    file_path = export_dir / filename

    with file_path.open("wb") as f:
        f.write(pdf_buf.getvalue())

    pdf_buf.seek(0)

    return StreamingResponse(
        pdf_buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ==============================
#   Export XML + AUF + VALIDATOR
# ==============================
@router.get("/abrechnungen/{abrechnung_id}/export")
def export_abrechnung_xml(
    request: Request,
    abrechnung_id: int,
    db: Session = Depends(get_db),
):
    abrechnung = db.get(Abrechnung, abrechnung_id)
    if not abrechnung:
        return RedirectResponse(url="/abrechnungen", status_code=303)

    patient = abrechnung.patient
    kasse = abrechnung.kasse
    positionen = abrechnung.positionen

    cfg = db.get(Einstellungen, 1)

    errors: List[str] = []

    sender_ik_raw = (cfg.ik if cfg and cfg.ik else "").strip() if cfg else ""
    if not sender_ik_raw:
        errors.append(
            "In der Konfiguration ist kein Institutionskennzeichen (IK) "
            "für den Leistungserbringer hinterlegt."
        )
    else:
        if (
            len(sender_ik_raw) != 9
            or not sender_ik_raw.isdigit()
            or sender_ik_raw == "000000000"
        ):
            errors.append(
                f"Das Absender-IK '{sender_ik_raw}' ist ungültig. "
                "Erwartet werden 9 Ziffern (kein 000000000)."
            )

    if not kasse:
        errors.append(
            "Der gewählte Patient hat keine Pflegekasse / keinen Kostenträger hinterlegt."
        )
    else:
        k_ik = (kasse.ik or "").strip()
        if not k_ik or len(k_ik) != 9 or not k_ik.isdigit():
            errors.append(
                f"Die Pflegekasse '{kasse.name}' hat kein gültiges IK. "
                "Bitte prüfen Sie die Stammdaten."
            )

        if hasattr(kasse, "aktiv") and (kasse.aktiv is False):
            errors.append(
                f"Die Pflegekasse '{kasse.name}' ist laut Stammdaten nicht aktiv "
                "(Funktionskennzeichen ≠ '01')."
            )

    primary_mail = ""
    if cfg:
        primary_mail = (cfg.kim_adresse or cfg.email_absender or "").strip()
    if not primary_mail:
        errors.append(
            "Es ist keine KIM-/Absenderadresse hinterlegt. "
            "Bitte in der Konfiguration eine E-Mail-Adresse eintragen."
        )

    if errors:
        return templates.TemplateResponse(
            "export_error.html",
            {
                "request": request,
                "abrechnung": abrechnung,
                "patient": patient,
                "kasse": kasse,
                "errors": errors,
            },
            status_code=400,
        )

    sender_ik = sender_ik_raw or "000000000"
    sender_email = primary_mail
    verfahrenskennung = cfg.verfahrenskennung or "TPFL0" if cfg else "TPFL0"
    zeichensatz = cfg.zeichensatz or "I8" if cfg else "I8"
    uebertragungsweg = 5
    abrechnungscode = cfg.abrechnungscode if cfg else None

    if cfg and cfg.uebertragungsweg:
        try:
            uebertragungsweg = int(cfg.uebertragungsweg)
        except ValueError:
            uebertragungsweg = 5

    empfaenger_ik = None
    if kasse and kasse.ik and len(kasse.ik) == 9 and kasse.ik.isdigit():
        empfaenger_ik = kasse.ik

    now = datetime.now()
    erstellungsdatum = now.strftime("%Y%m%d")
    erstellungszeit = now.strftime("%H%M%S")
    datei_id = str(uuid.uuid4())
    leistungsnachweis_id = str(uuid.uuid4())

    root = ET.Element(f"{{{NS_DAT}}}Nutzdaten")
    header_el = ET.SubElement(root, f"{{{NS_DAT}}}Header")

    abs_el = ET.SubElement(header_el, f"{{{NS_BAS}}}Absender")
    ET.SubElement(abs_el, f"{{{NS_BAS}}}KIM_Mailadresse").text = sender_email
    ET.SubElement(abs_el, f"{{{NS_BAS}}}Institutionskennzeichen").text = sender_ik

    emp_el = ET.SubElement(header_el, f"{{{NS_BAS}}}Empfaenger")
    if empfaenger_ik:
        ET.SubElement(emp_el, f"{{{NS_BAS}}}Institutionskennzeichen").text = empfaenger_ik

    ET.SubElement(header_el, f"{{{NS_BAS}}}Erstellungsdatum").text = erstellungsdatum
    ET.SubElement(header_el, f"{{{NS_BAS}}}Erstellungszeit").text = erstellungszeit
    ET.SubElement(header_el, f"{{{NS_BAS}}}Datei_ID").text = datei_id
    ET.SubElement(header_el, f"{{{NS_BAS}}}Verfahrenskennung").text = verfahrenskennung
    ET.SubElement(header_el, f"{{{NS_BAS}}}Nachrichtentyp").text = "ABR"
    ET.SubElement(header_el, f"{{{NS_BAS}}}Logische_Version").text = "2.2.0"

    abr_msg = ET.SubElement(root, f"{{{NS_DAT}}}Abrechnungsnachricht")

    edifact_bytes = build_edifact_from_abrechnung(abrechnung, cfg)
    pkcs7_bytes = sign_edifact(edifact_bytes)

    abr_daten_el = ET.SubElement(abr_msg, f"{{{NS_ABR}}}Abrechnungsdaten")
    abr_daten_el.text = base64.b64encode(pkcs7_bytes).decode("ascii")

    unterlagen_el = ET.SubElement(abr_msg, f"{{{NS_ABR}}}Abrechnungsbegruendende_Unterlagen")
    u1 = ET.SubElement(unterlagen_el, f"{{{NS_ABR}}}Abrechnungsbegruendende_Unterlage")

    ET.SubElement(u1, f"{{{NS_ABR}}}Leistungsnachweis_ID").text = leistungsnachweis_id
    ET.SubElement(u1, f"{{{NS_ABR}}}Erstelldatum_Leistungsnachweis").text = erstellungsdatum

    lines = [
        f"Abrechnung ID: {abrechnung.id}",
        f"Abrechnungsmonat: {abrechnung.abrechnungsmonat}",
        "",
        f"Patient: {patient.name} ({patient.versichertennummer})",
        f"Kasse: {kasse.name if kasse else ''}",
        "",
        "Positionen:",
    ]
    for pos in positionen:
        lines.append(
            f"- {pos.menge} x {pos.hilfsmittel.bezeichnung} "
            f"à {pos.einzelpreis:.2f} EUR = {pos.betrag_gesamt:.2f} EUR"
        )
    lines.append("")
    lines.append(f"Gesamtbetrag: {abrechnung.gesamt_betrag:.2f} EUR")

    leistungsnachweis_text = "\n".join(lines).encode("utf-8")
    datei_el = ET.SubElement(u1, f"{{{NS_ABR}}}Datei")
    datei_el.text = base64.b64encode(leistungsnachweis_text).decode("ascii")

    ET.SubElement(u1, f"{{{NS_ABR}}}Inhaltstyp").text = "1"
    ET.SubElement(u1, f"{{{NS_ABR}}}Dateityp").text = "1"

    export_dir = get_abrechnung_export_dir(abrechnung)

    transfer_nummer = f"{abrechnung.id % 1000:03d}"
    transfername = f"{verfahrenskennung}{transfer_nummer}"

    xml_filename = f"{transfername}.xml"
    xml_path = export_dir / xml_filename

    tree = ET.ElementTree(root)
    tree.write(xml_path, encoding="utf-8", xml_declaration=True)

    dateigroesse_nutzdaten = len(edifact_bytes)
    dateigroesse_uebertragung = xml_path.stat().st_size

    email_abs_for_auf = primary_mail or None

    auftragssatz = build_auftragssatz(
        verfahrenskennung=verfahrenskennung,
        transfer_nummer=transfer_nummer,
        absender_ik=sender_ik,
        empfaenger_ik=empfaenger_ik,
        dateiname=transfername,
        datum_erstellung=now,
        dateigroesse_nutzdaten=dateigroesse_nutzdaten,
        dateigroesse_uebertragung=dateigroesse_uebertragung,
        zeichensatz=zeichensatz,
        komprimierung=(cfg.komprimierung if cfg and cfg.komprimierung else "00"),
        verschluesselungsart=(cfg.verschluesselungsart if cfg and cfg.verschluesselungsart else "02") if hasattr(cfg, "verschluesselungsart") else (cfg.verschluesselungsart if cfg and cfg.verschluesselungsart else "02"),
        elektronische_unterschrift=(cfg.elektronische_unterschrift if cfg and cfg.elektronische_unterschrift else "00"),
        uebertragungsweg=uebertragungsweg,
        verzoegerter_versand=None,
        email_absender=email_abs_for_auf,
        abrechnungscode=abrechnungscode,
        verfahren_spezifikation=(cfg.verfahren_spezifikation if cfg and cfg.verfahren_spezifikation else None),
        max_wiederholungen=(cfg.max_wiederholungen if cfg and cfg.max_wiederholungen else None),
    )

    auftrag_filename = f"{transfername}.AUF"
    auftrag_path = export_dir / auftrag_filename

    with auftrag_path.open("w", encoding="latin-1", newline="") as f:
        f.write(auftragssatz)
        f.write("\r\n")

    is_valid, errors_val = validate_pfl_file(xml_path)
    if not is_valid:
        print(f"[PFL-VALIDATION] Datei {xml_path} ist NICHT gültig.")
        for err in errors_val:
            print("  -", err)
    else:
        print(f"[PFL-VALIDATION] Datei {xml_path} ist gültig.")

    return FileResponse(
        path=str(xml_path),
        media_type="application/xml",
        filename=xml_filename,
    )


# ==============================
#   Versand-Hilfsfunktion (mit Fehlermeldung)
# ==============================
def _sende_abrechnung_per_mail(
    abrechnung: Abrechnung,
    db: Session,
) -> Tuple[bool, Optional[str]]:
    """
    Versendet EINE Abrechnung per E-Mail nach Anlage 7.

    Rückgabe:
      (True, None)      -> alles ok
      (False, "Fehler") -> Fehler, nicht gesendet
    """
    # Bereits gesendet? Dann nichts tun
    if abrechnung.gesendet_am is not None:
        return True, None

    cfg = db.get(Einstellungen, 1)
    if not cfg:
        return False, (
            "Es ist noch keine Konfiguration hinterlegt. "
            "Bitte unter 'Konfiguration' Stammdaten und Absender-E-Mail eintragen."
        )

    # --- SMTP-Konfiguration prüfen ---------------------------------------
    smtp_server = (cfg.smtp_server or "").strip()
    smtp_port = cfg.smtp_port

    if not smtp_server or not smtp_port:
        return False, (
            "In der Konfiguration ist kein gültiger SMTP-Server / Port hinterlegt.\n"
            "Bitte unter 'Konfiguration' einen SMTP-Server (z.B. smtp.example.org) "
            "und einen Port (z.B. 587) eintragen."
        )

    try:
        int(smtp_port)
    except (TypeError, ValueError):
        return False, (
            f"Der konfigurierte SMTP-Port '{smtp_port}' ist ungültig.\n"
            "Bitte einen numerischen Port angeben (z.B. 587)."
        )

    patient = abrechnung.patient
    kasse = abrechnung.kasse

    if not kasse:
        return False, (
            f"Abrechnung {abrechnung.id}: Keine Pflegekasse hinterlegt. "
            "Bitte dem Patienten eine Pflegekasse zuordnen."
        )

    primary_mail = (cfg.kim_adresse or cfg.email_absender or "").strip()
    if not primary_mail:
        return False, (
            "Es ist keine Absender-E-Mail/KIM-Adresse hinterlegt. "
            "Bitte in der Konfiguration eine E-Mail-Adresse eintragen."
        )

    empfaenger_email = (getattr(kasse, "annahmestelle_email", None) or "").strip()
    if not empfaenger_email:
        # Fallback-Testadresse
        empfaenger_email = DUMMY_KASSEN_EMAIL

    sender_ik = (cfg.ik or "").strip()
    if not sender_ik or len(sender_ik) != 9 or not sender_ik.isdigit():
        return False, (
            f"Das Absender-IK '{sender_ik or '-'}' ist ungültig. "
            "Bitte in der Konfiguration ein gültiges 9-stelliges IK eintragen."
        )

    empfaenger_ik = (kasse.ik or "").strip()
    if not empfaenger_ik or len(empfaenger_ik) != 9 or not empfaenger_ik.isdigit():
        return False, (
            f"Die Pflegekasse '{kasse.name}' hat kein gültiges IK. "
            "Bitte die Kassen-Stammdaten prüfen."
        )

    verfahrenskennung = cfg.verfahrenskennung or "TPFL0"
    zeichensatz = cfg.zeichensatz or "I8"

    uebertragungsweg = 5
    if cfg.uebertragungsweg:
        try:
            uebertragungsweg = int(cfg.uebertragungsweg)
        except ValueError:
            uebertragungsweg = 5

    abrechnungscode = cfg.abrechnungscode

    now = datetime.now()
    erstellungsdatum = now.strftime("%Y%m%d")
    erstellungszeit = now.strftime("%H%M%S")
    datei_id = str(uuid.uuid4())
    leistungsnachweis_id = str(uuid.uuid4())

    # =============================
    #   XML-Struktur aufbauen
    # =============================
    root = ET.Element(f"{{{NS_DAT}}}Nutzdaten")
    header_el = ET.SubElement(root, f"{{{NS_DAT}}}Header")

    abs_el = ET.SubElement(header_el, f"{{{NS_BAS}}}Absender")
    ET.SubElement(abs_el, f"{{{NS_BAS}}}KIM_Mailadresse").text = primary_mail
    ET.SubElement(abs_el, f"{{{NS_BAS}}}Institutionskennzeichen").text = sender_ik

    emp_el = ET.SubElement(header_el, f"{{{NS_BAS}}}Empfaenger")
    ET.SubElement(emp_el, f"{{{NS_BAS}}}Institutionskennzeichen").text = empfaenger_ik

    ET.SubElement(header_el, f"{{{NS_BAS}}}Erstellungsdatum").text = erstellungsdatum
    ET.SubElement(header_el, f"{{{NS_BAS}}}Erstellungszeit").text = erstellungszeit
    ET.SubElement(header_el, f"{{{NS_BAS}}}Datei_ID").text = datei_id
    ET.SubElement(header_el, f"{{{NS_BAS}}}Verfahrenskennung").text = verfahrenskennung
    ET.SubElement(header_el, f"{{{NS_BAS}}}Nachrichtentyp").text = "ABR"
    ET.SubElement(header_el, f"{{{NS_BAS}}}Logische_Version").text = "2.2.0"

    abr_msg = ET.SubElement(root, f"{{{NS_DAT}}}Abrechnungsnachricht")

    positionen = abrechnung.positionen
    edifact_bytes = build_edifact_from_abrechnung(abrechnung, cfg)
    pkcs7_bytes = sign_edifact(edifact_bytes)

    abr_daten_el = ET.SubElement(abr_msg, f"{{{NS_ABR}}}Abrechnungsdaten")
    abr_daten_el.text = base64.b64encode(pkcs7_bytes).decode("ascii")

    unterlagen_el = ET.SubElement(abr_msg, f"{{{NS_ABR}}}Abrechnungsbegruendende_Unterlagen")
    u1 = ET.SubElement(unterlagen_el, f"{{{NS_ABR}}}Abrechnungsbegruendende_Unterlage")
    ET.SubElement(u1, f"{{{NS_ABR}}}Leistungsnachweis_ID").text = leistungsnachweis_id
    ET.SubElement(u1, f"{{{NS_ABR}}}Erstelldatum_Leistungsnachweis").text = erstellungsdatum

    lines = [
        f"Abrechnung ID: {abrechnung.id}",
        f"Abrechnungsmonat: {abrechnung.abrechnungsmonat}",
        "",
        f"Patient: {patient.name} ({patient.versichertennummer})",
        f"Kasse: {kasse.name if kasse else ''}",
        "",
        "Positionen:",
    ]
    for pos in positionen:
        lines.append(
            f"- {pos.menge} x {pos.hilfsmittel.bezeichnung} "
            f"à {pos.einzelpreis:.2f} EUR = {pos.betrag_gesamt:.2f} EUR"
        )
    lines.append("")
    lines.append(f"Gesamtbetrag: {abrechnung.gesamt_betrag:.2f} EUR")

    leistungsnachweis_text = "\n".join(lines).encode("utf-8")
    datei_el = ET.SubElement(u1, f"{{{NS_ABR}}}Datei")
    datei_el.text = base64.b64encode(leistungsnachweis_text).decode("ascii")
    ET.SubElement(u1, f"{{{NS_ABR}}}Inhaltstyp").text = "1"
    ET.SubElement(u1, f"{{{NS_ABR}}}Dateityp").text = "1"

    # =============================
    #   Dateien im Export-Ordner
    # =============================
    export_dir = get_abrechnung_export_dir(abrechnung)

    transfer_nummer = f"{abrechnung.id % 1000:03d}"
    transfername = f"{verfahrenskennung}{transfer_nummer}"

    xml_filename = f"{transfername}.xml"
    xml_path = export_dir / xml_filename
    tree = ET.ElementTree(root)
    tree.write(xml_path, encoding="utf-8", xml_declaration=True)

    dateigroesse_nutzdaten = len(edifact_bytes)
    dateigroesse_uebertragung = xml_path.stat().st_size

    email_abs_for_auf = primary_mail

    auftragssatz = build_auftragssatz(
        verfahrenskennung=verfahrenskennung,
        transfer_nummer=transfer_nummer,
        absender_ik=sender_ik,
        empfaenger_ik=empfaenger_ik,
        dateiname=transfername,
        datum_erstellung=now,
        dateigroesse_nutzdaten=dateigroesse_nutzdaten,
        dateigroesse_uebertragung=dateigroesse_uebertragung,
        zeichensatz=zeichensatz,
        komprimierung=(cfg.komprimierung if cfg and cfg.komprimierung else "00"),
        verschluesselungsart=(cfg.verschluesselungsart if cfg and cfg.verschluesselungsart else "02"),
        elektronische_unterschrift=(cfg.elektronische_unterschrift if cfg and cfg.elektronische_unterschrift else "00"),
        uebertragungsweg=uebertragungsweg,
        verzoegerter_versand=None,
        email_absender=email_abs_for_auf,
        abrechnungscode=abrechnungscode,
        verfahren_spezifikation=cfg.verfahren_spezifikation,
        max_wiederholungen=cfg.max_wiederholungen,
    )

    auftrag_filename = f"{transfername}.AUF"
    auftrag_path = export_dir / auftrag_filename
    with auftrag_path.open("w", encoding="latin-1", newline="") as f:
        f.write(auftragssatz)
        f.write("\r\n")

    # =============================
    #   Versand per E-Mail
    # =============================
    try:
        send_datenaustausch_mail(
            cfg=cfg,
            sender_ik=sender_ik,
            empfaenger_email=empfaenger_email,
            auf_path=auftrag_path,
            nutzdaten_path=xml_path,
            auf_erstellzeit=now,
        )
    except Exception as e:
        print("[MAIL] Fehler beim Versand:", repr(e))
        return False, (
            "Beim Versand an die Datenannahmestelle ist ein technischer Fehler "
            f"aufgetreten:\n{e}"
        )

    # Zeitpunkt der Absendung (lokale Zeit für den Begleitzettel)
    send_time = datetime.now()
    erstellungsdatum = send_time.strftime("%Y%m%d")
    erstellungszeit = send_time.strftime("%H%M%S")

    # Abrechnung als gesendet markieren (UTC in der DB)
    abrechnung.gesendet_am = datetime.utcnow()
    db.add(abrechnung)
    db.commit()

    # --- Begleitzettel nach Versand erzeugen (falls noch nicht vorhanden) --
    patient = abrechnung.patient
    kasse = abrechnung.kasse
    positionen = abrechnung.positionen

    export_dir = get_abrechnung_export_dir(abrechnung)
    transfer_nummer = f"{abrechnung.id % 1000:03d}"
    transfername = f"{verfahrenskennung}{transfer_nummer}"

    begleitzettel_filename = f"{transfername}_Begleitzettel.pdf"
    begleitzettel_path = export_dir / begleitzettel_filename

    from weasyprint import HTML as WEASY_HTML

    begleitzettel_html = templates.get_template("begleitzettel.html").render(
        {
            "abrechnung": abrechnung,
            "patient": patient,
            "kasse": kasse,
            "positionen": positionen,
            "cfg": cfg,
            "sender_ik": sender_ik,
            "empfaenger_ik": empfaenger_ik,
            "erstellungsdatum": erstellungsdatum,
            "erstellungszeit": erstellungszeit,
            "transfername": transfername,
            "xml_filename": xml_filename,
            "auf_filename": auftrag_filename,
        }
    )
    WEASY_HTML(string=begleitzettel_html).write_pdf(str(begleitzettel_path))

    return True, None


# ==============================
#   ABSENDEN-Seite
# ==============================
@router.get("/absenden")
def absenden_view(
    request: Request,
    monat: Optional[str] = None,
    db: Session = Depends(get_db),
):
    if not monat:
        monat = datetime.now().strftime("%Y-%m")

    # alle Monate für das Dropdown
    alle_monate = [
        m[0]
        for m in db.query(Abrechnung.abrechnungsmonat)
        .distinct()
        .order_by(Abrechnung.abrechnungsmonat.desc())
        .all()
    ]

    # Abrechnungen des gewählten Monats (nicht stornierte)
    abrechnungen_monat = (
        db.query(Abrechnung)
        .filter(
            Abrechnung.abrechnungsmonat == monat,
            Abrechnung.storniert.is_(False),
        )
        .order_by(Abrechnung.created_at.asc())
        .all()
    )

    # monatsübergreifend alle NICHT gesendeten Abrechnungen (nicht storniert)
    offene_abrechnungen_alle = (
        db.query(Abrechnung)
        .filter(
            Abrechnung.gesendet_am.is_(None),
            Abrechnung.storniert.is_(False),
        )
        .order_by(
            Abrechnung.abrechnungsmonat.desc(),
            Abrechnung.created_at.desc(),
        )
        .all()
    )

    error = request.query_params.get("error")

    return templates.TemplateResponse(
        "absenden.html",
        {
            "request": request,
            "monat": monat,
            "alle_monate": alle_monate,
            "abrechnungen_monat": abrechnungen_monat,
            "error": error,
            "offene_abrechnungen_alle": offene_abrechnungen_alle,
        },
    )


@router.post("/absenden/{abrechnung_id}/send")
def absenden_send_single(
    abrechnung_id: int,
    monat: str = Form(...),
    db: Session = Depends(get_db),
):
    abrechnung = db.get(Abrechnung, abrechnung_id)
    if not abrechnung:
        error = f"Abrechnung {abrechnung_id} wurde nicht gefunden."
        url = f"/absenden?monat={monat}&error={urllib.parse.quote(error)}"
        return RedirectResponse(url=url, status_code=303)

    success, err = _sende_abrechnung_per_mail(abrechnung, db)

    if not success and err:
        url = f"/absenden?monat={monat}&error={urllib.parse.quote(err)}"
    else:
        url = f"/absenden?monat={monat}"

    return RedirectResponse(url=url, status_code=303)


@router.post("/absenden/send_all")
def absenden_send_all(
    monat: str = Form(...),
    db: Session = Depends(get_db),
):
    offene_abrechnungen = (
        db.query(Abrechnung)
        .filter(
            Abrechnung.abrechnungsmonat == monat,
            Abrechnung.gesendet_am.is_(None),
            Abrechnung.storniert.is_(False),
        )
        .order_by(Abrechnung.created_at.asc())
        .all()
    )

    errors: List[str] = []

    for abr in offene_abrechnungen:
        success, err = _sende_abrechnung_per_mail(abr, db)
        if not success and err:
            errors.append(f"ID {abr.id}: {err}")

    if errors:
        err_text = (
            "Einige Abrechnungen konnten nicht gesendet werden:\n"
            + "\n".join(errors)
        )
        url = f"/absenden?monat={monat}&error={urllib.parse.quote(err_text)}"
    else:
        url = f"/absenden?monat={monat}"

    return RedirectResponse(url=url, status_code=303)


# ==============================
#   Konfiguration
# ==============================
@router.get("/config")
def get_config(request: Request, db: Session = Depends(get_db)):
    cfg = db.get(Einstellungen, 1)

    if not cfg:
        cfg = Einstellungen(
            id=1,
            ik="000000000",
            verfahrenskennung="TPFL0",
            abrechnungscode="19",
            ust_pflichtig=True,
            ust_satz="19",
            max_wiederholungen="01",
        )
        db.add(cfg)
        db.commit()
        db.refresh(cfg)

    return templates.TemplateResponse(
        "config.html",
        {"request": request, "cfg": cfg},
    )


@router.post("/config")
def save_config(
    request: Request,
    name: str = Form(""),
    strasse: str = Form(""),
    plz: str = Form(""),
    ort: str = Form(""),
    ik: str = Form(...),
    kim_adresse: str = Form(""),
    bundesland: str = Form(""),
    abrechnungscode: str = Form("19"),
    tarifkennzeichen: str = Form(""),
    verfahrenskennung: str = Form("TPFL0"),
    ust_pflichtig: str = Form("ja"),
    ust_satz: str = Form("19"),
    uebermittlungsmedium: str = Form("2"),
    zeichensatz: str = Form("I8"),
    verfahren_spezifikation: str = Form(""),
    komprimierung: str = Form("00"),
    verschluesselungsart: str = Form("02"),
    elektronische_unterschrift: str = Form("00"),
    max_wiederholungen: str = Form("01"),
    uebertragungsweg: str = Form("5"),
    smtp_server: str = Form(""),
    smtp_port: str = Form(""),
    smtp_user: str = Form(""),
    smtp_password: str = Form(""),
    smtp_use_tls: str = Form("on"),
    email_absender: str = Form(""),
    kontakt_person: str = Form(""),
    kontakt_telefon: str = Form(""),
    kontakt_fax: str = Form(""),
    bank_name: str = Form(""),
    bank_iban: str = Form(""),
    db: Session = Depends(get_db),
):
    cfg = db.get(Einstellungen, 1)
    if not cfg:
        cfg = Einstellungen(id=1)
        db.add(cfg)

    cfg.name = name or None
    cfg.strasse = strasse or None
    cfg.plz = plz or None
    cfg.ort = ort or None

    cfg.ik = ik

    email_clean = (email_absender or "").strip()
    kim_clean = (kim_adresse or "").strip()

    cfg.email_absender = email_clean or kim_clean or None
    cfg.kim_adresse = kim_clean or email_clean or None

    cfg.bundesland = bundesland or None
    cfg.abrechnungscode = abrechnungscode or None

    tk_clean = (tarifkennzeichen or "").strip()
    if not tk_clean and bundesland in TARIFKENNZEICHEN_DEFAULTS:
        tk_clean = TARIFKENNZEICHEN_DEFAULTS[bundesland]
    cfg.tarifkennzeichen = tk_clean or None

    cfg.verfahrenskennung = verfahrenskennung

    cfg.ust_pflichtig = ust_pflichtig == "ja"
    cfg.ust_satz = ust_satz or None

    cfg.uebermittlungsmedium = uebermittlungsmedium or None
    cfg.zeichensatz = zeichensatz or None

    cfg.verfahren_spezifikation = verfahren_spezifikation or None
    cfg.komprimierung = komprimierung or "00"
    cfg.verschluesselungsart = verschluesselungsart or "02"
    cfg.elektronische_unterschrift = elektronische_unterschrift or "00"
    cfg.max_wiederholungen = max_wiederholungen or None
    cfg.uebertragungsweg = uebertragungsweg or None

    cfg.smtp_server = smtp_server or None
    cfg.smtp_port = int(smtp_port) if smtp_port.strip() else None
    cfg.smtp_user = smtp_user or None
    if smtp_password.strip():
        cfg.smtp_password = smtp_password
    cfg.smtp_use_tls = smtp_use_tls.lower() in ("on", "true", "1")

    cfg.kontakt_person = kontakt_person or None
    cfg.kontakt_telefon = kontakt_telefon or None
    cfg.kontakt_fax = kontakt_fax or None
    cfg.bank_name = bank_name or None
    cfg.bank_iban = bank_iban or None

    db.commit()

    return RedirectResponse(url="/config", status_code=303)


# ==============================
#   Archiv – Übersicht
# ==============================
@router.get("/archiv")
def archiv_overview(request: Request, db: Session = Depends(get_db)):
    patients_with_abrs = (
        db.query(Patient)
        .join(Abrechnung, Abrechnung.patient_id == Patient.id)
        .distinct()
        .order_by(Patient.name.asc())
        .all()
    )

    stats_raw = (
        db.query(
            Abrechnung.patient_id,
            func.count().label("anzahl"),
            func.min(Abrechnung.abrechnungsmonat).label("von"),
            func.max(Abrechnung.abrechnungsmonat).label("bis"),
        )
        .group_by(Abrechnung.patient_id)
        .all()
    )
    stats_by_patient = {row.patient_id: row for row in stats_raw}

    return templates.TemplateResponse(
        "archiv.html",
        {
            "request": request,
            "patients": patients_with_abrs,
            "stats_by_patient": stats_by_patient,
        },
    )


# ==============================
#   Archiv – Patient
# ==============================
@router.get("/archiv/{patient_id}")
def archiv_patient_view(
    patient_id: int,
    request: Request,
    monat: Optional[str] = None,
    db: Session = Depends(get_db),
):
    patient = db.get(Patient, patient_id)

    # Abrechnungen laden
    abrechnungen_q = (
        db.query(Abrechnung)
        .filter(Abrechnung.patient_id == patient_id)
        .order_by(
            Abrechnung.abrechnungsmonat.desc(),
            Abrechnung.created_at.desc(),
        )
    )
    abrechnungen_all = abrechnungen_q.all()

    monate = sorted({a.abrechnungsmonat for a in abrechnungen_all}, reverse=True)

    if not monat and monate:
        monat = monate[0]

    if monat:
        abrechnungen = [a for a in abrechnungen_all if a.abrechnungsmonat == monat]
    else:
        abrechnungen = abrechnungen_all

    # ============================
    #   Abrechnungs-spezifische Dateien
    # ============================
    dateien: dict[int, dict] = {}
    cfg = db.get(Einstellungen, 1)
    verfahrenskennung = cfg.verfahrenskennung or "TPFL0" if cfg else "TPFL0"

    for a in abrechnungen:
        export_dir = get_abrechnung_export_dir(a)

        transfer_nummer = f"{a.id % 1000:03d}"
        transfername = f"{verfahrenskennung}{transfer_nummer}"

        xml = export_dir / f"{transfername}.xml"
        auf = export_dir / f"{transfername}.AUF"
        pdf_begleitzettel = export_dir / f"{transfername}_Begleitzettel.pdf"
        pdf_leistungsnachweis = export_dir / f"{transfername}_Leistungsnachweis.pdf"
        pdf_leistungsnachweis_komplett = export_dir / f"{transfername}_Leistungsnachweis_komplett.pdf"

        # Rechnungs-PDF-Name robust bestimmen, auch wenn Patient evtl. None ist
        if patient:
            pn = patient.name or f"patient_{patient_id}"
        else:
            pn = f"patient_{patient_id}"
        safe_pn = pn.replace(" ", "_")

        pdf_rechnung = export_dir / f"Rechnung_{safe_pn}_{a.abrechnungsmonat}.pdf"

        dateien[a.id] = {
            "xml_exists": xml.exists(),
            "auf_exists": auf.exists(),
            "pdf_exists": pdf_begleitzettel.exists(),
            "leistungsnachweis_exists": pdf_leistungsnachweis.exists(),
            "leistungsnachweis_komplett_exists": pdf_leistungsnachweis_komplett.exists(),
            "rechnung_exists": pdf_rechnung.exists(),
            "xml_path": str(xml),
            "auf_path": str(auf),
            "pdf_path": str(pdf_begleitzettel),
            "leistungsnachweis_path": str(pdf_leistungsnachweis),
            "leistungsnachweis_komplett_path": str(pdf_leistungsnachweis_komplett),
            "rechnung_path": str(pdf_rechnung),
        }

    # ============================
    #   Patientenbezogene Dateien
    # ============================
    from pathlib import Path as _Path

    patient_files = {
        "antrag_exists": False,
        "antrag_inkl_unterschrift_exists": False,
        "unterschriebener_exists": False,
    }

    if patient:
        p_export_dir = get_patient_export_dir(patient)

        # Alter Antrag Krankenkasse
        antrag_list = sorted(
            p_export_dir.glob("Antrag_Krankenkasse_*.pdf"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if antrag_list:
            patient_files["antrag_exists"] = True

        # ✅ Neuer Antrag inkl. Unterschrift
        antrag_inkl_list = sorted(
            p_export_dir.glob("Antrag_inkl_Unterschrift_*.pdf"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if antrag_inkl_list:
            patient_files["antrag_inkl_unterschrift_exists"] = True

        # ✅ Unterschriebener Antrag
        unterschriebener_path = None
        if getattr(patient, "unterschriebener_antrag", None):
            unterschriebener_path = _Path(patient.unterschriebener_antrag)

        # Fallback: alter Archivpfad
        if not unterschriebener_path or not unterschriebener_path.is_file():
            legacy_path = _Path(f"app/static/archiv/patient_{patient_id}/unterschriebener_antrag.pdf")
            if legacy_path.is_file():
                unterschriebener_path = legacy_path

        if unterschriebener_path and unterschriebener_path.is_file():
            patient_files["unterschriebener_exists"] = True

    else:
        # Falls Patient gelöscht wurde: Fallback auf altes Archivverzeichnis
        legacy_dir = _Path(f"app/static/archiv/patient_{patient_id}")
        if legacy_dir.is_dir():
            if list(legacy_dir.glob("Antrag_Krankenkasse_*.pdf")):
                patient_files["antrag_exists"] = True
            if list(legacy_dir.glob("Antrag_inkl_Unterschrift_*.pdf")):
                patient_files["antrag_inkl_unterschrift_exists"] = True
            if (legacy_dir / "unterschriebener_antrag.pdf").is_file():
                patient_files["unterschriebener_exists"] = True

    # ============================
    #   Template ausgeben
    # ============================
    return templates.TemplateResponse(
        "archiv_patient.html",
        {
            "request": request,
            "patient": patient,
            "patient_id": patient_id,
            "monate": monate,
            "monat": monat,
            "abrechnungen": abrechnungen,
            "dateien": dateien,
            "patient_files": patient_files,
        },
    )

from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from decimal import Decimal
from pathlib import Path
import shutil

MWST = Decimal("0.19")


@router.get("/archiv/{abrechnung_id}/leistungsnachweis")
def download_leistungsnachweis(
    abrechnung_id: int,
    db: Session = Depends(get_db),
):
    """
    Original-Kassenversion des Leistungsnachweises ausliefern:
    <transfername>_Leistungsnachweis.pdf
    """
    abrechnung = db.get(Abrechnung, abrechnung_id)
    if not abrechnung:
        return RedirectResponse(url="/archiv", status_code=303)

    cfg = db.get(Einstellungen, 1)
    verfahrenskennung = cfg.verfahrenskennung or "TPFL0" if cfg else "TPFL0"

    export_dir = get_abrechnung_export_dir(abrechnung)
    transfer_nummer = f"{abrechnung.id % 1000:03d}"
    transfername = f"{verfahrenskennung}{transfer_nummer}"
    pdf_path = export_dir / f"{transfername}_Leistungsnachweis.pdf"

    if not pdf_path.exists():
        return HTMLResponse(
            f"Kein Leistungsnachweis für Abrechnung {abrechnung.id} gefunden.",
            status_code=404,
        )

    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        filename=pdf_path.name,
    )


@router.get("/archiv/{abrechnung_id}/leistungsnachweis_komplett")
def download_leistungsnachweis_komplett(
    abrechnung_id: int,
    db: Session = Depends(get_db),
):
    """
    Kombinierte Version (Empfang + Unterschrift_zwei) ausliefern:
    <transfername>_Leistungsnachweis_komplett.pdf
    """
    abrechnung = db.get(Abrechnung, abrechnung_id)
    if not abrechnung:
        return RedirectResponse(url="/archiv", status_code=303)

    cfg = db.get(Einstellungen, 1)
    verfahrenskennung = cfg.verfahrenskennung or "TPFL0" if cfg else "TPFL0"

    export_dir = get_abrechnung_export_dir(abrechnung)
    transfer_nummer = f"{abrechnung.id % 1000:03d}"
    transfername = f"{verfahrenskennung}{transfer_nummer}"
    pdf_path = export_dir / f"{transfername}_Leistungsnachweis_komplett.pdf"

    if not pdf_path.exists():
        return HTMLResponse(
            f"Kein kombinierter Leistungsnachweis für Abrechnung {abrechnung.id} gefunden.",
            status_code=404,
        )

    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        filename=pdf_path.name,
    )


@router.get("/archiv/{patient_id}/antrag_kasse")
def download_archived_antrag_kasse(
    patient_id: int,
    db: Session = Depends(get_db),
):
    """
    Liefert den (zuletzt erzeugten) archivierten Antrag_Krankenkasse_*.pdf
    aus dem Patienten-Export-Ordner.
    """
    patient = db.get(Patient, patient_id)
    if not patient:
        return RedirectResponse(url="/archiv", status_code=303)

    export_dir = get_patient_export_dir(patient)
    antrag_files = sorted(
        export_dir.glob("Antrag_Krankenkasse_*.pdf"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    if not antrag_files:
        return HTMLResponse(
            f"Kein archivierter Antrag für Patient {patient_id} gefunden.",
            status_code=404,
        )

    pdf_path = antrag_files[0]

    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        filename=pdf_path.name,
    )


# ==============================
#   PDF-Parsing für Patientendaten
# ==============================
@router.post("/patients/parse_pdf")
async def parse_patient_pdf(
    patient_pdf: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    Nimmt eine Patienten-Dokumentations-PDF entgegen,
    extrahiert Text und parst Name / Geburtsdatum / Adresse / KV etc.
    """
    content = await patient_pdf.read()

    reader = LegacyPdfReader(BytesIO(content))
    raw_text = ""
    for page in reader.pages:
        raw_text += (page.extract_text() or "") + "\n"

    parsed = parse_patient_from_pdf_text(raw_text)

    # Pflegekasse im System "fuzzy" suchen
    kasse_id: Optional[int] = None
    kasse_name = (parsed.get("pflegeversicherung_name") or "").strip()

    if kasse_name:
        kassen = db.query(Kostentraeger).all()

        def normalize(s: str) -> str:
            s_norm = s.lower()
            import re

            s_norm = re.sub(r"[^a-z0-9]+", " ", s_norm)
            return " ".join(s_norm.split())

        target = normalize(kasse_name)
        best_match = None
        best_score = 0.0

        for k in kassen:
            name = k.name or ""
            n = normalize(name)

            tokens_t = set(target.split())
            tokens_n = set(n.split())
            if not tokens_t or not tokens_n:
                continue
            score = len(tokens_t & tokens_n) / len(tokens_t | tokens_n)

            if score > best_score:
                best_score = score
                best_match = k

        if best_match and best_score >= 0.4:
            kasse_id = best_match.id

    return JSONResponse(
        {
            "name": parsed.get("name") or "",
            "versichertennummer": parsed.get("versichertennummer") or "",
            "geburtsdatum": parsed.get("geburtsdatum") or "",
            "address": parsed.get("address") or "",
            "pflegeversicherung_name": parsed.get("pflegeversicherung_name") or "",
            "kasse_id": kasse_id,
        }
    )


# ==============================
#   Begleitzettel aus Archiv abrufen
# ==============================
@router.get("/archiv/{abrechnung_id}/begleitzettel")
def download_begleitzettel(
    abrechnung_id: int,
    db: Session = Depends(get_db),
):
    """
    Begleitzettel-PDF aus dem Archiv für eine Abrechnung ausliefern.
    Erwartet, dass der Begleitzettel im gleichen Export-Ordner liegt
    wie XML/AUF (Name: <transfername>_Begleitzettel.pdf).
    """
    abrechnung = db.get(Abrechnung, abrechnung_id)
    if not abrechnung:
        return RedirectResponse(url="/archiv", status_code=303)

    cfg = db.get(Einstellungen, 1)
    verfahrenskennung = cfg.verfahrenskennung or "TPFL0" if cfg else "TPFL0"

    export_dir = get_abrechnung_export_dir(abrechnung)

    transfer_nummer = f"{abrechnung.id % 1000:03d}"
    transfername = f"{verfahrenskennung}{transfer_nummer}"

    pdf_path = export_dir / f"{transfername}_Begleitzettel.pdf"

    if not pdf_path.exists():
        return HTMLResponse(
            f"Kein Begleitzettel für Abrechnung {abrechnung.id} gefunden.",
            status_code=404,
        )

    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        filename=pdf_path.name,
    )


# ==============================
#   Leistungsnachweise – UI & Upload
# ==============================
@router.get("/leistungsnachweise")
def leistung_nachweise_view(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Zeigt alle gesendeten Abrechnungen mit Möglichkeit,
    einen unterschriebenen Leistungsnachweis (PDF) hochzuladen.
    Zusätzlich wird geprüft, ob der kombinierte Leistungsnachweis_komplett.pdf vorhanden ist.
    """
    abrechnungen = (
        db.query(Abrechnung)
        .filter(Abrechnung.gesendet_am.isnot(None))
        .order_by(Abrechnung.gesendet_am.desc())
        .all()
    )

    cfg = db.get(Einstellungen, 1)
    verfahrenskennung = cfg.verfahrenskennung or "TPFL0" if cfg else "TPFL0"

    abr_ln_list = []
    for a in abrechnungen:
        export_dir = get_abrechnung_export_dir(a)
        transfer_nummer = f"{a.id % 1000:03d}"
        transfername = f"{verfahrenskennung}{transfer_nummer}"

        ln_path = export_dir / f"{transfername}_Leistungsnachweis.pdf"
        combined_path = export_dir / f"{transfername}_Leistungsnachweis_komplett.pdf"

        abr_ln_list.append(
            {
                "abr": a,
                "ln_exists": ln_path.exists(),
                "ln_url": f"/archiv/{a.id}/leistungsnachweis" if ln_path.exists() else None,
                "combined_exists": combined_path.exists(),
                "combined_url": f"/archiv/{a.id}/leistungsnachweis_komplett" if combined_path.exists() else None,
            }
        )

    return templates.TemplateResponse(
        "leistungsnachweise.html",
        {
            "request": request,
            "items": abr_ln_list,
        },
    )


@router.post("/leistungsnachweise/{abrechnung_id}/upload")
async def upload_leistungsnachweis(
    abrechnung_id: int,
    ln_pdf: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    1. Hochgeladenen Leistungsnachweis als Original-PDF speichern
    2. Unterschrift aus dem PDF extrahieren
    3. Anlage 3 (empfang.pdf) als Seite 1 rendern
    4. Unterschrift 2 (mit Summen + Signatur) als Seite 2 rendern
    5. Alles zu <transfername>_Leistungsnachweis_komplett.pdf kombinieren
    """
    # --- 1️⃣ Abrechnung holen ---
    abrechnung = db.get(Abrechnung, abrechnung_id)
    if not abrechnung:
        return RedirectResponse(url="/leistungsnachweise", status_code=303)

    patient: Optional[Patient] = abrechnung.patient
    if not patient:
        return HTMLResponse("Abrechnung ohne gültigen Patienten – Abbruch.", status_code=400)

    # --- 2️⃣ Datei prüfen & Original speichern ---
    content_type = (ln_pdf.content_type or "").lower()
    if "pdf" not in content_type and not (ln_pdf.filename or "").lower().endswith(".pdf"):
        return HTMLResponse("Bitte eine PDF-Datei hochladen.", status_code=400)

    cfg = db.get(Einstellungen, 1)
    verfahrenskennung = cfg.verfahrenskennung or "TPFL0" if cfg else "TPFL0"

    export_dir = get_abrechnung_export_dir(abrechnung)
    export_dir.mkdir(parents=True, exist_ok=True)

    transfer_nummer = f"{abrechnung.id % 1000:03d}"
    transfername = f"{verfahrenskennung}{transfer_nummer}"

    ln_path = export_dir / f"{transfername}_Leistungsnachweis.pdf"
    ln_combined = export_dir / f"{transfername}_Leistungsnachweis_komplett.pdf"

    # Original speichern
    with ln_path.open("wb") as f:
        shutil.copyfileobj(ln_pdf.file, f)

    # --- 3️⃣ Unterschrift aus Original extrahieren ---
    sign_buf = None
    try:
        sign_buf = extract_signature_from_pflegeantrag(str(ln_path))
        if sign_buf:
            print(f"[SIGNATURE] Signatur erfolgreich extrahiert aus {ln_path}")
        else:
            print("[SIGNATURE] Keine Unterschrift gefunden – fortfahren ohne Signatur")
    except Exception as e:
        print("[SIGNATURE] Fehler bei der Extraktion:", repr(e))
        # wir brechen nicht ab, sondern rendern ohne Signatur

    # --- 4️⃣ Positionen aus DB holen + Netto/Brutto berechnen ---
    # MwSt aus Konfiguration (falls pflichtig), sonst 0
    mwst_satz = Decimal("0")
    ust_pflichtig = False
    if cfg:
        ust_pflichtig = bool(cfg.ust_pflichtig)
        try:
            mwst_satz = Decimal(str(cfg.ust_satz or "0"))
        except Exception:
            mwst_satz = Decimal("0")

    if ust_pflichtig and mwst_satz > 0:
        mwst_factor = Decimal("1") + (mwst_satz / Decimal("100"))
    else:
        mwst_factor = Decimal("1")  # keine MwSt

    pos_list = (
        db.query(AbrechnungsPosition)
        .filter_by(abrechnung_id=abrechnung.id)
        .all()
    )

    produkte: list[dict] = []
    total_net = Decimal("0.00")
    total_gross = Decimal("0.00")

    for pos in pos_list:
        name = pos.hilfsmittel.bezeichnung if pos.hilfsmittel else "Unbekannt"
        menge = int(pos.menge)

        brutto_gesamt = Decimal(pos.betrag_gesamt)

        if mwst_factor != Decimal("1"):
            # brutto = netto * (1+mwst)  → netto = brutto / faktor
            net = (brutto_gesamt / mwst_factor).quantize(Decimal("0.01"))
        else:
            # keine MwSt → net = brutto
            net = brutto_gesamt

        produkte.append(
            {
                "name": name,
                "qty": menge,
                "net": net,
                "gross": brutto_gesamt,
            }
        )

        total_net += net
        total_gross += brutto_gesamt

    produkte_dict = {p["name"]: p["qty"] for p in produkte}

    # --- 5️⃣ Templates prüfen ---
    ANLAGE3_TEMPLATE = Path("app/static/empfang.pdf")
    UNTERSCHRIFT2_TEMPLATE = Path("app/static/unterschrift_zwei.pdf")

    if not ANLAGE3_TEMPLATE.exists():
        return HTMLResponse("Fehler: empfang.pdf fehlt im app/static/-Ordner.", status_code=500)
    if not UNTERSCHRIFT2_TEMPLATE.exists():
        return HTMLResponse("Fehler: unterschrift_zwei.pdf fehlt im app/static/-Ordner.", status_code=500)

    # --- 6️⃣ PDFs rendern & kombinieren ---
    try:
        # Seite 1: Anlage 3 (offizielles Formular / Empfangsbestätigung)
        anlage3_pdf = render_anlage3(
            template_path=str(ANLAGE3_TEMPLATE),
            patient={
                "kasse": abrechnung.kasse.name if abrechnung.kasse else "",
                "name_addr_tel": f"{patient.name}\n{patient.address or ''}",
                "versicherten_nr": getattr(patient, "versichertennummer", ""),
                "versorgungsmonat": abrechnung.abrechnungsmonat,
            },
            leistungserbringer=None,   # oder dict, wenn du überschreiben willst
            produkte_pos=produkte,
            mwst=mwst_satz / Decimal("100") if mwst_factor != Decimal("1") else Decimal("0"),
        )

        # Seite 2: Unterschrift Zwei (Summen + Checkbox + Signatur)
        unterschrift2_pdf = render_unterschrift_zwei(
            template_path=str(UNTERSCHRIFT2_TEMPLATE),
            data={
                "patient_name": patient.name,
                "abrechnungsmonat": abrechnung.abrechnungsmonat,
                "produkte": produkte_dict,
            },
            positions=produkte,
            total_net=total_net,
            total_gross=total_gross,
            mwst=mwst_satz / Decimal("100") if mwst_factor != Decimal("1") else Decimal("0"),
            signature=sign_buf,
        )

        # Beide Seiten zu einer kombinierten PDF zusammenführen
        combine_pdfs(
            [anlage3_pdf, unterschrift2_pdf],
            output_path=str(ln_combined),
        )

        print(f"[PDF] Leistungsnachweis kombiniert gespeichert unter {ln_combined}")

    except Exception as e:
        return HTMLResponse(f"Fehler beim Generieren der PDF-Dateien: {e}", status_code=500)

    # --- 7️⃣ Erfolg / Weiterleitung ---
    return RedirectResponse(url="/leistungsnachweise", status_code=303)


@router.get("/archiv/{abrechnung_id}/leistungsnachweis_komplett")
def download_leistungsnachweis_komplett(
    abrechnung_id: int,
    db: Session = Depends(get_db),
):
    """
    Kombinierte Version (Empfang + Unterschrift_zwei) ausliefern.
    """
    abrechnung = db.get(Abrechnung, abrechnung_id)
    if not abrechnung:
        return RedirectResponse(url="/archiv", status_code=303)

    cfg = db.get(Einstellungen, 1)
    verfahrenskennung = cfg.verfahrenskennung or "TPFL0" if cfg else "TPFL0"

    export_dir = get_abrechnung_export_dir(abrechnung)
    transfer_nummer = f"{abrechnung.id % 1000:03d}"
    transfername = f"{verfahrenskennung}{transfer_nummer}"
    pdf_path = export_dir / f"{transfername}_Leistungsnachweis_komplett.pdf"

    if not pdf_path.exists():
        return HTMLResponse(
            f"Kein kombinierter Leistungsnachweis für Abrechnung {abrechnung.id} gefunden.",
            status_code=404,
        )

    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        filename=pdf_path.name,
    )