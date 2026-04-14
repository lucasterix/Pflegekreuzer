import hashlib
import hmac
import secrets
from typing import Optional

HASH_PREFIX = "pbkdf2_sha256"
DEFAULT_ITERATIONS = 200_000
SALT_SIZE = 16


def _pbkdf2(password: str, salt: bytes, iterations: int = DEFAULT_ITERATIONS) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)


def hash_password(password: str, salt: Optional[bytes] = None, iterations: int = DEFAULT_ITERATIONS) -> str:
    if salt is None:
        salt = secrets.token_bytes(SALT_SIZE)
    digest = _pbkdf2(password, salt, iterations)
    return f"{HASH_PREFIX}${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    if stored.startswith(f"{HASH_PREFIX}$"):
        try:
            _, iterations_str, salt_hex, digest_hex = stored.split("$", 3)
            iterations = int(iterations_str)
            salt = bytes.fromhex(salt_hex)
            expected = bytes.fromhex(digest_hex)
        except (ValueError, TypeError):
            return False
        computed = _pbkdf2(password, salt, iterations)
        return hmac.compare_digest(computed, expected)

    return hmac.compare_digest(password, stored)


def create_signed_cookie(value: str, secret: str) -> str:
    signature = hmac.new(secret.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{value}:{signature}"


def verify_signed_cookie(cookie_value: str, secret: str) -> Optional[str]:
    if not cookie_value or ":" not in cookie_value:
        return None
    value, signature = cookie_value.rsplit(":", 1)
    expected = hmac.new(secret.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()
    if hmac.compare_digest(signature, expected):
        return value
    return None
