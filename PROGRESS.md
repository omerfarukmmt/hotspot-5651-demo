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

### 2. Gerçek hotspot'a dönüştürme planı (KODLANDI + gerçek donanımda UÇTAN UCA TEST EDİLDİ — 2026-07-24)
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

**Tamamlandı (2026-07-24, bkz. aşağıdaki "Laptop üzerinde..." bölümünün sonu):**
- [x] USB adaptöre gerek kalmadan, laptopun tek dahili Wi-Fi kartıyla
      (concurrent AP+STA) hem WAN hem AP çalıştırıldı — donanım/sürücü desteği
      doğrulandı (Intel AX201/iwlwifi).
- [x] `network/setup-ap.sh` + hostapd/dnsmasq/nftables config'leri gerçek
      donanımda (bu Ubuntu laptop) uçtan uca çalıştırıldı ve doğrulandı.
- [x] Backend konteyneri `--network host` + `--cap-add=NET_ADMIN` ile ayağa
      kaldırıldı — ama ana `docker-compose.yml`'e DEĞİL, ayrı bir
      **`docker-compose.host.yml`** override dosyasına eklendi (ana dosya
      demo/cross-platform modda değişmeden kaldı). Çalıştırma:
      ```bash
      sudo docker compose -f docker-compose.yml -f docker-compose.host.yml up -d --build
      ```
      nginx de aynı override'da `network_mode: host`'a alındı (backend'e
      servis-DNS'siz ulaşabilmek + gerçek AP istemcilerinin `192.168.4.1:80`'e
      doğrudan erişebilmesi için), ayrı bir `nginx/nginx.host.conf` ile.
