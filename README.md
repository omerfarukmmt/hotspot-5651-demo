# 5651 Sayılı Kanun Uyumlu Hotspot (Captive Portal) ve Dijital İmzalı Loglama Sistemi

[![tests](https://github.com/omerfarukmmt/hotspot-5651-demo/actions/workflows/tests.yml/badge.svg)](https://github.com/omerfarukmmt/hotspot-5651-demo/actions/workflows/tests.yml)
![Python](https://img.shields.io/badge/python-3.12-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688)
![Docker Compose](https://img.shields.io/badge/docker-compose-2496ED)

Erzincan Binali Yıldırım Üniversitesi Bilgi İşlem Daire Başkanlığı'nda yapılan yaz stajı
(Temmuz 2026) kapsamında geliştirilen, **5651 sayılı Kanun**'un toplu kullanım sağlayıcılara
getirdiği kimlik doğrulama ve log saklama yükümlülüklerini gösteren bir hotspot demosu.

Kullanıcı Wi-Fi'a bağlanır, captive portal'da **TC Kimlik No** veya **SMS OTP** ile giriş yapar,
ancak ondan sonra internete çıkabilir. Her giriş, çıkış ve ziyaret edilen alan adı
**RFC 5424** formatında loglanır; log dosyaları **SHA-256 + RSA-2048** ile imzalanıp
**hash zinciriyle** arşivlenir, böylece sonradan yapılan en küçük değişiklik bile tespit edilir.

> İki çalışma modu var: herhangi bir bilgisayarda çalışan **Docker demo modu** ve gerçek bir
> Linux laptopta `hostapd` + `dnsmasq` + `nftables` ile **gerçek internet paylaşan hotspot modu**
> (2026-07-24'te gerçek bir telefonla uçtan uca test edildi).

## İçindekiler

- [Özellikler](#özellikler)
- [Mimari](#mimari)
- [Proje yapısı](#proje-yapısı)
- [Hızlı başlangıç (Docker demo)](#hızlı-başlangıç-docker-demo)
- [Demo senaryosu](#demo-senaryosu)
- [API uç noktaları](#api-uç-noktaları)
- [Güvenlik](#güvenlik)
- [Log imzalama, rotasyon ve hash zinciri](#log-imzalama-rotasyon-ve-hash-zinciri)
- [Site ziyaret loglama (DNS tabanlı)](#site-ziyaret-loglama-dns-tabanlı)
- [Gerçek hotspot kurulumu](#gerçek-hotspot-kurulumu-hostapd--dnsmasq--nftables)
- [Testler](#testler)
- [Yapılandırma](#yapılandırma)
- [Bilinen sınırlar](#bilinen-sınırlar)

## Özellikler

- **Kimlik doğrulama:** Mock MERNİS (gerçek TC Kimlik No algoritması) ve SMS OTP (simülasyon, 3 dk geçerli)
- **Oturum yönetimi:** Redis'te 2 saatlik TTL, PostgreSQL'de kalıcı kayıt; süresi dolan oturumlar otomatik kapatılır
- **5651 loglama:** RFC 5424 (Syslog) formatı — LOGIN, LOGOUT, EXPIRE, KICK, AUTHFAIL, SMSOTP, SITEVISIT, TRAFFIC
- **Dijital imza:** SHA-256 özet + RSA-2048 (PKCS#1 v1.5) imza, kurcalama tespiti
- **Log rotasyonu + hash zinciri:** dönemsel arşivleme, append-only imza zinciri
- **Site ziyaret takibi:** dnsmasq DNS sorguları aktif oturuma (kullanıcıya) bağlanır
- **Yönetici paneli:** aktif oturumlar, kullanıcıyı ağdan düşürme (kick), kullanıcı bazlı ziyaret özeti
- **Gerçek gatekeeping:** nftables varsayılan DROP; giriş yapan istemcinin IP'si dinamik allow-set'e eklenir
- **Sertleştirme:** rate limiting, OTP kilitleme, yönetici anahtarı, backend'in sadece nginx arkasında erişilebilir olması

## Mimari

```
İstemci ──► Nginx (:8080 demo / :80 hotspot)
            ├── /portal/*  → Captive Portal (index.html, status.html, admin.html)
            ├── /api/*     → FastAPI backend (yalnızca 127.0.0.1:8000)
            └── /*         → auth_request ile oturum kontrolü
                             ├── oturum VAR  → simüle "internet" sayfası (+ TRAFFIC logu)
                             └── oturum YOK  → 302 /portal/index.html

FastAPI ──► PostgreSQL   users, sessions, site_visits
        ──► Redis        session:* (7200 sn), otp:* (180 sn), rate limit sayaçları
        ──► logs/        dhcp_activity.log (RFC 5424), .signed, chain.jsonl, archive/
        ──► nftables     allowed_clients set'i (sadece hotspot modunda)
        ◄── dnsmasq      DNS sorgu logu → site ziyaretleri
```

Hotspot modunda ağ tarafı (`WAN_IF` = telefon hotspot'una bağlı Wi-Fi, `LAN_IF` = kendi AP'miz)
için ayrıntılı şema [`network/README.md`](network/README.md)'de.

## Proje yapısı

```
backend/
  main.py              FastAPI uygulaması: kimlik doğrulama, oturum, admin, log uçları, arka plan görevleri
  log_manager.py       RFC 5424 loglama, RSA imzalama/doğrulama, rotasyon + hash zinciri
  nft_manager.py       nftables allow-set'ine IP ekleme/silme (ENABLE_NFTABLES=false iken no-op)
  dns_log_watcher.py   dnsmasq sorgu logunu tail -f gibi izler ve ayrıştırır
  models.py, schemas.py, database.py
  tests/               pytest testleri (Docker gerektirmez)
frontend/              index.html (portal), status.html (oturum), admin.html (yönetici paneli)
nginx/                 nginx.conf (demo), nginx.host.conf (hotspot modu)
network/               hostapd/dnsmasq/nftables yapılandırmaları + setup-ap.sh
docker-compose.yml       Demo modu
docker-compose.host.yml  Hotspot modu override'ı (host network + NET_ADMIN)
PROGRESS.md              Geliştirme günlüğü: alınan kararlar ve nedenleri
staj-defteri-kanitlari.md  Gerçek donanımda alınan komut çıktıları (staj defteri için)
```

## Hızlı başlangıç (Docker demo)

Gereksinim: Docker + Docker Compose. Önce yönetici anahtarını ayarlayın (`.env` git'e girmez):

```bash
cp .env.example .env
```

`.env` içindeki `ADMIN_API_KEY` değerini rastgele bir değerle değiştirin, ardından:

```bash
docker compose up --build
```

| Adres | Açıklama |
|---|---|
| http://localhost:8080 | Oturum yoksa otomatik olarak captive portal'a yönlendirir |
| http://localhost:8080/portal/admin.html | Yönetici paneli (`ADMIN_API_KEY` ister) |
| http://localhost:8000/docs | Swagger arayüzü (yalnızca bu makineden erişilebilir) |

## Demo senaryosu

1. **TC Kimlik ile giriş:** Ad/Soyad serbest, Doğum Yılı örn. `1995`, TC No: **`10000000146`**
   (Mock MERNİS gerçek algoritmayı doğrular: 11 hane, ilk hane ≠ 0, 10. ve 11. hane checksum).
2. **SMS ile giriş:** Herhangi bir 10 haneli numara girin; üretilen OTP hem ekranda hem backend
   logunda (`docker logs hotspot-backend` → `[SMS-SIMULATOR] SMS Gönderildi: XXXXXX`) görünür.
3. Oturum Redis'e **7200 sn (2 saat) TTL** ile yazılır; `status.html` geri sayımı gösterir.
4. **http://localhost:8080/** artık "internet" simülasyon sayfasını açar; her ziyaret TRAFFIC logu üretir.
5. **Log imzalama** (yönetici yetkisi ister):
   ```bash
   curl -X POST -H "X-Admin-Key: $ADMIN_API_KEY" http://localhost:8080/api/v1/log/sign
   ```
6. **Doğrulama:**
   ```bash
   curl http://localhost:8080/api/v1/log/verify
   ```
   → `"valid": true`
7. **Kurcalama kanıtı:** `logs/dhcp_activity.log` içinde tek bir karakter değiştirin; verify
   tekrar çağrıldığında `"valid": false` döner.

## API uç noktaları

| Metot | Yol | Yetki | Açıklama |
|---|---|---|---|
| POST | `/api/v1/auth/tc` | — | Mock MERNİS ile TC kimlik doğrulama + oturum |
| POST | `/api/v1/auth/sms/request` | — | OTP üret (Redis, 180 sn) |
| POST | `/api/v1/auth/sms/verify` | — | OTP doğrula + oturum |
| GET | `/api/v1/auth/check` | — | Nginx `auth_request` kontrol ucu (200/401) |
| GET | `/api/v1/session/status` | oturum | Kalan süre, IP, MAC, kullanıcı |
| POST | `/api/v1/logout` | oturum | Oturumu kapat (LOGOUT logu) |
| GET | `/api/v1/log/verify` | — | Aktif logun imza bütünlüğünü doğrula |
| POST | `/api/v1/log/sign` | admin | Aktif logun SHA-256 özetini RSA ile imzala |
| POST | `/api/v1/log/rotate` | admin | Aktif logu imzalayıp arşive taşı, zincire ekle |
| GET | `/api/v1/log/chain` | admin | Tüm rotasyon/imza zincirini doğrula |
| GET | `/api/v1/admin/sessions` | admin | Aktif oturumlar |
| POST | `/api/v1/admin/sessions/{id}/kick` | admin | Kullanıcıyı ağdan düşür (nftables'tan anında çıkarır) |
| GET | `/api/v1/sitevisits` | admin | Ham ziyaret listesi (`?username=`, `?domain=`, `?limit=`) |
| GET | `/api/v1/sitevisits/summary` | admin | Kullanıcı → ziyaret edilen alan adları özeti |
| GET | `/api/v1/health` | — | Sağlık kontrolü |

*admin* uçları `X-Admin-Key` header'ı ister.

## Güvenlik

**Rate limiting** (Redis sabit pencereli sayaç, `main.py _rate_limit`):
- `/auth/tc`: IP başına 5 dakikada en fazla 10 deneme.
- `/auth/sms/request`: hem telefon hem IP başına 10 dakikada en fazla 3 istek (SMS bombalamaya karşı).
- Limit aşılınca `429 Too Many Requests` + kalan bekleme süresi.

**OTP kilitleme:** Bir numara için art arda 5 yanlış kod girilirse kod iptal edilir ve numara
15 dakika boyunca hem kod isteyemez hem doğrulama yapamaz. Kilitlenme AUTHFAIL olarak loglanır.

**Backend'e doğrudan erişim kapalı:** Backend istemci IP'sini nginx'in gönderdiği `X-Real-IP`
header'ından okur. Bu header'a güvenilebilmesi için backend portu yalnızca `127.0.0.1`'e açılır
(demo modunda port eşlemesi, hotspot modunda uvicorn'un loopback'e bağlanması). Aksi halde bir
istemci header'ı kendisi gönderip rate limit'i atlatabilir veya başka bir IP adına erişim açtırabilirdi.

**İmza doğrulama sunucunun anahtarıyla yapılır:** `.signed` dosyası ve zincir kayıtları public key'i
bilgi amaçlı taşır, ancak doğrulamada her zaman sunucunun kendi anahtarı kullanılır. Böylece logu
değiştirip kendi anahtarıyla yeniden imzalayan biri doğrulamayı geçemez. İmzalama ucu da bu yüzden
yönetici yetkisi ister.

**Aynı IP'de birden fazla oturum:** Bir cihaz cookie'sini kaybedip yeniden giriş yaparsa, eski
oturumun kapanması yeni oturumun internet erişimini kesmez; IP ancak o IP'ye ait aktif oturum
kalmadığında allow-set'ten çıkarılır.

Tüm eşikler `docker-compose.yml` üzerinden ortam değişkeniyle ayarlanabilir (bkz. [Yapılandırma](#yapılandırma)).

## Log imzalama, rotasyon ve hash zinciri

`/log/sign` ve `/log/verify` yalnızca **o an aktif olan** `dhcp_activity.log`'u imzalar/doğrular;
her imzalamada `.signed` dosyasının üzerine yazılır. Uzun süreli saklama için bunun üstüne
**rotasyon + imza zinciri** katmanı var (`log_manager.rotate_and_seal_log` / `verify_chain`):

- Aktif log imzalanır, `logs/archive/dhcp_activity-<zaman damgası>.log` olarak arşivlenir ve imza
  kaydı `logs/dhcp_activity.chain.jsonl` dosyasına **eklenir** (append-only).
- Her kayıt bir önceki kaydın `link_hash`'ini içerir: geçmişteki bir dönem silinir, değiştirilir
  veya sırası bozulursa zincir o noktadan itibaren geçersiz çıkar.
- Arşiv dosyasının diskten **kaybolması** da ihlal sayılır (5651 logların saklanmasını zorunlu kılar).
- Varsayılan olarak günde bir kez otomatik çalışır (`LOG_ROTATE_INTERVAL_SECONDS`);
  `POST /api/v1/log/rotate` ile manuel de tetiklenebilir.
- `GET /api/v1/log/chain` her dönem için `chain_intact`, `signature_valid`, `archive_file_present`,
  `archive_file_matches` durumlarını döner.

## Site ziyaret loglama (DNS tabanlı)

HTTPS içeriği şifreli olduğundan, hangi kullanıcının hangi siteye gittiğini görmenin gerçekçi yolu
**DNS sorgularını loglamaktır**; 5651 kapsamındaki ticari çözümlerin çoğu da bunu yapar.

1. Tüm istemcilerin DNS'i `dnsmasq` üzerinden çözülür (`log-queries` açık, log dosyası `logs/` altında).
2. Backend bu dosyayı arka planda izler (`_dns_log_tailer`), her `query[TİP] alan-adı from IP`
   satırını o IP'nin **aktif oturumuna** bağlar. Eşleşmeyen IP'ler `(kimliksiz)` olarak işaretlenir.
3. Her eşleşme hem imzalı loga (SITEVISIT) hem `site_visits` tablosuna yazılır.
4. Sonuçlar yönetici panelinde (`/portal/admin.html`) canlı izlenebilir.

Docker demosunda gerçek dnsmasq olmadığı için `logs/dnsmasq_query.log` dosyasına elle
`query[A] example.com from 192.168.4.50` biçiminde bir satır eklemek yeterlidir.

## Gerçek hotspot kurulumu (hostapd + dnsmasq + nftables)

Docker demosu girişi kontrol eder ama gerçek ağ trafiğini kesmez. Gerçek hotspot modunda:

- `hostapd` kendi SSID'ini yayınlar, `dnsmasq` DHCP + DNS sağlar.
- `nftables` forward zinciri varsayılan **DROP**; backend giriş/çıkış/süre dolumu anlarında
  istemci IP'sini `allowed_clients` set'ine ekler/siler (`backend/nft_manager.py`).
- Harici USB adaptör gerekmez: laptopun tek dahili Wi-Fi kartı (Intel AX201) concurrent AP+STA ile
  hem WAN hem AP olarak kullanıldı.

```bash
sudo WAN_IF=wlp0s20f3 LAN_IF=ap0 ./network/setup-ap.sh
```

```bash
sudo docker compose -f docker-compose.yml -f docker-compose.host.yml up -d --build
```

Adım adım kurulum, NetworkManager ayarı, kanal eşleştirme ve bilinen kırılganlıklar için
[`network/README.md`](network/README.md); kararların gerekçeleri için [`PROGRESS.md`](PROGRESS.md).

## Testler

Testler Docker, PostgreSQL veya Redis gerektirmez; her push'ta GitHub Actions'ta da çalışır.

```bash
cd backend
```

```bash
pip install -r requirements.txt -r requirements-dev.txt
```

```bash
python -m pytest -q
```

Kapsanan senaryolar: TC Kimlik algoritması, RFC 5424 satır formatı, imzala/doğrula, tek karakterlik
kurcalama, **sahte anahtarla yeniden imzalama**, arşiv dosyası değişikliği/silinmesi, zincirden kayıt silinmesi.

## Yapılandırma

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `ADMIN_API_KEY` | — (zorunlu, `.env`) | Yönetici uçları ve paneli için anahtar |
| `SESSION_TTL_SECONDS` | `7200` | Oturum süresi |
| `OTP_TTL_SECONDS` | `180` | OTP geçerlilik süresi |
| `RATE_LIMIT_LOGIN_MAX` / `_WINDOW_SECONDS` | `10` / `300` | TC giriş denemesi sınırı |
| `RATE_LIMIT_SMS_REQUEST_MAX` / `_WINDOW_SECONDS` | `3` / `600` | SMS isteği sınırı |
| `OTP_MAX_ATTEMPTS` / `OTP_LOCKOUT_SECONDS` | `5` / `900` | OTP kilitleme |
| `LOG_ROTATE_INTERVAL_SECONDS` | `86400` | Otomatik log rotasyonu aralığı |
| `ENABLE_NFTABLES` | `false` | Gerçek nftables gatekeeping (hotspot modunda `true`) |
| `DNSMASQ_LEASES_FILE` | boş | Gerçek MAC adresi için dnsmasq lease dosyası |
| `DNSMASQ_LOG_FILE` | `/app/logs/dnsmasq_query.log` | DNS sorgu logu |

## Bilinen sınırlar

Bu bir staj demosudur; üretim ortamı için şunlar gerekir:

- **MERNİS ve SMS simülasyondur.** Gerçek kurulumda KPSPublic servisi ve bir SMS sağlayıcısı kullanılır;
  `demo_otp` alanı yanıttan kaldırılmalıdır.
- **İmza anahtarı diskte (`logs/signing_key.pem`) durur.** Gerçek sistemde HSM/KMS ve BTK/TÜBİTAK
  onaylı zaman damgası (TSA) kullanılır. Hash zinciri tek başına anahtarsız yeniden hesaplanabilir;
  zincirin bütününün bağımsız doğrulanması için `link_hash`'in düzenli olarak harici bir TSA'ya
  bildirilmesi gerekir.
- **KVKK:** TC Kimlik No ve gezinme geçmişi kişisel veridir. Yönetici paneli ayrı bir yönetim
  ağına/VLAN'a taşınmalı, veritabanındaki kimlik bilgileri şifrelenmeli ve saklama süresi politikası uygulanmalıdır.
- **Gatekeeping IP bazlıdır.** DHCP lease'i başka bir cihaza geçerse eski izin teorik olarak miras kalabilir;
  lease süresinin oturum süresiyle hizalanması önerilir.
- PostgreSQL parolası `docker-compose.yml` içinde sabittir; gerçek kurulumda `.env`'e taşınmalıdır.
