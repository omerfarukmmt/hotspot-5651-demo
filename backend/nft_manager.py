"""Gerçek gatekeeping: nftables `allowed_clients` set'ine IP ekleme/silme.

Docker Compose demosunda (Windows/Mac dev makinesi, `nft` binary'si yok) bu
modül tamamen no-op çalışır — sadece log basar. Gerçek Linux hotspot kutusunda
`ENABLE_NFTABLES=true` set edilip backend `NET_ADMIN` yetkisiyle çalıştırılınca
gerçek `nft` komutlarını tetikler (bkz. `network/README.md`).

Ruleset `network/nftables.conf`'ta tanımlıdır: forward zinciri varsayılan DROP,
sadece `@allowed_clients` set'indeki IP'ler WAN'a çıkabilir.
"""
import os
import subprocess

ENABLE_NFTABLES = os.getenv("ENABLE_NFTABLES", "false").strip().lower() == "true"
NFT_TABLE_FAMILY = os.getenv("NFT_TABLE_FAMILY", "inet")
NFT_TABLE = os.getenv("NFT_TABLE", "hotspot")
NFT_SET = os.getenv("NFT_SET", "allowed_clients")


def _run_nft(args: list[str]) -> bool:
    try:
        subprocess.run(["nft", *args], check=True, capture_output=True, text=True, timeout=5)
        return True
    except FileNotFoundError:
        print("[nft_manager] 'nft' komutu bulunamadı (Docker demo ortamında beklenen durum).", flush=True)
    except subprocess.CalledProcessError as exc:
        print(f"[nft_manager] nft komutu basarisiz: {' '.join(args)} -> {exc.stderr.strip()}", flush=True)
    except subprocess.TimeoutExpired:
        print(f"[nft_manager] nft komutu zaman asimina ugradi: {' '.join(args)}", flush=True)
    return False


def allow_client(ip: str) -> None:
    """Giriş yapan istemcinin IP'sini nftables allow-set'ine ekler (gerçek internet erişimi açılır)."""
    if not ENABLE_NFTABLES:
        print(f"[nft_manager] (devre disi) allow_client atlandi: {ip}", flush=True)
        return
    if _run_nft(["add", "element", NFT_TABLE_FAMILY, NFT_TABLE, NFT_SET, "{", ip, "}"]):
        print(f"[nft_manager] {ip} allow-set'e eklendi.", flush=True)


def revoke_client(ip: str) -> None:
    """Çıkış yapan/oturumu dolan istemcinin IP'sini allow-set'ten siler (erişim gerçekten kesilir)."""
    if not ENABLE_NFTABLES:
        print(f"[nft_manager] (devre disi) revoke_client atlandi: {ip}", flush=True)
        return
    if _run_nft(["delete", "element", NFT_TABLE_FAMILY, NFT_TABLE, NFT_SET, "{", ip, "}"]):
        print(f"[nft_manager] {ip} allow-set'ten silindi.", flush=True)
