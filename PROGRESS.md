# Proje İlerleme Notu

Bu dosya, projeye farklı bilgisayarlardan/oturumlardan devam edebilmek için
tutulan bir günlüktür. Mimari ve API detayları için `README.md`'ye bakın;
burada **neden bu kararların alındığı** ve **sırada ne olduğu** var.

## Proje özeti

Üniversite staj/bitirme projesi: 5651 Sayılı Kanun kapsamında, kimlik
doğrulamalı (TC Kimlik / SMS OTP) bir hotspot captive portal + dijital
imzalı (RSA-2048 + SHA-256) loglama sistemi. Şu an FastAPI + PostgreSQL +
Redis + Nginx, Docker Compose ile ayakta (bkz. `README.md`).

## Şu ana kadar yapılanlar

### 1. Demo/MVP (mevcut haliyle depoda)
- Mock MERNİS ile TC kimlik doğrulama, SMS OTP simülasyonu.
- Redis'te 2 saatlik oturum (TTL), PostgreSQL'de kalıcı `users`/`sessions`.
- RFC 5424 formatlı log + RSA-2048 dijital imza + bütünlük doğrulama
  (`logs/dhcp_activity.log`, `.signed`).
- Nginx `auth_request` ile "internet" simülasyonu (gerçek WAN çıkışı yok).

### 2. Gerçek hotspot'a dönüştürme planı (config + backend entegrasyonu KODLANDI, donanımda TEST EDİLMEDİ)
Amaç: sahte "internet simülasyonu"nu gerçek, internete çıkan bir ağa çevirmek.

Kararlaştırılan mimari:
- **WAN:** Laptop'un dahili Wi-Fi'ı → telefon mobil veri hotspot'una bağlanır
  (taşınabilir, komisyon/okul ağına bağımlı değil).
- **LAN/AP:** USB Wi-Fi adaptör (AP/master mode destekleyen bir chipset ile)
  + `hostapd` → kendi SSID'ini yayınlar.
- `dnsmasq` → DHCP + DNS.
- `nftables`/`iptables` → varsayılan DROP, login olan MAC/IP dinamik set'e
  eklenip ACCEPT olur (gerçek gatekeeping; şu anki Redis-only kontrol sadece
  Nginx reverse-proxy seviyesinde, gerçek trafiği kesmiyor).
- Elimizdeki eski/zayıf router bu plana **dahil edilmedi** (sinyal sorunu
  demo riski yaratır).

**KODLANDI (bu oturumda), henüz gerçek donanımda TEST EDİLMEDİ:**
- [x] hostapd/dnsmasq/nftables konfigürasyonlarının yazılması
      (`network/hostapd.conf.example`, `network/dnsmasq.conf.example`,
      `network/nftables.conf`, kurulum betiği `network/setup-ap.sh`,
      ayrıntılı mimari `network/README.md`).
