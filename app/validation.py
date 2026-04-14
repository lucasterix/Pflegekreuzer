from pathlib import Path
from lxml import etree

# Ordner, in dem deine XSDs liegen
XSD_DIR = Path("xsd")

# Hauptschema – das importiert die anderen
PFL_DAT_XSD = XSD_DIR / "PFL_DAT_2.2.0.xsd"


def _load_schema() -> etree.XMLSchema:
    """Lädt das PFL_DAT-Schema (inkl. seiner Imports)."""
    if not PFL_DAT_XSD.exists():
        raise FileNotFoundError(f"XSD-Datei nicht gefunden: {PFL_DAT_XSD}")

    with open(PFL_DAT_XSD, "rb") as f:
        schema_doc = etree.parse(f)
    return etree.XMLSchema(schema_doc)


# Schema einmalig auf Modul-Ebene laden
_PFL_SCHEMA = None


def get_pfl_schema() -> etree.XMLSchema:
    global _PFL_SCHEMA
    if _PFL_SCHEMA is None:
        _PFL_SCHEMA = _load_schema()
    return _PFL_SCHEMA


def validate_pfl_file(xml_path: Path) -> tuple[bool, list[str]]:
    """
    Validiert eine PFL_DAT-XML-Datei gegen das Schema.

    Rückgabe:
      - bool: True, wenn gültig
      - Liste von Fehlerstrings, wenn ungültig
    """
    schema = get_pfl_schema()

    if not xml_path.exists():
        return False, [f"XML-Datei nicht gefunden: {xml_path}"]

    xml_doc = etree.parse(str(xml_path))
    is_valid = schema.validate(xml_doc)

    if is_valid:
        return True, []

    errors: list[str] = []
    for error in schema.error_log:
        errors.append(str(error))

    return False, errors