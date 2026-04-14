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


APP_LOGIN_USER = os.environ.get("APP_LOGIN_USER", "abrechnung@froehlichdienste.de")
APP_LOGIN_PASSWORD = os.environ.get("APP_LOGIN_PASSWORD", "FrohZeit123")
CONFIG_PASSWORD = os.environ.get("CONFIG_PASSWORD", "Einheitsfront1A+")
APP_LOGIN_PASSWORD_HASH = os.environ.get("APP_LOGIN_PASSWORD_HASH", "")
CONFIG_PASSWORD_HASH = os.environ.get("CONFIG_PASSWORD_HASH", "")
APP_AUTH_COOKIE_NAME = os.environ.get("APP_AUTH_COOKIE_NAME", "app_auth")
AUTH_COOKIE_NAME = os.environ.get("AUTH_COOKIE_NAME", "cfg_auth")
APP_AUTH_COOKIE_SECRET = os.environ.get("APP_AUTH_COOKIE_SECRET", "please_change_this_secret")
CFG_AUTH_COOKIE_SECRET = os.environ.get("CFG_AUTH_COOKIE_SECRET", APP_AUTH_COOKIE_SECRET)
SESSION_COOKIE_SECURE = _bool_env("SESSION_COOKIE_SECURE", False)
SESSION_COOKIE_SAMESITE = os.environ.get("SESSION_COOKIE_SAMESITE", "lax")

# Falls ein Hash vorhanden ist, benutzen wir diesen statt eines Klartextpassworts.
if APP_LOGIN_PASSWORD_HASH:
    APP_LOGIN_PASSWORD = APP_LOGIN_PASSWORD_HASH
if CONFIG_PASSWORD_HASH:
    CONFIG_PASSWORD = CONFIG_PASSWORD_HASH

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg2://pflege:pflegepass@localhost:5432/pflege",
)