- [x] Gerçek bir telefon `5651-Hotspot-Demo` SSID'sine bağlandı, captive portal
      açıldı, TC+OTP girişi yapıldı, `nft_manager.py`'nin gerçekten
      `nft add/delete element` çalıştırdığı doğrulandı (host'un canlı
      `allowed_clients` set'i değişti), giriş sonrası **gerçek internete**
      çıkabildiği doğrulandı.

Yol boyunca çıkan ve düzeltilen yan etkiler (ayrıntılar aşağıdaki
"Laptop üzerinde..." bölümünde):
- Bu laptopta Docker hiç kurulu değildi → `docker.io` + `docker-compose-v2`
  kuruldu (Ubuntu'da `docker-compose-plugin` diye bir paket YOK).
- AP'nin kendi nftables ruleset'i (varsayılan DROP forward zinciri) Docker'ın
  kendi container'larının internetini de kırmıştı → `network/nftables.conf`'a
  `docker0` için açık `accept` kuralı eklendi.
- `dnsmasq`'ın systemd birimi upstream DNS'i `resolvconf`/systemd-networkd
  entegrasyonundan bekliyordu, bu makinede WAN NetworkManager ile yönetildiği
  için bu sessizce çalışmıyordu → `network/dnsmasq.conf.example`'a
  `server=127.0.0.53` (systemd-resolved stub) eklendi. Bu olmadan gerçek
  siteler DNS seviyesinde "Refused" dönüyordu (telefonla yapılan gerçek testte
  yakalandı: arama sonuçları geliyordu ama sitelere girilemiyordu).
- `hostapd`, telefonun kendi kanalını değiştirmesi (6→1) durumunda sessizce
  yayın yapmayı kesiyor ama `systemctl status` hâlâ "active" gösteriyor —
  gerçek durumu her zaman `iw dev ap0 info` (SSID + kanal görünüyor mu) ile
  teyit etmek gerekiyor.

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

## Laptop üzerinde harici Wi-Fi adaptörsüz AP denemesi (2026-07-22 → 2026-07-24, TAMAMLANDI)

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

**Sonuç:** Kart concurrent AP+STA destekliyor (`iw list` combo:
`#{managed}<=1, #{AP,P2P-client,P2P-GO}<=1, total<=3, #channels<=1` — tek
kanal kısıtı var, yani AP her zaman WAN'ın o an bağlı olduğu kanalda olmak
zorunda). Uygulanan adımlar:

1. Sanal AP arayüzü: `sudo iw dev wlp0s20f3 interface add ap0 type __ap`.
2. NetworkManager'ın `ap0`'ı ele geçirmesi (oluşur oluşmaz otomatik
   yönetime alıp wpa_supplicant ile kapmaya çalışıyordu — `nmcli device set
   ap0 managed no` komutu her zaman bir adım geç kalıyordu, "Device or
   resource busy" hatasının asıl kaynağı buydu) **kalıcı olarak**
   `/etc/NetworkManager/conf.d/10-unmanaged-ap0.conf` ile engellendi:
   ```
   [keyfile]
   unmanaged-devices=interface-name:ap0
   ```
   Bu dosya repo dışında (sistem seviyesinde) — başka bir makinede
   tekrarlanırsa bu adım yeniden yapılmalı.
3. `hostapd.conf.example`'daki `channel=` değeri WAN'ın o anki kanalıyla
   eşleştirildi — ama bu **statik** bir eşleşme değil: telefon hotspot'u
   kanalını kendi kendine değiştirebiliyor (bu oturumda 6'dan 1'e değişti),
   bu durumda hostapd sessizce yayını kesiyor (`systemctl status` yine de
   "active" gösteriyor). AP'yi tekrar ayağa kaldırırken önce
   `iw dev wlp0s20f3 info` ile WAN'ın güncel kanalını kontrol edip
   `/etc/hostapd/hostapd.conf`'taki `channel=`'ı ona göre güncellemek ve
   `systemctl restart hostapd` sonrası `iw dev ap0 info`'da SSID+kanalın
   göründüğünü teyit etmek gerekiyor.
4. `sudo WAN_IF=wlp0s20f3 LAN_IF=ap0 ./network/setup-ap.sh` — script değişmeden
   çalıştı, uçtan uca doğrulandı (hostapd+dnsmasq+nftables).
5. Docker bu makinede kurulu değildi, kuruldu (`docker.io` +
   `docker-compose-v2`); backend gerçek `ENABLE_NFTABLES=true` +
   `--network host --cap-add=NET_ADMIN` ile `docker-compose.host.yml`
   override'ından ayağa kaldırıldı (bkz. yukarıdaki bölüm 2).
6. Gerçek bir telefonla (Galaxy Tab S9 FE) uçtan uca test edildi: bağlantı →
   captive portal → TC+OTP girişi → gerçek nftables gatekeeping → gerçek DNS
   çözümleme (bkz. bölüm 2'deki `dnsmasq` upstream düzeltmesi) → gerçek
   internet erişimi, hepsi çalışır durumda doğrulandı.

`ap0` sanal bir arayüz olduğu için **reboot'ta kalıcı değil** — her açılışta
`iw dev wlp0s20f3 interface add ap0 type __ap` ile yeniden oluşturulup
`setup-ap.sh` tekrar çalıştırılmalı (NetworkManager conf.d düzeltmesi kalıcı
olduğu için "busy" hatası bir daha çıkmıyor).

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
- [x] Yukarıdaki "gerçek hotspot" checklist'i 2026-07-24'te tamamlandı ve
      gerçek bir telefonla uçtan uca test edildi (bkz. bölüm 2 ve "Laptop
      üzerinde..." bölümü) — sistem artık Docker demo'sunun ötesinde, gerçek
      cihazlarla internet paylaşabiliyor.
- [x] hostapd/nftables kurulumu bu laptopta prova edildi (2026-07-24).
- [ ] Demo günü öncesi son bir kez daha prova et — özellikle telefon hotspot'un
      kanalını değiştirmiş olabileceğini unutma (`iw dev wlp0s20f3 info` ile
      kontrol, gerekirse `/etc/hostapd/hostapd.conf`'ta `channel=` güncelle).
- [ ] `docker-compose.host.yml` ile ayağa kaldırma komutunu ezberden değil,
      buradan/`network/README.md`'den kopyala:
      `sudo docker compose -f docker-compose.yml -f docker-compose.host.yml up -d --build`

## Nasıl çalıştırılır

```bash
cd hotspot-5651-demo
docker compose up --build
```
- Portal: http://localhost:8080
- Admin panel: http://localhost:8080/portal/admin.html
- Swagger: http://localhost:8000/docs
