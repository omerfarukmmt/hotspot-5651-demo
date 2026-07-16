"""5651 Sayılı Kanun Uyumlu Hotspot (Captive Portal) Demo — FastAPI backend.

Bileşenler:
- Mock MERNİS doğrulaması (TC Kimlik No algoritma kontrolü)
- SMS OTP simülasyonu (Redis, 3 dk TTL)
- Oturum yönetimi (Redis, 2 saat / 7200 sn TTL)
- PostgreSQL: users + sessions kalıcı kayıtları
- RFC 5424 loglama + RSA dijital imza (log_manager)
"""
import asyncio
import hashlib
import json
import os
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import redis as redis_lib
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session as DbSession

import dns_log_watcher
import log_manager
import models
import nft_manager
import schemas
from database import Base, SessionLocal, engine, get_db, wait_for_db

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
SESSION_TTL = int(os.getenv("SESSION_TTL_SECONDS", "7200"))  # 2 saat
OTP_TTL = int(os.getenv("OTP_TTL_SECONDS", "180"))  # 3 dakika
DNSMASQ_LOG_FILE = os.getenv("DNSMASQ_LOG_FILE", "/app/logs/dnsmasq_query.log")
# Gerçek hotspot kurulumunda dnsmasq'ın lease dosyasına işaret eder (bkz. network/README.md).
# Docker demo ortamında boş bırakılır; bu durumda MAC her zaman simulate_mac() ile türetilir.
DNSMASQ_LEASES_FILE = os.getenv("DNSMASQ_LEASES_FILE", "")
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "changeme-admin-key")

# Rate limiting / OTP kilitleme (bkz. _rate_limit, sms_verify) — brute-force ve
# SMS bombalama saldırılarına karşı; Redis sabit-pencere sayaçlarıyla uygulanır.
RATE_LIMIT_LOGIN_MAX = int(os.getenv("RATE_LIMIT_LOGIN_MAX", "10"))
RATE_LIMIT_LOGIN_WINDOW = int(os.getenv("RATE_LIMIT_LOGIN_WINDOW_SECONDS", "300"))
RATE_LIMIT_SMS_REQUEST_MAX = int(os.getenv("RATE_LIMIT_SMS_REQUEST_MAX", "3"))
RATE_LIMIT_SMS_REQUEST_WINDOW = int(os.getenv("RATE_LIMIT_SMS_REQUEST_WINDOW_SECONDS", "600"))
OTP_MAX_ATTEMPTS = int(os.getenv("OTP_MAX_ATTEMPTS", "5"))
OTP_LOCKOUT_SECONDS = int(os.getenv("OTP_LOCKOUT_SECONDS", "900"))  # 15 dakika

# Log rotasyon aralığı (bkz. _daily_log_rotator, log_manager.rotate_and_seal_log).
LOG_ROTATE_INTERVAL_SECONDS = int(os.getenv("LOG_ROTATE_INTERVAL_SECONDS", "86400"))  # 24 saat

rdb = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)


# ----------------------------------------------------------------------------
# Yardımcılar
# ----------------------------------------------------------------------------
def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def get_client_ip(request: Request) -> str:
    """Nginx arkasında X-Real-IP, doğrudan erişimde socket adresi."""
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "0.0.0.0")


def simulate_mac(ip: str) -> str:
    """IP adresinden deterministik sahte MAC üretir (gerçek ortamda DHCP/ARP tablosundan okunur)."""
    parts = ip.split(".")
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        return "02:00:" + ":".join(f"{int(p) & 0xFF:02X}" for p in parts)
    h = hashlib.md5(ip.encode()).hexdigest().upper()
    return "02:" + ":".join(h[i:i + 2] for i in range(0, 10, 2))


