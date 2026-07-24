#!/usr/bin/env bash
# setup-ap.sh — gerçek hotspot Linux kutusunda (Raspberry Pi / eski laptop) bir
# kere elle çalıştırılacak kurulum betiği. Docker Compose demosuyla bir ilgisi
# YOKTUR; bu, PROGRESS.md'deki "gerçek hotspot'a dönüştürme" adımlarının
# LAN/AP + WAN tarafını hazırlar.
#
# Varsayımlar:
#   - WAN_IF: laptop'un dahili Wi-Fi'ı, telefonun mobil hotspot'una wpa_supplicant
#     ile önceden bağlanmış (bu betik WAN bağlantısını KURMAZ, sadece kullanır).
#   - LAN_IF: AP/master mode destekleyen USB Wi-Fi adaptör.
#
# Kullanım:
#   sudo WAN_IF=wlan0 LAN_IF=wlan1 ./setup-ap.sh

set -euo pipefail

WAN_IF="${WAN_IF:-wlan0}"
LAN_IF="${LAN_IF:-wlan1}"
AP_IP="${AP_IP:-192.168.4.1}"
PROJECT_PATH="${PROJECT_PATH:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

echo "[setup-ap] WAN_IF=$WAN_IF  LAN_IF=$LAN_IF  AP_IP=$AP_IP  PROJECT_PATH=$PROJECT_PATH"

command -v hostapd >/dev/null || { echo "hostapd kurulu değil (apt install hostapd)"; exit 1; }
command -v dnsmasq >/dev/null || { echo "dnsmasq kurulu değil (apt install dnsmasq)"; exit 1; }
command -v nft >/dev/null || { echo "nftables kurulu değil (apt install nftables)"; exit 1; }

echo "[setup-ap] $LAN_IF üzerine statik IP atanıyor..."
ip addr flush dev "$LAN_IF"
ip addr add "${AP_IP}/24" dev "$LAN_IF"
ip link set "$LAN_IF" up

echo "[setup-ap] IPv4 forwarding açılıyor..."
sysctl -w net.ipv4.ip_forward=1 >/dev/null

echo "[setup-ap] dnsmasq/hostapd config'leri yer tutuculardan üretiliyor..."
sed "s#<PROJECT_PATH>#${PROJECT_PATH}#g" "${PROJECT_PATH}/network/dnsmasq.conf.example" \
    | sed "s/wlan1/${LAN_IF}/g" > /etc/dnsmasq.conf
sed "s/wlan1/${LAN_IF}/g" "${PROJECT_PATH}/network/hostapd.conf.example" > /etc/hostapd/hostapd.conf

echo "[setup-ap] nftables ruleset yükleniyor (varsayılan DROP + dinamik izin listesi)..."
sed -e "s/wlan0/${WAN_IF}/g" -e "s/wlan1/${LAN_IF}/g" -e "s/192\\.168\\.4\\.1/${AP_IP}/g" \
    "${PROJECT_PATH}/network/nftables.conf" | nft -f -

echo "[setup-ap] dnsmasq ve hostapd yeniden başlatılıyor..."
systemctl restart dnsmasq
systemctl restart hostapd

echo "[setup-ap] Tamamlandı. Backend'i ENABLE_NFTABLES=true ile başlatmayı unutmayın"
echo "           (bkz. backend/nft_manager.py, docker-compose.yml)."
