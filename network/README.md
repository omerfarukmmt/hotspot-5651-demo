# Gerçek hotspot ağ kurulumu

Bu dizin, Docker Compose demosunun *dışında*, gerçek bir Linux kutusunda
(Raspberry Pi, eski laptop vb.) çalıştırılacak ağ katmanı konfigürasyonlarını
içerir. Docker demosu bu dosyalara ihtiyaç duymaz; sadece `PROGRESS.md`'de
kararlaştırılan "gerçek hotspot'a dönüştürme" planının LAN/AP + gatekeeping
kısmını hazırlar.

## Bileşenler

| Dosya | Görev |
|---|---|
| `hostapd.conf.example` | USB Wi-Fi adaptörünü AP'ye çevirir, kendi SSID'sini yayınlar |
| `dnsmasq.conf.example` | DHCP dağıtır, DNS sorgularını loglar, captive-portal auto-detect domain'lerini AP IP'sine yönlendirir |
| `nftables.conf` | Varsayılan DROP + `allowed_clients` set'ine giren IP'lere ACCEPT (gerçek gatekeeping) |
| `setup-ap.sh` | Yukarıdaki üçünü doğru arayüz adlarıyla üretip yükleyen kurulum betiği |

## Mimari

```
Telefon (mobil veri) ──Wi-Fi──► WAN_IF (laptop dahili Wi-Fi, ör. wlan0)
                                     │ (wpa_supplicant ile önceden bağlı, bu dizinin dışında)
                                     │
                              [ nftables NAT/forward ]
                                     │
                              LAN_IF (USB AP adaptör, ör. wlan1) ──► hostapd SSID
                                     │
                              dnsmasq (DHCP: 192.168.4.10-250, DNS, query log)
                                     │
                          İstemci cihazlar (telefon/laptop) 192.168.4.0/24
```

Backend (FastAPI) hâlâ Docker Compose ile 192.168.4.1 üzerinde (nginx :80,
backend :8000 dahili) çalışır; `nginx.conf` içindeki `auth_request` mantığı
değişmez. Değişen tek şey: backend artık login/logout anında **gerçek**
nftables set'ine IP ekleyip/siliyor (bkz. `backend/nft_manager.py`), yani
oturumu olmayan bir cihaz artık sadece portala değil, **hiçbir yere** çıkamıyor.

## Kurulum (özet)

```bash
sudo apt install hostapd dnsmasq nftables
sudo systemctl unmask hostapd
sudo WAN_IF=wlan0 LAN_IF=wlan1 ./setup-ap.sh
```

Backend'i `ENABLE_NFTABLES=true` ile başlatın (bkz. kök `docker-compose.yml`
veya backend'i konteynersiz çalıştırıyorsanız ortam değişkeni olarak).
Konteyner içinde çalışıyorsa backend'in `nft` komutunu host'ta çalıştırabilmesi
için `--network host` + `--cap-add=NET_ADMIN` gerekir (bkz. ana `README.md`).

## Henüz yapılmadı

- USB Wi-Fi adaptörün temin edilip AP modunun gerçek donanımda test edilmesi.
- `setup-ap.sh`'nin gerçek donanımda uçtan uca prova edilmesi (demo gününden
  1-2 gün önce, bkz. kök `PROGRESS.md`).
