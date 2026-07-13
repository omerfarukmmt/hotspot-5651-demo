"""5651 Sayılı Kanun uyumlu loglama ve dijital imzalama katmanı.

- Log satırları RFC 5424 (Syslog) formatındadır:
  <PRI>VERSION TIMESTAMP HOSTNAME APP-NAME PROCID MSGID [meta IP=".." MAC=".." USER=".."] MESAJ
- İmzalama: log dosyasının SHA-256 özeti, RSA-2048 özel anahtarı ile (PKCS#1 v1.5)
  imzalanır ve `dhcp_activity.log.signed` dosyasına yazılır (zaman damgası simülasyonu).
- Doğrulama: dosyanın güncel özeti yeniden hesaplanır ve imza public key ile kontrol
  edilir; tek karakterlik değişiklik bile imzayı geçersiz kılar.
"""
import base64
import hashlib
import json
import os
import threading
from datetime import datetime, timezone

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa, utils

LOG_DIR = os.getenv("LOG_DIR", "/app/logs")
LOG_FILE = os.path.join(LOG_DIR, "dhcp_activity.log")
SIGNED_FILE = LOG_FILE + ".signed"
KEY_FILE = os.path.join(LOG_DIR, "signing_key.pem")

HOSTNAME = "hotspot-gw"
APP_NAME = "hotspot-5651"
PRI = 134  # facility=local0(16)*8 + severity=info(6)

_write_lock = threading.Lock()


def _ensure_log_dir() -> None:
    os.makedirs(LOG_DIR, exist_ok=True)


def load_or_create_private_key() -> rsa.RSAPrivateKey:
    """RSA-2048 anahtarını diskte tutar; yoksa otomatik üretir.

    Not: Gerçek bir kurulumda özel anahtar HSM/KMS içinde saklanmalıdır;
    demo amacıyla logs/ altında PEM olarak tutulur.
    """
    _ensure_log_dir()
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, "rb") as f:
            return serialization.load_pem_private_key(f.read(), password=None)

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    with open(KEY_FILE, "wb") as f:
        f.write(pem)
    print(f"[log_manager] Yeni RSA-2048 imza anahtarı üretildi: {KEY_FILE}", flush=True)
    return key


def _rfc5424_timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def write_log(msgid: str, ip: str, mac: str, user: str, message: str) -> str:
    """RFC 5424 uyumlu tek satır log yazar ve satırı döndürür."""
    _ensure_log_dir()
    line = (
        f"<{PRI}>1 {_rfc5424_timestamp()} {HOSTNAME} {APP_NAME} {os.getpid()} {msgid} "
        f'[meta IP="{ip}" MAC="{mac}" USER="{user}"] {message}'
    )
    with _write_lock:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    print(f"[5651-LOG] {line}", flush=True)
    return line


def _sha256_of_file(path: str) -> "hashlib._Hash":
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h


def sign_log_file() -> dict:
    """Log dosyasının SHA-256 özetini RSA ile imzalar ve .signed dosyası üretir."""
    if not os.path.exists(LOG_FILE):
        raise FileNotFoundError("İmzalanacak log dosyası henüz oluşmadı: dhcp_activity.log")

    key = load_or_create_private_key()
    digest = _sha256_of_file(LOG_FILE)
    digest_bytes = digest.digest()

    signature = key.sign(
        digest_bytes,
        padding.PKCS1v15(),
        utils.Prehashed(hashes.SHA256()),
    )

    public_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")

    with open(LOG_FILE, "r", encoding="utf-8") as f:
        line_count = sum(1 for _ in f)

    meta = {
        "signed_at": _rfc5424_timestamp(),
        "log_file": os.path.basename(LOG_FILE),
        "line_count": line_count,
        "sha256": digest.hexdigest(),
        "signature_b64": base64.b64encode(signature).decode("ascii"),
        "algorithm": "RSA-2048 / PKCS#1 v1.5 / SHA-256",
        "note": "5651 uyumlu zaman damgasi simulasyonu (self-signed). "
                "Gercek sistemde TUBITAK/BTK onayli zaman damgasi sunucusu kullanilir.",
        "public_key_pem": public_pem,
    }
    with open(SIGNED_FILE, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"[log_manager] Log imzalandı -> {SIGNED_FILE} (SHA-256: {meta['sha256']})", flush=True)
    return meta


def verify_log_file() -> dict:
    """İmzayı doğrular. Log dosyasında tek karakter değişse bile 'valid: false' döner."""
    if not os.path.exists(SIGNED_FILE):
        raise FileNotFoundError("İmza dosyası bulunamadı. Önce /api/v1/log/sign çağırın.")
    if not os.path.exists(LOG_FILE):
        raise FileNotFoundError("Log dosyası bulunamadı: dhcp_activity.log")

    with open(SIGNED_FILE, "r", encoding="utf-8") as f:
        meta = json.load(f)

    current_digest = _sha256_of_file(LOG_FILE)
    current_hex = current_digest.hexdigest()
    hash_matches = current_hex == meta.get("sha256")

    public_key = serialization.load_pem_public_key(meta["public_key_pem"].encode("ascii"))
    signature = base64.b64decode(meta["signature_b64"])

    signature_valid = False
    try:
        public_key.verify(
            signature,
            current_digest.digest(),
            padding.PKCS1v15(),
            utils.Prehashed(hashes.SHA256()),
        )
        signature_valid = True
    except InvalidSignature:
        signature_valid = False

    valid = hash_matches and signature_valid
    return {
        "valid": valid,
        "hash_matches": hash_matches,
        "signature_valid": signature_valid,
        "signed_at": meta.get("signed_at"),
        "expected_sha256": meta.get("sha256"),
        "current_sha256": current_hex,
        "message": (
            "Log dosyası bütünlüğü DOĞRULANDI. İmza geçerli."
            if valid
            else "UYARI: Log dosyası imzalandıktan sonra DEĞİŞTİRİLMİŞ! İmza geçersiz."
        ),
    }
