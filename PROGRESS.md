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

### 2. Gerçek hotspot'a dönüştürme planı (henüz KODLANMADI, sadece karar verildi)
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

**Henüz yapılmadı:**
- [ ] hostapd/dnsmasq/nftables konfigürasyonlarının yazılması
- [ ] FastAPI login/logout akışına gerçek `nft add/delete element` çağrılarının
      eklenmesi (şu an sadece Redis+Postgres'e yazıyor, firewall'a dokunmuyor)
- [ ] Gerçek MAC adresinin dnsmasq lease dosyası/ARP'tan okunması
      (şu an `simulate_mac()` ile IP'den türetiliyor — `backend/main.py`)
- [ ] iOS/Android captive portal auto-detection domain'lerinin (ör.
      `captive.apple.com`, `connectivitycheck.gstatic.com`) dnsmasq'ta
      portale yönlendirilmesi
- [ ] USB Wi-Fi adaptörün temin edilip AP modunun test edilmesi

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

## Demo günü öncesi yapılacaklar (checklist)

- [ ] `docker-compose.yml` içindeki `ADMIN_API_KEY` değerini değiştir
      (varsayılan `changeme-admin-key` demoya açık bırakılmamalı).
- [ ] `logs/dnsmasq_query.log` içindeki test verisini temizle (youtube/
      instagram gibi sahte satırlar test amaçlıydı).
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
