# Gerçek hotspot ağ kurulumu

Bu dizin, Docker Compose demosunun *dışında*, gerçek bir Linux kutusunda
çalıştırılacak ağ katmanı konfigürasyonlarını içerir. Docker demosu bu
dosyalara ihtiyaç duymaz; `PROGRESS.md`'de kararlaştırılan "gerçek hotspot'a
dönüştürme" planının LAN/AP + gatekeeping kısmını hazırlar.

**Durum: 2026-07-24'te bu dizindeki her şey gerçek donanımda (bir Ubuntu
laptop, USB adaptör olmadan, tek dahili Wi-Fi kartıyla) uçtan uca test edildi**
— gerçek bir telefon SSID'ye bağlandı, captive portal + TC/OTP girişi + gerçek
nftables gatekeeping + gerçek internet erişimi doğrulandı. Aşağıdaki adımlar
hem USB adaptörlü hem tek-kart senaryosu için geçerlidir.

## Bileşenler

| Dosya | Görev |
|---|---|
| `hostapd.conf.example` | LAN/AP arayüzünü (USB adaptör ya da aynı kartın sanal arayüzü) AP'ye çevirir, kendi SSID'sini yayınlar |
| `dnsmasq.conf.example` | DHCP dağıtır, DNS sorgularını loglar, captive-portal auto-detect domain'lerini AP IP'sine yönlendirir |
| `nftables.conf` | Varsayılan DROP + `allowed_clients` set'ine giren IP'lere ACCEPT (gerçek gatekeeping) + `docker0` istisnası |
| `setup-ap.sh` | Yukarıdaki üçünü doğru arayüz adlarıyla üretip yükleyen kurulum betiği |

## Mimari

```
Telefon (mobil veri) ──Wi-Fi──► WAN_IF (laptop dahili Wi-Fi, ör. wlp0s20f3)
                                     │ (wpa_supplicant/NetworkManager ile önceden bağlı,
                                     │  bu dizinin dışında)
                                     │
                              [ nftables NAT/forward ]
                                     │
                              LAN_IF (USB AP adaptör YA DA aynı fiziksel
                                      kartın sanal arayüzü, ör. ap0) ──► hostapd SSID
                                     │
                              dnsmasq (DHCP: 192.168.4.10-250, DNS, query log)
                                     │
                          İstemci cihazlar (telefon/laptop) 192.168.4.0/24
```

`setup-ap.sh` `WAN_IF`/`LAN_IF`'i env değişkeni olarak parametrik aldığı için
aynı script iki farklı fiziksel adaptörle de, tek bir kartın fiziksel arayüzü +
sanal AP arayüzüyle de (aşağıya bakın) değişmeden çalışır.

Backend (FastAPI) hâlâ Docker Compose ile 192.168.4.1 üzerinde (nginx :80,
backend :8000 dahili) çalışır; `nginx.conf` içindeki `auth_request` mantığı
değişmez. Değişen tek şey: backend artık login/logout anında **gerçek**
nftables set'ine IP ekleyip/siliyor (bkz. `backend/nft_manager.py`), yani
oturumu olmayan bir cihaz artık sadece portala değil, **hiçbir yere** çıkamıyor.

## Tek kart (USB adaptörsüz) kurulum — test edilen yapılandırma

Kartın concurrent AP+STA desteklediğini (`iw list | grep -A 15 "valid
interface combinations"` çıktısında `managed` + `AP` birlikte geçen bir
kombinasyon) doğruladıktan sonra:

```bash
# 1. Sanal AP arayüzü oluştur
sudo iw dev wlp0s20f3 interface add ap0 type __ap

# 2. NetworkManager'ın onu ele geçirmesini KALICI olarak engelle — "managed no"yu
#    arayüz oluştuktan SONRA çalıştırmak yeterli değil, NetworkManager arayüz
#    oluşur oluşmaz (< 1 sn içinde) onu otomatik yönetime alıp wpa_supplicant ile
#    kapmaya çalışıyor ve "Device or resource busy" hatasına yol açıyor.
sudo tee /etc/NetworkManager/conf.d/10-unmanaged-ap0.conf <<'EOF'
[keyfile]
unmanaged-devices=interface-name:ap0
EOF
sudo nmcli general reload conf

# 3. WAN'ın o anki kanalını kontrol et ve hostapd.conf.example'daki channel=
#    değerini buna göre ayarla (kart tek kanal kısıtı taşıyor — AP ve WAN aynı
#    kanalda olmak zorunda; iw list'te "#channels<=1" olarak görünür).
iw dev wlp0s20f3 info | grep channel

sudo WAN_IF=wlp0s20f3 LAN_IF=ap0 ./setup-ap.sh
```

