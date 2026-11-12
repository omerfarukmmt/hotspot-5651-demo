"""TC Kimlik No algoritması ve yardımcı fonksiyon testleri.

`main` modülü import edilirken PostgreSQL/Redis'e BAĞLANILMAZ (bağlantılar tembeldir),
bu yüzden bu testler de Docker gerektirmez.
"""
import pytest
from fastapi import HTTPException

import main


@pytest.mark.parametrize("tc", ["10000000146", "12345678950"])
def test_valid_tc_numbers(tc):
    assert main.mock_mernis_verify(tc, "Ali", "Yılmaz", 1995)


@pytest.mark.parametrize(
    "tc",
    [
        "10000000145",   # 11. hane checksum hatalı
        "10000000156",   # 10. hane checksum hatalı
        "01234567890",   # 0 ile başlayamaz
        "1000000014",    # 10 hane
        "1000000014a",   # rakam olmayan karakter
    ],
)
def test_invalid_tc_numbers(tc):
    assert not main.mock_mernis_verify(tc, "Ali", "Yılmaz", 1995)


def test_birth_year_and_names_required():
    assert not main.mock_mernis_verify("10000000146", "", "Yılmaz", 1995)
    assert not main.mock_mernis_verify("10000000146", "Ali", "Yılmaz", 1899)
    assert not main.mock_mernis_verify("10000000146", "Ali", "Yılmaz", main.utcnow().year + 1)


def test_simulate_mac_is_deterministic():
    assert main.simulate_mac("192.168.4.50") == "02:00:C0:A8:04:32"
    assert main.simulate_mac("192.168.4.50") == main.simulate_mac("192.168.4.50")


def test_normalize_phone():
    assert main.normalize_phone("+90 (555) 123 45 67") == "5551234567"
    with pytest.raises(HTTPException):
        main.normalize_phone("12345")