def get_real_mac(ip: str) -> str:
    """dnsmasq lease dosyasından gerçek MAC adresini okur (format: `expiry mac ip host client-id`).

    Lease dosyası tanımlı/erişilebilir değilse veya IP eşleşmiyorsa (Docker demo
    ortamı gibi) `simulate_mac()`'e düşer."""
    if DNSMASQ_LEASES_FILE:
        try:
            with open(DNSMASQ_LEASES_FILE, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 3 and parts[2] == ip:
                        return parts[1].upper()
        except OSError:
            pass
    return simulate_mac(ip)


def mock_mernis_verify(tc_no: str, first_name: str, last_name: str, birth_year: int) -> bool:
    """MERNİS KPSPublic servisinin yerel simülasyonu.

    Gerçek TC Kimlik No algoritmasını uygular:
    - 11 hane, ilk hane 0 olamaz
    - 10. hane = ((1,3,5,7,9. haneler toplamı * 7) - (2,4,6,8. haneler toplamı)) mod 10
    - 11. hane = ilk 10 hanenin toplamı mod 10
    """
    tc_no = tc_no.strip()
    if not tc_no.isdigit() or len(tc_no) != 11 or tc_no[0] == "0":
        return False
    d = [int(c) for c in tc_no]
    if ((sum(d[0:9:2]) * 7 - sum(d[1:8:2])) % 10) != d[9]:
        return False
    if sum(d[:10]) % 10 != d[10]:
        return False
    if not first_name.strip() or not last_name.strip():
        return False
    if not (1900 <= birth_year <= utcnow().year):
        return False
    return True


def _rate_limit(key: str, max_count: int, window_seconds: int) -> None:
    """Redis sabit pencereli sayaç: aynı pencere içinde max_count'u aşan istekleri 429 ile reddeder.

    `INCR` + ilk istekte `EXPIRE`: pencere süresi dolunca sayaç otomatik sıfırlanır."""
    current = rdb.incr(key)
    if current == 1:
        rdb.expire(key, window_seconds)
    if current > max_count:
        ttl = rdb.ttl(key)
        raise HTTPException(
            status_code=429,
            detail=f"Çok fazla istek. Lütfen {max(ttl, 1)} saniye sonra tekrar deneyin.",
        )


def normalize_phone(phone: str) -> str:
    digits = "".join(c for c in phone if c.isdigit())
    if len(digits) < 10:
        raise HTTPException(status_code=400, detail="Geçersiz telefon numarası.")
    return digits[-10:]  # 5XXXXXXXXX


def _create_session(db: DbSession, request: Request, response: Response, username: str) -> dict:
    """Başarılı kimlik doğrulama sonrası: Redis'e 2 saatlik TTL ile oturum yazar,
    PostgreSQL'e kalıcı kayıt atar, 5651 LOGIN logu üretir ve cookie set eder."""
    token = uuid.uuid4().hex
    ip = get_client_ip(request)
    mac = get_real_mac(ip)
    now = utcnow()

    session_payload = {
        "username": username,
        "ip": ip,
        "mac": mac,
        "login_time": now.isoformat(),
    }
    rdb.setex(f"session:{token}", SESSION_TTL, json.dumps(session_payload))

    record = models.SessionRecord(
        ip_address=ip,
        mac_address=mac,
        username=username,
        session_token=token,
        login_time=now,
        is_active=True,
    )
    db.add(record)
    db.commit()

    log_manager.write_log("LOGIN", ip, mac, username, "Kullanici sisteme giris yapti.")
    nft_manager.allow_client(ip)

    response.set_cookie(
        key="session_token",
        value=token,
        max_age=SESSION_TTL,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return {
        "status": "ok",
        "message": "Giriş başarılı. İnternet erişiminiz 2 saat boyunca aktif.",
        "session_ttl": SESSION_TTL,
        "ip": ip,
        "mac": mac,
    }


def _get_session_from_request(request: Request):
    token = request.cookies.get("session_token")
    if not token:
        return None, None
    raw = rdb.get(f"session:{token}")
    if not raw:
        return token, None
    return token, json.loads(raw)


def _active_session_for_ip(db: DbSession, ip: str) -> models.SessionRecord | None:
    """Bir IP'nin o anki sahibi olan aktif oturumu bulur (DNS sorgusunu kullanıcıya bağlamak için)."""
    return (
        db.query(models.SessionRecord)
        .filter(models.SessionRecord.ip_address == ip, models.SessionRecord.is_active.is_(True))
        .order_by(models.SessionRecord.login_time.desc())
        .first()
    )


def require_admin(x_admin_key: str = Header(default="")) -> None:
    """Site ziyaret loglarını görebilmek için basit paylaşılan-anahtar koruması (KVKK: bu veriler herkese açık olmamalı)."""
    if not secrets.compare_digest(x_admin_key, ADMIN_API_KEY):
        raise HTTPException(status_code=403, detail="Geçersiz yönetici anahtarı (X-Admin-Key).")


# ----------------------------------------------------------------------------
# Arka plan görevleri
# ----------------------------------------------------------------------------
async def _expired_session_reaper():
    """Redis TTL'i dolan oturumları PostgreSQL tarafında kapatır ve EXPIRE logu yazar."""
    while True:
        await asyncio.sleep(60)
        try:
            db = SessionLocal()
            try:
                active = db.query(models.SessionRecord).filter(
                    models.SessionRecord.is_active.is_(True)
                ).all()
                for rec in active:
                    if not rdb.exists(f"session:{rec.session_token}"):
                        rec.is_active = False
                        rec.logout_time = utcnow()
                        log_manager.write_log(
                            "EXPIRE", rec.ip_address, rec.mac_address, rec.username,
                            "Oturum suresi doldu (2 saatlik TTL), internet erisimi kapatildi.",
                        )
                        nft_manager.revoke_client(rec.ip_address)
                db.commit()
            finally:
                db.close()
        except Exception as exc:  # arka plan görevi asla ölmemeli
            print(f"[reaper] Hata: {exc}", flush=True)


async def _daily_log_rotator():
    """Günde bir kez aktif log dosyasını imzalayıp arşive taşır ve zincire ekler
    (manuel tetik: POST /api/v1/log/rotate). Log dosyasının sınırsız büyümesini
    önler ve her dönemin imzasını kalıcı olarak saklar (bkz. log_manager.rotate_and_seal_log)."""
    while True:
        await asyncio.sleep(LOG_ROTATE_INTERVAL_SECONDS)
        try:
            if os.path.exists(log_manager.LOG_FILE) and os.path.getsize(log_manager.LOG_FILE) > 0:
                log_manager.rotate_and_seal_log()
        except Exception as exc:
            print(f"[daily-rotator] Hata: {exc}", flush=True)


async def _dns_log_tailer():
    """dnsmasq'ın sorgu logunu izler, her domaini o anki aktif oturuma (kullanıcıya) bağlar;
    hem imzalı 5651 loguna hem de sorgulanabilir site_visits tablosuna yazar."""
    try:
        async for line in dns_log_watcher.follow(DNSMASQ_LOG_FILE):
            parsed = dns_log_watcher.parse_query_line(line)
            if not parsed:
                continue
            qtype, domain, ip = parsed
            try:
                db = SessionLocal()
                try:
                    session = _active_session_for_ip(db, ip)
                    username = session.username if session else "(kimliksiz)"
                    mac = session.mac_address if session else get_real_mac(ip)
                    db.add(models.SiteVisit(
                        username=username, ip_address=ip, mac_address=mac,
                        domain=domain, query_type=qtype,
                    ))
                    db.commit()
                finally:
                    db.close()
                log_manager.write_log(
                    "SITEVISIT", ip, mac, username, f"DNS sorgusu: {domain} (tip={qtype})",
                )
            except Exception as exc:
                print(f"[dns-tailer] Satır işlenemedi: {exc}", flush=True)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        print(f"[dns-tailer] Durdu: {exc}", flush=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    wait_for_db()
    Base.metadata.create_all(bind=engine)
    log_manager.load_or_create_private_key()
    log_manager.write_log("BOOT", "0.0.0.0", "00:00:00:00:00:00", "-", "Hotspot servisi baslatildi.")
    tasks = [
        asyncio.create_task(_expired_session_reaper()),
        asyncio.create_task(_daily_log_rotator()),
        asyncio.create_task(_dns_log_tailer()),
    ]
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(
    title="5651 Uyumlu Hotspot Demo",
    description="Captive Portal + MERNİS/SMS doğrulama + RFC 5424 imzalı loglama",
    version="1.0.0",
    lifespan=lifespan,
)


# ----------------------------------------------------------------------------
# Sağlık / durum
# ----------------------------------------------------------------------------
@app.get("/api/v1/health")
def health():
    rdb.ping()
    return {"status": "ok", "service": "hotspot-backend"}


# ----------------------------------------------------------------------------
# Kimlik doğrulama — TC Kimlik No (Mock MERNİS)
# ----------------------------------------------------------------------------
@app.post("/api/v1/auth/tc", response_model=schemas.LoginResponse)
def login_with_tc(
    body: schemas.TCLoginRequest,
    request: Request,
    response: Response,
    db: DbSession = Depends(get_db),
):
    ip = get_client_ip(request)
    _rate_limit(f"ratelimit:tc:{ip}", RATE_LIMIT_LOGIN_MAX, RATE_LIMIT_LOGIN_WINDOW)

    if not body.kvkk_approved:
        raise HTTPException(status_code=400, detail="KVKK açık rıza onayı zorunludur.")
    if not mock_mernis_verify(body.tc_no, body.first_name, body.last_name, body.birth_year):
        log_manager.write_log(
            "AUTHFAIL", ip, simulate_mac(ip), body.tc_no,
            "MERNIS dogrulamasi basarisiz (gecersiz TC kimlik bilgileri).",
        )
        raise HTTPException(
            status_code=400,
            detail="MERNİS doğrulaması başarısız: TC Kimlik No algoritması veya kimlik bilgileri geçersiz.",
        )

    user = db.query(models.User).filter(models.User.tc_no == body.tc_no).first()
    if not user:
        user = models.User(
            first_name=body.first_name.strip(),
            last_name=body.last_name.strip(),
            tc_no=body.tc_no.strip(),
            birth_year=body.birth_year,
        )
        db.add(user)
        db.commit()

    return _create_session(db, request, response, body.tc_no)


# ----------------------------------------------------------------------------
# Kimlik doğrulama — SMS OTP
# ----------------------------------------------------------------------------
@app.post("/api/v1/auth/sms/request", response_model=schemas.SmsRequestResponse)
def sms_request(body: schemas.SmsRequestBody, request: Request):
    if not body.kvkk_approved:
        raise HTTPException(status_code=400, detail="KVKK açık rıza onayı zorunludur.")
    phone = normalize_phone(body.phone)
    ip = get_client_ip(request)

    if rdb.exists(f"otp_lock:{phone}"):
        ttl = rdb.ttl(f"otp_lock:{phone}")
        raise HTTPException(
            status_code=429,
            detail=f"Çok fazla hatalı deneme nedeniyle bu numara kilitli. {max(ttl, 1)} saniye sonra tekrar deneyin.",
        )
    # SMS bombalamayı önlemek için hem numara hem de IP bazında sınırla.
    _rate_limit(f"ratelimit:smsreq:phone:{phone}", RATE_LIMIT_SMS_REQUEST_MAX, RATE_LIMIT_SMS_REQUEST_WINDOW)
    _rate_limit(f"ratelimit:smsreq:ip:{ip}", RATE_LIMIT_SMS_REQUEST_MAX, RATE_LIMIT_SMS_REQUEST_WINDOW)

    code = f"{secrets.randbelow(10**6):06d}"
    rdb.setex(f"otp:{phone}", OTP_TTL, code)
    rdb.delete(f"otp_fail:{phone}")  # yeni kod istendi, önceki başarısız deneme sayacını sıfırla

    print(f"[SMS-SIMULATOR] SMS Gönderildi: {code} -> +90{phone}", flush=True)
    log_manager.write_log(
        "SMSOTP", ip, simulate_mac(ip), phone,
        "SMS OTP uretildi ve gonderildi (3 dakika gecerli).",
    )
    return {
        "status": "ok",
        "message": f"Doğrulama kodu +90{phone} numarasına gönderildi (3 dk geçerli).",
        "demo_otp": code,  # Demo: gerçek SMS gateway'i yerine kod arayüzde gösterilir
        "expires_in": OTP_TTL,
    }


@app.post("/api/v1/auth/sms/verify", response_model=schemas.LoginResponse)
def sms_verify(
    body: schemas.SmsVerifyBody,
    request: Request,
    response: Response,
    db: DbSession = Depends(get_db),
):
    phone = normalize_phone(body.phone)

    if rdb.exists(f"otp_lock:{phone}"):
        ttl = rdb.ttl(f"otp_lock:{phone}")
        raise HTTPException(
            status_code=429,
            detail=f"Çok fazla hatalı deneme nedeniyle bu numara kilitli. {max(ttl, 1)} saniye sonra tekrar deneyin.",
        )

    stored = rdb.get(f"otp:{phone}")
    if stored is None:
        raise HTTPException(status_code=400, detail="Kodun süresi dolmuş. Lütfen yeni kod isteyin.")
    if stored != body.code.strip():
        fail_key = f"otp_fail:{phone}"
        fails = rdb.incr(fail_key)
        if fails == 1:
            rdb.expire(fail_key, OTP_TTL)
        if fails >= OTP_MAX_ATTEMPTS:
            rdb.delete(f"otp:{phone}")
            rdb.delete(fail_key)
            rdb.setex(f"otp_lock:{phone}", OTP_LOCKOUT_SECONDS, "1")
            ip = get_client_ip(request)
            log_manager.write_log(
                "AUTHFAIL", ip, simulate_mac(ip), phone,
                f"SMS OTP {OTP_MAX_ATTEMPTS} kez hatali girildi, numara {OTP_LOCKOUT_SECONDS}sn kilitlendi.",
            )
            raise HTTPException(
                status_code=429,
                detail=f"Çok fazla hatalı deneme. Numara {OTP_LOCKOUT_SECONDS // 60} dakika kilitlendi.",
            )
        raise HTTPException(status_code=400, detail="Doğrulama kodu hatalı.")
    rdb.delete(f"otp:{phone}")
    rdb.delete(f"otp_fail:{phone}")

    user = db.query(models.User).filter(models.User.phone == phone).first()
    if not user:
        user = models.User(phone=phone)
        db.add(user)
        db.commit()

    return _create_session(db, request, response, phone)


# ----------------------------------------------------------------------------
# Oturum durumu / çıkış / Nginx auth_request
# ----------------------------------------------------------------------------
@app.get("/api/v1/auth/check")
def auth_check(request: Request):
    """Nginx auth_request bu endpoint'i çağırır: 200 = internete çık, 401 = portala yönlen."""
    _, session = _get_session_from_request(request)
    if session is None:
        raise HTTPException(status_code=401, detail="Aktif oturum bulunamadı.")
    return {"authenticated": True}


@app.get("/api/v1/session/status")
def session_status(request: Request):
    token, session = _get_session_from_request(request)
    if session is None:
        raise HTTPException(status_code=401, detail="Aktif oturum bulunamadı.")
    ttl = rdb.ttl(f"session:{token}")
    return {
        "authenticated": True,
        "remaining_seconds": max(ttl, 0),
        "username": session["username"],
        "ip": session["ip"],
        "mac": session["mac"],
        "login_time": session["login_time"],
    }


@app.post("/api/v1/logout")
def logout(request: Request, response: Response, db: DbSession = Depends(get_db)):
    token, session = _get_session_from_request(request)
    if token:
        rdb.delete(f"session:{token}")
        record = db.query(models.SessionRecord).filter(
            models.SessionRecord.session_token == token,
            models.SessionRecord.is_active.is_(True),
        ).first()
        if record:
            record.is_active = False
            record.logout_time = utcnow()
            db.commit()
        if session:
            log_manager.write_log(
                "LOGOUT", session["ip"], session["mac"], session["username"],
                "Kullanici oturumu sonlandirdi.",
            )
            nft_manager.revoke_client(session["ip"])
    response.delete_cookie("session_token", path="/")
    return {"status": "ok", "message": "Oturum sonlandırıldı."}


# ----------------------------------------------------------------------------
# 5651 loglama — dijital imza ve doğrulama
# ----------------------------------------------------------------------------
@app.post("/api/v1/log/sign")
def sign_logs():
    try:
        meta = log_manager.sign_log_file()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"status": "ok", "message": "Log dosyası SHA-256 + RSA ile imzalandı.", "signature": meta}


@app.get("/api/v1/log/verify")
def verify_logs():
    try:
        return log_manager.verify_log_file()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/api/v1/log/rotate", dependencies=[Depends(require_admin)])
def rotate_logs():
    """Aktif log dosyasını imzalayıp arşive taşır, imza kaydını hash-zincirine ekler.
    Dosyaları taşıdığı için admin yetkisi ister (bkz. log_manager.rotate_and_seal_log)."""
    try:
        entry = log_manager.rotate_and_seal_log()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"status": "ok", "message": "Log dosyası döndürüldü ve zincire eklendi.", "entry": entry}


@app.get("/api/v1/log/chain", dependencies=[Depends(require_admin)])
def get_log_chain():
    """Tüm imza zincirini (rotasyon geçmişi) baştan sona doğrulayıp döndürür."""
    return log_manager.verify_chain()


# ----------------------------------------------------------------------------
# Site ziyaretleri — DNS sorgularından türetilen, kullanıcıya bağlanmış kayıtlar
# ----------------------------------------------------------------------------
@app.get("/api/v1/sitevisits", dependencies=[Depends(require_admin)])
def list_site_visits(
    username: str | None = None,
    domain: str | None = None,
    limit: int = 200,
    db: DbSession = Depends(get_db),
):
    """Ham ziyaret listesi (en yeni önce). username/domain ile filtrelenebilir."""
    query = db.query(models.SiteVisit).order_by(models.SiteVisit.timestamp.desc())
    if username:
        query = query.filter(models.SiteVisit.username == username)
    if domain:
        query = query.filter(models.SiteVisit.domain.ilike(f"%{domain}%"))
    rows = query.limit(min(max(limit, 1), 1000)).all()
    return [
        {
            "timestamp": r.timestamp.isoformat(),
            "username": r.username,
            "ip": r.ip_address,
            "mac": r.mac_address,
            "domain": r.domain,
            "query_type": r.query_type,
        }
        for r in rows
    ]


@app.get("/api/v1/sitevisits/summary", dependencies=[Depends(require_admin)])
def site_visits_summary(db: DbSession = Depends(get_db)):
    """Kullanıcı başına ziyaret edilen domainler: {username: [{domain, visit_count, last_visit}, ...]}."""
    rows = (
        db.query(
            models.SiteVisit.username,
            models.SiteVisit.domain,
            func.count(models.SiteVisit.id).label("visit_count"),
            func.max(models.SiteVisit.timestamp).label("last_visit"),
        )
        .group_by(models.SiteVisit.username, models.SiteVisit.domain)
        .order_by(models.SiteVisit.username, func.count(models.SiteVisit.id).desc())
        .all()
    )
    summary: dict[str, list] = {}
    for username, domain, visit_count, last_visit in rows:
        summary.setdefault(username, []).append({
            "domain": domain,
            "visit_count": visit_count,
            "last_visit": last_visit.isoformat(),
        })
    return summary


# ----------------------------------------------------------------------------
# Simüle edilmiş "internet" — Nginx auth_request'ten geçen istekler buraya düşer
# ----------------------------------------------------------------------------
@app.get("/internet{full_path:path}", response_class=HTMLResponse)
def simulated_internet(request: Request, full_path: str = ""):
    _, session = _get_session_from_request(request)
    if session is None:
        # Nginx normalde 401'i yakalayıp portala yönlendirir; bu, derinlemesine savunma.
        return RedirectResponse(url="/portal/index.html", status_code=302)

    log_manager.write_log(
        "TRAFFIC", session["ip"], session["mac"], session["username"],
        f"Kullanici internet erisimi gerceklestirdi (path=/{full_path.lstrip('/') or ''}).",
    )
    return HTMLResponse(
        f"""<!DOCTYPE html>
<html lang="tr"><head><meta charset="utf-8"><title>İnternet Simülasyonu</title>
<style>
 body{{font-family:'Segoe UI',sans-serif;background:#0f172a;color:#e2e8f0;display:flex;
 align-items:center;justify-content:center;min-height:100vh;margin:0}}
 .card{{background:#1e293b;padding:40px 48px;border-radius:16px;text-align:center;max-width:460px}}
 h1{{color:#4ade80;font-size:1.5rem}} a{{color:#60a5fa}} code{{color:#fbbf24}}
</style></head><body><div class="card">
<h1>&#127760; İnternet erişimi aktif</h1>
<p>Bu sayfa, hotspot arkasındaki "gerçek interneti" simüle eder.<br>
Kullanıcı: <code>{session['username']}</code><br>IP: <code>{session['ip']}</code> — MAC: <code>{session['mac']}</code></p>
<p>Bu ziyaret 5651 uyumlu olarak <code>dhcp_activity.log</code> dosyasına TRAFFIC kaydı olarak işlendi.</p>
<p><a href="/portal/status.html">← Oturum durumuna dön</a></p>
</div></body></html>"""
    )
