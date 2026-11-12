"""log_manager: imzalama, kurcalama tespiti ve imza zinciri testleri.

Çalıştırma (backend/ dizininde):  python -m pytest -q
Docker, PostgreSQL veya Redis gerektirmez.
"""
import base64
import importlib
import json
import os

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa, utils


@pytest.fixture()
def lm(tmp_path, monkeypatch):
    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    import log_manager
    return importlib.reload(log_manager)


def _write_some(lm, n=3):
    for i in range(n):
        lm.write_log("LOGIN", f"192.168.4.{10 + i}", "02:00:C0:A8:04:0A", f"user{i}", "test")


def test_log_line_is_rfc5424(lm):
    line = lm.write_log("LOGIN", "192.168.4.50", "AA:BB:CC:DD:EE:FF", "10000000146", "Giris")
    assert line.startswith("<134>1 ")
    assert 'IP="192.168.4.50" MAC="AA:BB:CC:DD:EE:FF" USER="10000000146"' in line


def test_sign_then_verify_valid(lm):
    _write_some(lm)
    lm.sign_log_file()
    result = lm.verify_log_file()
    assert result["valid"] is True
    assert result["key_matches_server"] is True


def test_single_char_tamper_detected(lm):
    _write_some(lm)
    lm.sign_log_file()
    with open(lm.LOG_FILE, "r+", encoding="utf-8") as f:
        data = f.read()
        f.seek(0)
        f.write(data.replace("user1", "userX", 1))
    assert lm.verify_log_file()["valid"] is False


def test_resign_with_foreign_key_is_rejected(lm):
    """Saldırgan logu değiştirip KENDİ anahtarıyla yeniden imzalarsa ve .signed
    dosyasına kendi public key'ini koyarsa doğrulama yine de başarısız olmalı."""
    _write_some(lm)
    lm.sign_log_file()
    with open(lm.LOG_FILE, "a", encoding="utf-8") as f:
        f.write("sahte satir\n")

    attacker = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    digest = lm._sha256_of_file(lm.LOG_FILE)
    sig = attacker.sign(digest.digest(), padding.PKCS1v15(), utils.Prehashed(hashes.SHA256()))
    with open(lm.SIGNED_FILE, "r", encoding="utf-8") as f:
        meta = json.load(f)
    meta["sha256"] = digest.hexdigest()
    meta["signature_b64"] = base64.b64encode(sig).decode()
    meta["public_key_pem"] = attacker.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    with open(lm.SIGNED_FILE, "w", encoding="utf-8") as f:
        json.dump(meta, f)

    result = lm.verify_log_file()
    assert result["hash_matches"] is True       # özet tutarlı yeniden hesaplanmış...
    assert result["signature_valid"] is False   # ...ama sunucunun anahtarıyla imzalanmamış
    assert result["key_matches_server"] is False
    assert result["valid"] is False


def test_rotation_chain_valid_and_tamper_detected(lm):
    for _ in range(3):
        _write_some(lm, 2)
        lm.rotate_and_seal_log()
    chain = lm.verify_chain()
    assert chain["valid"] is True and chain["entry_count"] == 3
    assert not os.path.exists(lm.LOG_FILE)  # aktif log arşive taşındı

    archived = os.path.join(lm.ARCHIVE_DIR, chain["entries"][1]["archived_file"])
    with open(archived, "a", encoding="utf-8") as f:
        f.write("x")
    chain = lm.verify_chain()
    assert chain["valid"] is False
    assert chain["entries"][1]["archive_file_matches"] is False
    assert chain["entries"][0]["valid"] and chain["entries"][2]["valid"]


def test_missing_archive_breaks_chain(lm):
    _write_some(lm)
    entry = lm.rotate_and_seal_log()
    os.remove(os.path.join(lm.ARCHIVE_DIR, entry["archived_file"]))
    chain = lm.verify_chain()
    assert chain["valid"] is False
    assert chain["entries"][0]["archive_file_present"] is False


def test_deleted_chain_entry_detected(lm):
    for _ in range(3):
        _write_some(lm, 1)
        lm.rotate_and_seal_log()
    with open(lm.CHAIN_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()
    with open(lm.CHAIN_FILE, "w", encoding="utf-8") as f:
        f.writelines([lines[0], lines[2]])  # ortadaki dönem sessizce silindi
    chain = lm.verify_chain()
    assert chain["valid"] is False
    assert chain["entries"][1]["chain_intact"] is False
