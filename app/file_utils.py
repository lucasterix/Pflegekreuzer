"""
Sichere Dateioperationen und Pfad-Sanitization für Pflegekreuzer.
"""
import os
import re
from pathlib import Path
from typing import BinaryIO, TextIO


class SecureFileHandler:
    """Sichere Dateioperationen mit Pfad-Validierung."""

    # Erlaubte Zeichen für Dateinamen: Buchstaben, Zahlen, Bindestrich, Unterstrich, Punkt
    SAFE_FILENAME_PATTERN = re.compile(r'^[a-zA-Z0-9\-_\.]+$')

    # Basis-Verzeichnisse, die erlaubt sind
    ALLOWED_BASE_DIRS = {
        "exports",
        "uploads",
        "temp",
        "static",
        "crypto"
    }

    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """Sanitize einen Dateinamen, entferne gefährliche Zeichen."""
        if not filename:
            raise ValueError("Dateiname darf nicht leer sein")

        # Entferne gefährliche Zeichen
        safe_name = re.sub(r'[^\w\-_\.]', '_', filename)

        # Stelle sicher, dass es kein Pfad ist
        if '/' in safe_name or '\\' in safe_name:
            raise ValueError("Dateiname darf keine Pfad-Trenner enthalten")

        # Stelle sicher, dass es nicht mit . oder .. beginnt
        if safe_name.startswith('.') or safe_name.startswith('..'):
            raise ValueError("Dateiname darf nicht mit . oder .. beginnen")

        return safe_name

    @staticmethod
    def validate_path(base_dir: Path, relative_path: str) -> Path:
        """Validiere einen relativen Pfad innerhalb eines erlaubten Basis-Verzeichnisses."""
        if not relative_path:
            raise ValueError("Pfad darf nicht leer sein")

        # Stelle sicher, dass der Basis-Pfad erlaubt ist
        if base_dir.name not in SecureFileHandler.ALLOWED_BASE_DIRS:
            raise ValueError(f"Basis-Verzeichnis {base_dir.name} ist nicht erlaubt")

        # Resolve den Pfad und stelle sicher, dass er innerhalb des Basis-Verzeichnisses bleibt
        full_path = (base_dir / relative_path).resolve()

        # Sicherheitscheck: Pfad muss innerhalb des Basis-Verzeichnisses bleiben
        try:
            full_path.relative_to(base_dir.resolve())
        except ValueError:
            raise ValueError("Pfad verlässt das erlaubte Basis-Verzeichnis")

        return full_path

    @staticmethod
    def safe_open(path: Path, mode: str = 'r', **kwargs) -> BinaryIO | TextIO:
        """Öffne eine Datei sicher mit Pfad-Validierung."""
        # Stelle sicher, dass das Elternverzeichnis existiert
        path.parent.mkdir(parents=True, exist_ok=True)

        # Zusätzliche Sicherheit: Stelle sicher, dass der Pfad nicht in sensible Bereiche zeigt
        resolved = path.resolve()
        str_path = str(resolved)

        # Blockiere Zugriff auf sensible Dateien
        if any(sensitive in str_path.lower() for sensitive in ['.env', 'config', 'secret', '/etc/', '/root/']):
            raise ValueError("Zugriff auf sensible Datei blockiert")

        return path.open(mode, **kwargs)

    @staticmethod
    def safe_write_file(path: Path, content: bytes | str, mode: str = 'wb') -> None:
        """Schreibe sicher in eine Datei."""
        with SecureFileHandler.safe_open(path, mode) as f:
            f.write(content)

    @staticmethod
    def safe_read_file(path: Path, mode: str = 'rb') -> bytes | str:
        """Lese sicher aus einer Datei."""
        with SecureFileHandler.safe_open(path, mode) as f:
            return f.read()