**Bilinen kırılganlıklar (donanım/sürücü kaynaklı, kod hatası değil):**
- `ap0` sanal bir arayüzdür, **reboot'ta kalıcı değildir** — her açılışta 1.
  adım tekrarlanmalı (NetworkManager düzeltmesi kalıcı olduğu için "busy"
  hatası bir daha çıkmaz).
- Telefon hotspot'u kendi kanalını **kendiliğinden değiştirebilir** (bu oturumda
  6'dan 1'e değişti). Bu durumda `hostapd` sessizce yayını kesiyor ama
  `systemctl status hostapd` yine de `active (running)` gösteriyor —
  yanıltıcı. Gerçek durumu her zaman `iw dev ap0 info` ile teyit edin (SSID +
  kanal görünmeli, `ip addr show ap0` `UP,LOWER_UP` olmalı). Uyuşmazlık varsa
  `/etc/hostapd/hostapd.conf`'taki `channel=`'ı güncelleyip
  `sudo systemctl restart hostapd`.

## Kurulum (özet)

```bash
sudo apt install hostapd dnsmasq nftables
sudo systemctl unmask hostapd
sudo WAN_IF=wlp0s20f3 LAN_IF=ap0 ./setup-ap.sh   # ya da USB adaptörse LAN_IF=wlan1 vb.
```

Backend'i `ENABLE_NFTABLES=true` ile başlatmak için ana `docker-compose.yml`'i
**değiştirmeyin** — ayrı bir override dosyası olan kök dizindeki
`docker-compose.host.yml` bunu sağlar (backend + nginx'i `--network host` +
backend'e `--cap-add=NET_ADMIN` ile ayağa kaldırır, `postgres`/`redis`'i
`127.0.0.1`'e açar):

```bash
sudo docker compose -f docker-compose.yml -f docker-compose.host.yml up -d --build
```

## dnsmasq upstream DNS notu (önemli)

Debian/Ubuntu'nun `dnsmasq` systemd birimi upstream DNS listesini
`/run/dnsmasq/resolv.conf`'tan okur; bu dosya normalde WAN arayüzü
**systemd-networkd** ile yönetiliyorsa otomatik doldurulur. WAN
**NetworkManager** ile yönetiliyorsa (bu projenin varsayımı — telefon
hotspot'una `wpa_supplicant`/NetworkManager ile bağlanma) bu mekanizma
sessizce çalışmaz ve dnsmasq'ın **hiç** upstream sunucusu kalmaz — sonuç:
captive-portal domain'leri dışındaki her DNS sorgusu `REFUSED` döner (gerçek
telefon testinde bu şekilde tespit edildi: arama sonuçları geliyordu ama
sitelere girilemiyordu). Bu yüzden `dnsmasq.conf.example` artık doğrudan
`server=127.0.0.53` (systemd-resolved'ın kendi stub resolver'ı) satırını
içeriyor — WAN arayüzü ne olursa olsun NetworkManager'ın negotiate ettiği
gerçek upstream'i doğru şekilde yansıtır.

## Docker'ın kendi ağının kırılmaması notu

`nftables.conf`'taki `forward` zincirinin varsayılan politikası DROP'tur ve
sadece `ap0` trafiğini allowlist'e alır. Bu, aynı makinede çalışan **Docker
container'larının** kendi internet erişimini de (docker0 → WAN yönlendirmesi)
kırar — çünkü aynı hook'ta (forward) kayıtlı birden fazla nftables tablosu
bağımsız değerlendirilir ve herhangi biri DROP derse paket düşer (Docker'ın
kendi iptables-nft kuralları buna engel olamaz). Bu yüzden `nftables.conf`'a
açık `iifname "docker0" accept` / `oifname "docker0" accept` kuralları
eklendi. Bu makine hem hotspot kutusu hem geliştirme makinesi olarak
kullanıldığı için bu istisna kalıcıdır; salt bir hotspot kutusunda (Docker
kurulu değilse) zararsızdır, kaldırmaya gerek yoktur.
