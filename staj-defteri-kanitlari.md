# 5651 Hotspot — Staj Defteri Kanıt Çıktıları (2026-08-03)

Bu dosya Claude Code tarafından gerçek laptop üzerinde çalıştırılan komutların
ham çıktılarıdır. Ekran görüntüsü almak veya kopyala-yapıştır yapmak için
kullanabilirsin.

> Gizlilik: telefon numarası, donanım MAC adresleri, WAN IP ve ev dizini yolu
> maskelenmiştir (`5XXXXXXXXX`, `XX`, `<kullanici>`). `02:00:...` ile başlayan MAC
> adresleri gerçek değil, backend'in IP'den türettiği demo değerleridir.

---

## 1. AP Kurulumu Kanıtı (Şekil 14/16)

### `iw list` — valid interface combinations (AP+STA aynı radyoda destekleniyor)
```
valid interface combinations:
     * #{ managed } <= 1, #{ P2P-client, P2P-GO } <= 1, #{ P2P-device } <= 1,
       total <= 3, #channels <= 2
     * #{ managed } <= 1, #{ AP, P2P-client, P2P-GO } <= 1, #{ P2P-device } <= 1,
       total <= 3, #channels <= 1
```

### `ip addr show` — WAN (wlp0s20f3) ve ap0 aynı anda UP + IP'li
```
3: wlp0s20f3: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 ... state UP
    link/ether c4:bd:e5:XX:XX:26 brd ff:ff:ff:ff:ff:ff
    inet 10.x.x.55/24 brd 10.x.x.255 scope global dynamic noprefixroute wlp0s20f3

8: ap0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 ... state UP
    link/ether c4:bd:e5:XX:XX:28 brd ff:ff:ff:ff:ff:ff
    inet 192.168.4.1/24 scope global ap0
```

### `sudo WAN_IF=wlp0s20f3 LAN_IF=ap0 ./network/setup-ap.sh` çıktısı
```
[setup-ap] WAN_IF=wlp0s20f3  LAN_IF=ap0  AP_IP=192.168.4.1  PROJECT_PATH=/home/<kullanici>/codewithclaude
[setup-ap] ap0 üzerine statik IP atanıyor...
[setup-ap] IPv4 forwarding açılıyor...
[setup-ap] dnsmasq/hostapd config'leri yer tutuculardan üretiliyor...
[setup-ap] nftables ruleset yükleniyor (varsayılan DROP + dinamik izin listesi)...
[setup-ap] Docker'ın DOCKER-USER zincirine ap0<->wlp0s20f3 izin kuralları ekleniyor...
[setup-ap] dnsmasq ve hostapd yeniden başlatılıyor...
[setup-ap] Tamamlandı. Backend'i ENABLE_NFTABLES=true ile başlatmayı unutmayın
           (bkz. backend/nft_manager.py, docker-compose.yml).
```

### `systemctl status hostapd` / `systemctl status dnsmasq`
```
● hostapd.service - Access point and authentication server for Wi-Fi and Ethernet
     Active: active (running) since Mon 2026-08-03 15:30:48 +03

● dnsmasq.service - dnsmasq - A lightweight DHCP and caching DNS server
     Active: active (running) since Mon 2026-08-03 15:30:48 +03
```

### `iw dev ap0 info` — SSID + kanal doğrulaması
```
Interface ap0
	ssid 5651-Hotspot-Demo
	type AP
	channel 6 (2437 MHz), width: 20 MHz, center1: 2437 MHz
```

---

## 3. Gatekeeping Kanıtı (Şekil 14)

