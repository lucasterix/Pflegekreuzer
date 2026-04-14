import os
from fastapi.templating import Jinja2Templates
from weasyprint import HTML

templates = Jinja2Templates(directory="app/templates")

def generate_begleitzettel_pdf(abrechnung_id: int, send_dtm, db):
    from .models.abrechnung import Abrechnung
    from .models.patient import Patient
    from .models.settings import Settings

    abr = db.query(Abrechnung).filter(Abrechnung.id == abrechnung_id).first()
    if not abr:
        raise ValueError("Abrechnung existiert nicht")

    patient = abr.patient
    kasse   = patient.kasse if patient else None
    cfg     = db.query(Settings).first()

    # Versandzeit formatieren
    dt_str = send_dtm.strftime("%Y%m%d")
    tm_str = send_dtm.strftime("%H%M")

    # HTML rendern (Template ohne base.html!)
    html = templates.get_template("begleitzettel.html").render(
        abrechnung=abr,
        patient=patient,
        kasse=kasse,
        cfg=cfg,
        erstellungsdatum=dt_str,
        erstellungszeit=tm_str,
        positionen=abr.positionen,
        transfername=f"TA1_{abr.id}",
        xml_filename=abr.xml_filename or "",
        auf_filename=abr.auf_filename or ""
    )

    # Ordner anlegen
    out_dir = f"archiv/{patient.id}/{abr.abrechnungsmonat}"
    os.makedirs(out_dir, exist_ok=True)

    out_path = os.path.join(out_dir, "begleitzettel.pdf")

    # PDF erzeugen
    HTML(string=html).write_pdf(out_path)

    return out_path