- [x] FastAPI login/logout/expire akışına gerçek `nft add/delete element`
      çağrılarının eklenmesi: `backend/nft_manager.py` (`allow_client`/
      `revoke_client`), `backend/main.py` içinde `_create_session`, `logout`,
      `_expired_session_reaper`'a bağlandı. `ENABLE_NFTABLES=true` olmadan
      no-op (Docker demo ortamında `nft` binary'si yok, varsayılan `false`).
- [x] Gerçek MAC adresinin dnsmasq lease dosyasından okunması:
      `backend/main.py get_real_mac()`, `DNSMASQ_LEASES_FILE` env değişkeni
      tanımlı değilse (Docker demo varsayılanı) eskisi gibi `simulate_mac()`'e
      düşer — demo davranışı bozulmadı.
- [x] iOS/Android/Windows captive portal auto-detection domain'lerinin
      (`captive.apple.com`, `connectivitycheck.gstatic.com`,
      `msftconnecttest.com` vb.) `network/dnsmasq.conf.example`'da AP IP'sine
      yönlendirilmesi.

**Henüz yapılmadı:**
- [ ] USB Wi-Fi adaptörün temin edilip AP modunun gerçek donanımda test
      edilmesi (donanım bağımlılığı — bu, yazılım tarafından bağımsız).
- [ ] `network/setup-ap.sh` + yukarıdaki config'lerin gerçek bir Linux kutusunda
      (Raspberry Pi/eski laptop) uçtan uca prova edilmesi — şu ana kadar sadece
      dosya olarak yazıldı, hiç çalıştırılmadı/test edilmedi.
- [ ] Backend konteynerinin gerçek kurulumda `nft` komutunu çalıştırabilmesi
      için `--network host` + `--cap-add=NET_ADMIN` ile ayağa kaldırılması
      (ya da backend'i konteynersiz, host üzerinde çalıştırma) — henüz
      `docker-compose.yml`'e bu mod eklenmedi, sadece `network/README.md`'de
      not olarak var.

### 3. Kullanıcı bazlı site ziyaret loglama (KODLANDI ve test edildi)
- `backend/dns_log_watcher.py`: dnsmasq sorgu logunu (`query[TİP] domain from IP`)
  `tail -f` gibi izler.
- `backend/models.py`: yeni `SiteVisit` tablosu.
- `backend/main.py`: `_dns_log_tailer()` arka plan görevi, her DNS sorgusunu
  o anki aktif oturuma (kullanıcıya) bağlar; imzalı 5651 loguna (`SITEVISIT`)
  ve `site_visits` tablosuna yazar. Yeni uçlar: `GET /api/v1/sitevisits`,
  `GET /api/v1/sitevisits/summary` — ikisi de `X-Admin-Key` header'ı ister.
- `frontend/admin.html`: `http://localhost:8080/portal/admin.html` — kullanıcı
  bazında ziyaret edilen domainler + ham liste, canlı demo için otomatik
  yenileme seçeneği.
- **Test edildi (docker compose ile):** TC ile giriş yapıldı, sahte dnsmasq
  log satırları `logs/dnsmasq_query.log`'a eklendi, doğru kullanıcıya
  eşlendiği, eşleşmeyen IP'nin `"(kimliksiz)"` olarak işaretlendiği, imza
  sign/verify akışının bozulmadığı doğrulandı.

### 4. Rate limiting + OTP kilitleme (KODLANDI, Docker'da test edildi)
- `backend/main.py`: `_rate_limit()` — Redis `INCR`+`EXPIRE` ile sabit pencereli sayaç.
  `/api/v1/auth/tc` (IP başına 10/5dk) ve `/api/v1/auth/sms/request` (telefon VE IP
  başına 3/10dk) uçlarına uygulandı; aşılınca `429` + kalan bekleme süresi döner.
- `sms_verify`: `otp_fail:{phone}` sayacı ile başarısız kod denemesi izleniyor;
  `OTP_MAX_ATTEMPTS` (varsayılan 5) aşılınca kod iptal edilip numara
  `OTP_LOCKOUT_SECONDS` (varsayılan 900sn) `otp_lock:{phone}` ile kilitleniyor,
  hem `sms/request` hem `sms/verify` bu kilidi kontrol ediyor; AUTHFAIL olarak
  imzalı loga da yazılıyor. Yeni kod başarıyla istenince sayaç sıfırlanıyor.
- Tüm eşikler docker-compose.yml'de env değişkeni olarak dışarı açık.
- **Test edildi:** `/auth/tc`'ye eşiği aşacak kadar istek atıldığında `429` döndüğü,
  `sms/verify`'a 5 kez yanlış kod girilince numaranın kilitlendiği ve kilitliyken
  hem `sms/request` hem `sms/verify`'ın reddettiği doğrulandı.

### 5. Log imza zinciri + rotasyon (KODLANDI, Docker'da test edildi)
- `backend/log_manager.py`: `rotate_and_seal_log()` — aktif `dhcp_activity.log`'u
  imzalayıp `logs/archive/dhcp_activity-<timestamp>.log` olarak arşivler, imza
  kaydını `logs/dhcp_activity.chain.jsonl`e append-only ekler. Her kayıt bir
  önceki kaydın `link_hash`'ini içerir (hash zinciri) — geçmiş bir dönem
  silinir/değiştirilirse zincir o noktadan sonrası için geçersiz çıkar.
  `verify_chain()` tüm zinciri baştan sona doğrular (chain_intact +
  signature_valid + archive_file_matches, her kayıt için ayrı ayrı).
- Eskisi (`sign_log_file`/`verify_log_file`, sadece o anki aktif dosyayı
  imzalar/doğrular, `.signed` her seferinde üzerine yazılır) **korundu**,
  ad-hoc/canlı-demo amaçlı hâlâ kullanılabilir; rotasyon bunun üstüne ek katman.
- Arka plan görevi `_daily_log_signer` → `_daily_log_rotator` olarak değiştirildi,
  `LOG_ROTATE_INTERVAL_SECONDS` (varsayılan 86400sn) periyoduyla otomatik rotasyon
  yapıyor. Manuel tetik: `POST /api/v1/log/rotate` (admin yetkisi ister, dosya
  taşıdığı için). Zincir görüntüleme: `GET /api/v1/log/chain` (admin).
- Bilinen sınır (README'de not edildi): hash zinciri tek başına, özel anahtara
  ihtiyaç duymadan yeniden hesaplanabilir bir yapı; asıl bütünlük garantisi her
  kaydın RSA imzasından geliyor. Zincirin tamamının bağımsız doğrulanması için
  gerçek sistemde harici bir zaman damgası otoritesine (TSA) periyodik bildirim
  gerekir — bu demo kapsamının dışında bırakıldı.
- **Test edildi:** birkaç log satırı yazıldıktan sonra `/api/v1/log/rotate` çağrıldı,
  `archive/`e dosyanın taşındığı, aktif log dosyasının sıfırlandığı (yeni yazımla
  otomatik yeniden oluştuğu), `/api/v1/log/chain`'in `valid: true` döndüğü,
  arşivlenen dosyada tek karakter değiştirilince `archive_file_matches: false`
  ile bozulmanın doğru tespit edildiği doğrulandı.

## Laptop üzerinde harici Wi-Fi adaptörsüz AP denemesi (2026-07-22, DEVAM EDİYOR)

Amaç: `network/` dizinindeki gerçek hotspot planı (bkz. yukarıdaki 2. bölüm)
şu ana kadar "laptop dahili Wi-Fi = WAN (telefon hotspot'una bağlı)" +
"USB Wi-Fi adaptör = LAN/AP" ikilisini varsayıyordu. Kullanıcı harici adaptör
almadan, laptopun **tek** dahili Wi-Fi kartıyla hem WAN hem AP'yi aynı anda
yapmak istiyor. Bu bölüm, bu alternatifin değerlendirilmesinin günlüğü.

**Elenen seçenekler:**
- **WSL2 içinde hostapd:** Laptopun Wi-Fi kartı **PCI** (Aygıt Yöneticisi'nde
  "Bus reporting information: PCI" olarak doğrulandı). WSL2'nin PCI cihazlara
  gerçek passthrough desteği yok; tam Hyper-V VM + Discrete Device Assignment
  (DDA) gerekir ki bu da tüketici Wi-Fi çipset/sürücülerinde genelde
  çalışmıyor ve kartı Windows'tan tamamen koparıyor. **Bu yol kapalı.**
- **Windows Mobil Etkin Nokta (ICS):** Teknik olarak mümkün (Windows sürücü
  katmanında STA+AP eşzamanlılığını destekliyor) ama `hostapd`/`dnsmasq`/
  `nftables` zincirinin tamamen Windows eşdeğerlerine (`nft_manager.py`
  yerine WFP/Windows Firewall, dnsmasq lease yerine ICS DHCP) yeniden
  yazılmasını gerektirir. **Şimdilik seçilmedi**, kullanıcı bunun yerine
  Ubuntu'yu seçti.

**Seçilen yol:** Laptopta **Ubuntu zaten kurulu** (dual-boot/ayrı bir işletim
sistemi olarak) — VM yok, kart doğrudan Linux'a görünür. Mevcut
`network/setup-ap.sh` script'i `WAN_IF`/`LAN_IF`'i zaten env değişkeni olarak
parametrik aldığı için (aynı script, iki farklı fiziksel adaptör yerine aynı
fiziksel kartın iki *sanal* arayüzüyle de çalıştırılabilir) kod tarafında
değişiklik gerekmiyor — tek açık soru, kartın/sürücünün tek radyoda
**concurrent AP + managed (STA) modunu** destekleyip desteklemediği.

**Sıradaki adım (henüz yapılmadı):** Laptopta Ubuntu'dan çalıştırılacak:
```bash
iw list | grep -A 15 "valid interface combinations"
```
Bakılacak şey:
- Çıktıda `managed` ile `AP` rolünü birlikte içeren bir kombinasyon var mı
  (yoksa bu kart concurrent AP+STA desteklemiyor demektir — plan burada
  tıkanır, USB adaptör veya Windows ICS'e geri dönülür).
- Varsa, `#channels <= 1` mi (AP, WAN'ın bağlı olduğu kanalla **aynı** kanalda
  olmak zorunda — `hostapd.conf.example`'daki `channel=` telefonun hotspot
  kanalıyla eşleştirilmeli) yoksa `<= 2` mi (farklı kanal da olur, daha esnek).

**Kombinasyon destekleniyorsa sıradaki adımlar:**
1. Sanal AP arayüzü oluştur: `sudo iw dev wlan0 interface add wlan1 type __ap`
   (gerçek isimler `iw dev`/`iw phy` ile teyit edilmeli).
2. NetworkManager'ın yeni sanal arayüzü (`wlan1`) yönetime almasını engelle
   (`nmcli device set wlan1 managed no` veya `NetworkManager.conf`
   `unmanaged-devices`) — aksi halde hostapd ile çakışır.
3. `hostapd.conf.example` içindeki `channel=6` değerini WAN'ın bağlı olduğu
   gerçek kanalla eşleştir (tek kanal kısıtı varsa).
4. `sudo WAN_IF=wlan0 LAN_IF=wlan1 ./network/setup-ap.sh` (script değişmeden
   kullanılabilir, bkz. yukarıda).

**Kombinasyon desteklenmiyorsa:** ya `network/README.md`'deki orijinal
USB adaptör planına dön, ya da Windows Mobil Etkin Nokta (ICS) yolunu
(yukarıda elenen ama teknik olarak mümkün olan seçenek) yeniden değerlendir.

## Demo günü öncesi yapılacaklar (checklist)

- [x] `docker-compose.yml` içindeki `ADMIN_API_KEY` değerini değiştir
      (varsayılan `changeme-admin-key` demoya açık bırakılmamalı) — 2026-07-20'de
      rastgele 64 karakterlik hex anahtarla değiştirildi. Anahtar git'e
      girmesin diye `docker-compose.yml`'de `${ADMIN_API_KEY:?...}` referansına
      çevrildi, gerçek değer `.env`'e (gitignored) taşındı; `.env.example`
      placeholder olarak repoya eklendi.
- [x] `logs/dnsmasq_query.log` içindeki test verisini temizle (youtube/
      instagram gibi sahte satırlar test amaçlıydı) — 2026-07-20'de dosya
      sıfırlandı (tailer truncate'i baştan okuyarak karşılıyor, bkz.
      `dns_log_watcher.py follow()`).
- [ ] Yukarıdaki "gerçek hotspot" checklist'i tamamlanmadan bu sistem sadece
      Docker demo'sunda çalışır, gerçek cihazlarla internet paylaşmaz.
- [ ] hostapd/nftables kurulumunu demo gününden 1-2 gün önce prova et.

## Nasıl çalıştırılır

```bash
cd hotspot-5651-demo
docker compose up --build
```
- Portal: http://localhost:8080
- Admin panel: http://localhost:8080/portal/admin.html
- Swagger: http://localhost:8000/docs
