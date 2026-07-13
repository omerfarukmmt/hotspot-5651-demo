# 5651 Sayılı Kanun Uyumlu Hotspot (Captive Portal) ve Dijital İmzalı Loglama Sistemi

Üniversite staj/bitirme projesi demo (MVP) — FastAPI + PostgreSQL + Redis + Nginx, tamamı Docker Compose ile ayağa kalkar.

## Mimari

```
Kullanıcı ──► Nginx (:8080)
              ├── /portal/*  → Captive Portal (index.html, status.html)
              ├── /api/*     → FastAPI backend (:8000)
              └── /*         → auth_request ile oturum kontrolü
                               ├── oturum VAR  → simüle "internet" sayfası (+ TRAFFIC logu)
                               └── oturum YOK  → 302 /portal/index.html

FastAPI ──► PostgreSQL (users, sessions)  — kalıcı kayıt
        ──► Redis (session:* 7200 sn TTL, otp:* 180 sn TTL)
        ──► logs/dhcp_activity.log        — RFC 5424 (Syslog) formatı
        ──► logs/dhcp_activity.log.signed — SHA-256 + RSA-2048 dijital imza
```

## Çalıştırma

```bash
docker-compose up --build
```

Ardından tarayıcıda: **http://localhost:8080** → oturum olmadığı için otomatik olarak Captive Portal'a (`/portal/index.html`) yönlendirilirsiniz.

## Demo Senaryosu

1. **TC Kimlik ile giriş:** Ad/Soyad serbest, Doğum Yılı örn. `1995`, TC No: **`10000000146`**
   (Mock MERNİS gerçek TC algoritmasını doğrular: 11 hane + 10. ve 11. hane checksum kontrolü.)
2. **SMS ile giriş:** Herhangi bir 10 haneli numara girin; üretilen OTP hem ekranda hem backend
   loglarında (`docker logs hotspot-backend` → `[SMS-SIMULATOR] SMS Gönderildi: XXXXXX`) görünür. 3 dk TTL.
3. Girişte oturum Redis'e **7200 sn (2 saat) TTL** ile yazılır; `status.html` geri sayımı gösterir.
4. **http://localhost:8080/** artık "internet" simülasyon sayfasını açar ve her ziyaret TRAFFIC logu üretir.
5. **Log imzalama:** `curl -X POST http://localhost:8080/api/v1/log/sign`
   → `logs/dhcp_activity.log.signed` üretilir (SHA-256 özet + RSA imza + public key).
6. **Doğrulama:** `curl http://localhost:8080/api/v1/log/verify` → `"valid": true`
7. **Kurcalama kanıtı:** `logs/dhcp_activity.log` içinde tek bir karakter değiştirin,
   verify tekrar çağrıldığında `"valid": false` döner.

## API Uç Noktaları

| Metot | Yol | Açıklama |
|---|---|---|
| POST | `/api/v1/auth/tc` | Mock MERNİS ile TC kimlik doğrulama + oturum |
| POST | `/api/v1/auth/sms/request` | OTP üret (Redis, 180 sn) |
| POST | `/api/v1/auth/sms/verify` | OTP doğrula + oturum |
| GET | `/api/v1/auth/check` | Nginx auth_request kontrol ucu (200/401) |
| GET | `/api/v1/session/status` | Kalan TTL, IP, MAC, kullanıcı |
| POST | `/api/v1/logout` | Oturumu kapat (LOGOUT logu) |
| POST | `/api/v1/log/sign` | Logun SHA-256 özetini RSA ile imzala |
| GET | `/api/v1/log/verify` | İmza bütünlük doğrulaması |
| GET | `/api/v1/sitevisits` | *(admin)* Ham site ziyaret listesi (`?username=`, `?domain=`) |
| GET | `/api/v1/sitevisits/summary` | *(admin)* Kullanıcı → ziyaret edilen domainler özeti |
| GET | `/api/v1/health` | Sağlık kontrolü |

*(admin)* işaretli uçlar `X-Admin-Key` header'ı ister (bkz. aşağıdaki bölüm).

Swagger arayüzü: http://localhost:8000/docs

## Site Ziyaret Loglama (DNS tabanlı)

HTTPS trafiğinin içeriği şifreli olduğu için (ve MITM ile araya girmek gerçek
kullanıcı cihazlarında pratik değil), hangi kullanıcının hangi siteye gittiğini
görmenin gerçekçi yolu **DNS sorgularını loglamaktır** — 5651 kapsamındaki
ticari çözümlerin çoğu da bu yaklaşımı kullanır.

**Nasıl çalışır:**
1. Gerçek ağ kurulumunda (bkz. yukarıdaki mimari) tüm istemcilerin DNS'i
   `dnsmasq` üzerinden çözülür. `dnsmasq.conf` içine şunlar eklenir:
   ```
   log-queries
   log-facility=/tam/yol/hotspot-5651-demo/logs/dnsmasq_query.log
   ```
   (Bu dosya, backend konteynerine zaten `./logs:/app/logs` ile bağlı olan
   dizinin içinde olmalı ki backend okuyabilsin.)
2. Backend, bu log dosyasını arka planda (`_dns_log_tailer`, `main.py`) sürekli
   izler; her `query[TİP] domain from IP` satırını o anda o IP'ye sahip
   **aktif oturuma** (dolayısıyla kullanıcıya) bağlar.
3. Her eşleşme hem imzalı 5651 loguna (`SITEVISIT` mesaj tipi) hem de
   sorgulanabilir `site_visits` tablosuna yazılır.
4. **Yönetici paneli:** `http://localhost:8080/portal/admin.html` —
   kullanıcı bazında ziyaret edilen domainler ve ham liste burada canlı olarak
   görülür (5 sn'de bir otomatik yenilenebilir; staj komisyonu demosu için
   uygundur).

**Önemli notlar:**
- Panel `X-Admin-Key` ile korunur; anahtar `docker-compose.yml` içindeki
  `ADMIN_API_KEY` değişkeninden gelir (varsayılan `changeme-admin-key`,
  **gerçek/canlı demo öncesi mutlaka değiştirin**).
- `/portal/` dizini captive-portal auth kontrolünden muaf olduğu için
  `admin.html` sayfası herkes tarafından *açılabilir*, ancak anahtar
  olmadan veri döndürmez. Gerçek üretim ortamında bu sayfayı ayrı bir
  yönetici ağına/VLAN'a taşımak veya nginx üzerinde ek erişim kısıtı
  eklemek gerekir (KVKK: gezinme geçmişi kişisel veridir).
- Docker demo ortamında henüz gerçek bir `dnsmasq` çalışmadığı için bu
  akışı test etmek üzere `logs/dnsmasq_query.log` dosyasına elle
  `query[A] example.com from 192.168.4.50` formatında bir satır eklemeniz
  yeterlidir; tailer bunu birkaç saniye içinde işler.

## Notlar

- MAC adresi demo ortamında IP'den deterministik türetilir (`02:00:AA:BB:CC:DD`); gerçek kurulumda DHCP/ARP tablosundan okunur.
- RSA özel anahtarı (`logs/signing_key.pem`) ilk açılışta otomatik üretilir; gerçek sistemde HSM/KMS ve BTK onaylı zaman damgası kullanılır.
- Redis TTL'i dolan oturumlar arka plan görevi ile PostgreSQL'de `is_active=false` yapılır ve EXPIRE logu yazılır; log imzalama ayrıca günde bir otomatik tetiklenir.
