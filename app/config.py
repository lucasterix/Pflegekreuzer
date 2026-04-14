import os

from dotenv import load_dotenv  # type: ignore

# Lade Umgebungsvariablen aus einer externen Datei, falls vorhanden.
# Das entspricht dem bestehenden /etc/pflegeweb.env use-case.
load_dotenv("/etc/pflegeweb.env")
load_dotenv()


def _bool_env(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _require_env(name: str) -> str:
    """Erzwingt eine Umgebungsvariable – keine Fallbacks für sensible Daten."""
    value = os.environ.get(name)
    if not value or value.strip() == "":
        raise ValueError(f"Umgebungsvariable {name} ist erforderlich und darf nicht leer sein.")
    return value.strip()


# Authentifizierung – erzwinge echte Werte, keine Defaults
APP_LOGIN_USER = _require_env("APP_LOGIN_USER")
APP_LOGIN_PASSWORD = _require_env("APP_LOGIN_PASSWORD")
CONFIG_PASSWORD = _require_env("CONFIG_PASSWORD")

# Optional: gehashte Passwörter (überschreiben Klartext)
APP_LOGIN_PASSWORD_HASH = os.environ.get("APP_LOGIN_PASSWORD_HASH", "")
CONFIG_PASSWORD_HASH = os.environ.get("CONFIG_PASSWORD_HASH", "")
if APP_LOGIN_PASSWORD_HASH:
    APP_LOGIN_PASSWORD = APP_LOGIN_PASSWORD_HASH
if CONFIG_PASSWORD_HASH:
    CONFIG_PASSWORD = CONFIG_PASSWORD_HASH

# Cookie-Namen
APP_AUTH_COOKIE_NAME = os.environ.get("APP_AUTH_COOKIE_NAME", "app_auth")
AUTH_COOKIE_NAME = os.environ.get("AUTH_COOKIE_NAME", "cfg_auth")

# Cookie-Secrets – erzwinge echte Werte
APP_AUTH_COOKIE_SECRET = _require_env("APP_AUTH_COOKIE_SECRET")
CFG_AUTH_COOKIE_SECRET = os.environ.get("CFG_AUTH_COOKIE_SECRET", APP_AUTH_COOKIE_SECRET)

# Cookie-Sicherheit – HTTPS erzwingen
SESSION_COOKIE_SECURE = _bool_env("SESSION_COOKIE_SECURE", True)  # Default: True für Produktion
SESSION_COOKIE_SAMESITE = os.environ.get("SESSION_COOKIE_SAMESITE", "strict")  # Strenger als lax

# Datenbank – erzwinge echte URL
DATABASE_URL = _require_env("DATABASE_URL")