### Login ÖNCESİ — `nft list set inet hotspot allowed_clients`
```
table inet hotspot {
	set allowed_clients {
		type ipv4_addr
		flags interval
	}
}
```
(set boş — hiçbir istemci internete çıkamıyor, sadece DHCP/DNS/captive-portal IP'sine erişebiliyor)

### Login SONRASI — aynı komut
```
table inet hotspot {
	set allowed_clients {
		type ipv4_addr
		flags interval
		elements = { 192.168.4.246 }
	}
}
```

---

## 4. Log Bütünlüğü Kanıtı (Şekil 8/13)

### `POST /api/v1/log/sign` sonrası `GET /api/v1/log/verify` — imzalandıktan hemen sonra
```json
{
    "valid": true,
    "hash_matches": true,
    "signature_valid": true,
    "expected_sha256": "d16088f34ac45f63bc47b9abef5ed0c5d625faac7a16243b7bcef3fe5af4f87a",
    "current_sha256": "d16088f34ac45f63bc47b9abef5ed0c5d625faac7a16243b7bcef3fe5af4f87a",
    "message": "Log dosyası bütünlüğü DOĞRULANDI. İmza geçerli."
}
```

### Dosyada TEK BYTE bozulduktan sonra aynı endpoint
```json
{
    "valid": false,
    "hash_matches": false,
    "signature_valid": false,
    "expected_sha256": "d16088f34ac45f63bc47b9abef5ed0c5d625faac7a16243b7bcef3fe5af4f87a",
    "current_sha256": "c84aeb7b2e9a04bfa4837d5eba579bf81c6a8854d41d46b3280923db5414157d",
    "message": "UYARI: Log dosyası imzalandıktan sonra DEĞİŞTİRİLMİŞ! İmza geçersiz."
}
```
(Not: dosya sonra byte-identical olarak orijinaline geri yüklendi, gerçek log kaybı yok — `diff` ile doğrulandı.)

### `logs/archive/` klasör listesi
```
-rw-r--r-- 1 root root 859880 Ağu  3 15:32 dhcp_activity-2026-08-03T123213293Z.log
```

### `dhcp_activity.chain.jsonl` içeriği (1. kayıt)
```json
{
    "sequence": 1,
    "archived_file": "dhcp_activity-2026-08-03T123213293Z.log",
    "rotated_at": "2026-08-03T12:32:13.293Z",
    "line_count": 4780,
    "sha256": "6919e180f3e93783c8c584b6d2a04eeb47ddb59a7caf742d01047fd978ff1f8f",
    "algorithm": "RSA-2048 / PKCS#1 v1.5 / SHA-256",
    "prev_link_hash": "0000000000000000000000000000000000000000000000000000000000000000",
    "link_hash": "00f4ad54af2be891b2c35ef082c42f5f63d95a3aaf8f99df502af6e07a116a22"
}
```

### `GET /api/v1/log/chain` — zincirin bütünlük doğrulaması
```json
{
    "valid": true,
    "entry_count": 1,
    "entries": [
        {
            "sequence": 1,
            "chain_intact": true,
            "signature_valid": true,
            "archive_file_present": true,
            "archive_file_matches": true,
            "valid": true
        }
    ],
    "message": "Zincirdeki tüm kayıtlar bütünlük içinde (imza + hash chain doğrulandı)."
}
```

---

## 5. DNS Tabanlı Site Loglama (Şekil 9)

### `logs/dnsmasq_query.log` — gerçek telefon trafiğinden örnek satırlar
```
Aug  3 15:39:05 dnsmasq[21419]: query[A] www.google.com.tr from 192.168.4.246
Aug  3 15:39:05 dnsmasq[21419]: reply www.google.com.tr is 142.251.38.227
Aug  3 15:39:05 dnsmasq[21419]: query[A] analytics.google.com from 192.168.4.246
Aug  3 15:39:11 dnsmasq[21419]: query[A] connectivity.samsung.com.cn from 192.168.4.246
```

### `GET /api/v1/sitevisits?username=5XXXXXXXXX` — TC'ye bağlanmış gerçek ziyaretler
```json
[
  {
    "timestamp": "2026-08-03T12:39:11.535098+00:00",
    "username": "5XXXXXXXXX",
    "ip": "192.168.4.246",
    "domain": "connectivity.samsung.com.cn",
    "query_type": "A"
  },
  {
    "timestamp": "2026-08-03T12:39:05.516030+00:00",
    "username": "5XXXXXXXXX",
    "ip": "192.168.4.246",
    "domain": "stats.g.doubleclick.net",
    "query_type": "A"
  },
  {
    "timestamp": "2026-08-03T12:39:05.482068+00:00",
    "username": "5XXXXXXXXX",
    "ip": "192.168.4.246",
    "domain": "analytics.google.com",
    "query_type": "A"
  },
  {
    "timestamp": "2026-08-03T12:39:05.448453+00:00",
    "username": "5XXXXXXXXX",
    "ip": "192.168.4.246",
    "domain": "www.google.com.tr",
    "query_type": "A"
  }
]
```

---

## 6. Admin Panel — Oturum Yönetimi (Şekil 17)

### KICK ÖNCESİ — `GET /api/v1/admin/sessions`
```json
[
    {
        "id": 37,
        "username": "5XXXXXXXXX",
        "ip": "192.168.4.246",
        "mac": "02:00:C0:A8:04:F6",
        "login_time": "2026-08-03T12:38:04.168042+00:00",
        "remaining_seconds": 7099
    }
]
```

### KICK ÖNCESİ — `nft list set inet hotspot allowed_clients`
```
elements = { 192.168.4.246 }
```

### `POST /api/v1/admin/sessions/37/kick`
```json
{
    "status": "ok",
    "message": "5XXXXXXXXX kullanıcısının oturumu sonlandırıldı."
}
```

### KICK SONRASI — `GET /api/v1/admin/sessions`
```json
[]
```

### KICK SONRASI — `nft list set inet hotspot allowed_clients`
```
table inet hotspot {
	set allowed_clients {
		type ipv4_addr
		flags interval
	}
}
```
