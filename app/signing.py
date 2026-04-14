import subprocess
import tempfile
from pathlib import Path
from typing import Optional


CERT_PATH = Path("crypto/test-cert.pem")   # <-- eigene Zertifikate möglich
KEY_PATH  = Path("crypto/test-key.pem")    # <-- privater Schlüssel dazu


def sign_edifact(
    edifact_bytes: bytes,
    cert_path: Path = CERT_PATH,
    key_path: Path = KEY_PATH,
    key_passphrase: Optional[str] = None,
) -> bytes:
    """
    Signiert EDIFACT als PKCS#7 SignedData (DER, binary, attached).

    ✦ Enthält die EDIFACT-Daten *eingebettet* (nicht detached!)
    ✦ Genau dieses Format erwartet TA3 gemäß GKV-Spezifikation
    ✦ Wenn Schlüssel/Zertifikat fehlen → EDIFACT wird unsigniert zurückgegeben
    """

    if not cert_path.exists() or not key_path.exists():
        print("[SIGNING] ❗ Kein Zertifikat/Key gefunden → Datei bleibt UNSIGNIERT.")
        return edifact_bytes

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        message_path = tmp / "edifact.dat"
        signed_path  = tmp / "signed.p7m"

        message_path.write_bytes(edifact_bytes)

        cmd = [
            "openssl", "smime",
            "-sign",
            "-binary", "-nodetach", "-noattr",       # 🔥 PAYLOAD eingebettet!
            "-in", str(message_path),
            "-signer", str(cert_path),
            "-inkey", str(key_path),
            "-outform", "DER",
            "-out", str(signed_path)
        ]

        # falls Schlüssel Passwort hat
        if key_passphrase:
            cmd.extend(["-passin", f"pass:{key_passphrase}"])

        result = subprocess.run(cmd, capture_output=True)

        if result.returncode != 0:
            print("[SIGNING] ❌ OpenSSL-Signatur fehlgeschlagen → unsigniert.")
            print("stderr:", result.stderr.decode("utf-8"))
            return edifact_bytes

        print(f"[SIGNING] ✔ PKCS#7 erzeugt ({signed_path.stat().st_size} Bytes)")

        return signed_path.read_bytes()