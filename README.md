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

İlk çalıştırmadan önce `.env.example`'ı `.env` olarak kopyalayıp `ADMIN_API_KEY`'i
kendi değerinizle değiştirin (`.env` `.gitignore`'da, git'e girmez):

```bash
cp .env.example .env
```

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
| POST | `/api/v1/log/sign` | Aktif logun SHA-256 özetini RSA ile imzala (dosyayı taşımaz) |
| GET | `/api/v1/log/verify` | Aktif log için imza bütünlük doğrulaması |
| POST | `/api/v1/log/rotate` | *(admin)* Aktif logu imzalayıp arşive taşır, zincire ekler |
| GET | `/api/v1/log/chain` | *(admin)* Tüm rotasyon/imza zincirini doğrulayıp döndürür |
| GET | `/api/v1/sitevisits` | *(admin)* Ham site ziyaret listesi (`?username=`, `?domain=`) |
| GET | `/api/v1/sitevisits/summary` | *(admin)* Kullanıcı → ziyaret edilen domainler özeti |
| GET | `/api/v1/health` | Sağlık kontrolü |

*(admin)* işaretli uçlar `X-Admin-Key` header'ı ister (bkz. aşağıdaki bölüm).

## Güvenlik sertleştirmeleri

**Rate limiting (Redis sabit-pencere sayaç, `main.py _rate_limit`):**
- `/api/v1/auth/tc`: IP başına 5 dakikada en fazla 10 deneme (`RATE_LIMIT_LOGIN_MAX` / `_WINDOW_SECONDS`).
- `/api/v1/auth/sms/request`: hem telefon hem IP başına 10 dakikada en fazla 3 istek
  (`RATE_LIMIT_SMS_REQUEST_MAX` / `_WINDOW_SECONDS`) — SMS bombalamayı önler.
- Limit aşılınca `429 Too Many Requests` + kalan bekleme süresi dönülür.

**OTP kilitleme (`main.py sms_verify`):**
- Bir telefon numarası için art arda `OTP_MAX_ATTEMPTS` (varsayılan 5) yanlış kod girilirse,
  mevcut kod iptal edilir ve numara `OTP_LOCKOUT_SECONDS` (varsayılan 900 sn / 15 dk) boyunca
  hem yeni kod isteyemez hem de doğrulama yapamaz. Kilitlenme AUTHFAIL olarak imzalı loga da yazılır.
- Yeni bir OTP başarıyla istendiğinde başarısız deneme sayacı sıfırlanır.

Tüm eşikler docker-compose.yml üzerinden ortam değişkeni olarak ayarlanabilir.

## Log imza zinciri ve rotasyon

`sign_log_file`/`verify_log_file` yalnızca **o an aktif olan** `dhcp_activity.log`'u
imzalar/doğrular; her yeniden imzalamada `.signed` dosyasının üzerine yazılır, yani
önceki dönemin imzası kaybolur ve dosya sınırsız büyür.

Bunu tamamlayan **rotasyon + imza zinciri** katmanı (`log_manager.rotate_and_seal_log` /
`verify_chain`):
- Aktif logu SHA-256 + RSA ile imzalar, `logs/archive/dhcp_activity-<zaman damgası>.log`
  olarak arşivler ve imza kaydını `logs/dhcp_activity.chain.jsonl`e **ekler** (append-only,
  önceki kayıtlar asla üzerine yazılmaz).
- Her kayıt bir önceki kaydın `link_hash`'ini içerir (blockchain-stili hash zinciri):
  geçmişteki bir dönem silinir/değiştirilir/sıralaması bozulursa zincir o noktadan
  itibaren doğrulamada geçersiz çıkar.
- Varsayılan olarak günde bir kez arka planda otomatik çalışır (`LOG_ROTATE_INTERVAL_SECONDS`,
  varsayılan 86400 sn); `POST /api/v1/log/rotate` ile manuel de tetiklenebilir (admin yetkisi ister).
- `GET /api/v1/log/chain` tüm zinciri uçtan uca doğrulayıp her dönem için
  `chain_intact` / `signature_valid` / `archive_file_matches` durumlarını döner.

**Bilinen sınır:** hash zinciri kendi içinde tutarlı yeniden hesaplanabilir (SHA-256 açık bir
algoritma, gizli anahtar gerektirmez); asıl bütünlük garantisi her kaydın RSA imzasından gelir
— imzalı bir dönemin içeriğini özel anahtar olmadan değiştirmek mümkün değildir. Zincirin
tamamının (ör. bir dönemin sessizce silinmesi) dışarıdan bağımsız doğrulanabilmesi için gerçek
sistemde `link_hash`'in periyodik olarak harici, güvenilir bir zaman damgası otoritesine
(TÜBİTAK/BTK onaylı TSA) bildirilmesi gerekir — bu demo kapsamının dışındadır.

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

## Gerçek Ağ Kurulumu (hostapd + dnsmasq + nftables)

Docker Compose demosu, girişi kontrol eder ama gerçek ağ trafiğini kesmez
(Nginx `auth_request` sadece reverse-proxy seviyesinde çalışır). Gerçek bir
hotspot'a dönüştürmek için `network/` dizinindeki hostapd/dnsmasq/nftables
konfigürasyonlarına ve `network/setup-ap.sh` kurulum betiğine bakın —
ayrıntılı mimari, adımlar ve bilinen kırılganlıklar `network/README.md`'de.

Özetle: backend artık login/logout/expire anlarında gerçek `nft` komutlarını
tetikleyip (`backend/nft_manager.py`) istemcinin IP'sini bir allow-set'e
ekliyor/siliyor; `network/nftables.conf`'taki forward zinciri varsayılan DROP
olduğu için oturumu olmayan bir cihaz artık hiçbir yere çıkamıyor. Bu davranış
`ENABLE_NFTABLES=true` olmadan **devre dışıdır** (Docker demo ortamındaki
varsayılan `docker-compose.yml` bunu `false` bırakır).

**2026-07-24'te gerçek donanımda uçtan uca test edildi** (USB adaptör
olmadan, laptopun tek dahili Wi-Fi kartıyla): gerçek bir telefon SSID'ye
bağlandı, captive portal + TC/OTP girişi + gerçek nftables gatekeeping +
gerçek internet erişimi doğrulandı. Bu mod için ana `docker-compose.yml`
**değiştirilmedi** — ayrı bir override dosyası olan `docker-compose.host.yml`
backend'i (ve nginx'i) `--network host` + backend'e `--cap-add=NET_ADMIN` ile
ayağa kaldırır:

```bash
sudo docker compose -f docker-compose.yml -f docker-compose.host.yml up -d --build
```

## Notlar

- MAC adresi: `DNSMASQ_LEASES_FILE` tanımlıysa gerçek dnsmasq lease dosyasından
  okunur (`backend/main.py get_real_mac`); tanımlı değilse (Docker demo
  varsayılanı) IP'den deterministik türetilir (`02:00:AA:BB:CC:DD`).
- RSA özel anahtarı (`logs/signing_key.pem`) ilk açılışta otomatik üretilir; gerçek sistemde HSM/KMS ve BTK onaylı zaman damgası kullanılır.
- Redis TTL'i dolan oturumlar arka plan görevi ile PostgreSQL'de `is_active=false` yapılır ve EXPIRE logu yazılır; log imzalama ayrıca günde bir otomatik tetiklenir.
