"""API istek/yanıt şemaları (Pydantic)."""
from pydantic import BaseModel, Field


class TCLoginRequest(BaseModel):
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    birth_year: int = Field(..., ge=1900)  # üst sınır mock_mernis_verify içinde (içinde bulunulan yıl)
    tc_no: str = Field(..., min_length=11, max_length=11)
    kvkk_approved: bool


class SmsRequestBody(BaseModel):
    phone: str = Field(..., min_length=10, max_length=20)
    kvkk_approved: bool


class SmsVerifyBody(BaseModel):
    phone: str = Field(..., min_length=10, max_length=20)
    code: str = Field(..., min_length=6, max_length=6)


class LoginResponse(BaseModel):
    status: str
    message: str
    session_ttl: int
    ip: str
    mac: str


class SmsRequestResponse(BaseModel):
    status: str
    message: str
    demo_otp: str
    expires_in: int
