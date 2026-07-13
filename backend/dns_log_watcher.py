"""dnsmasq sorgu logunu izleme yardımcıları.

Gerçek hotspot kurulumunda tüm istemci DNS sorguları dnsmasq üzerinden geçer
(bkz. README - "Ağ Kurulumu"). dnsmasq `log-queries` açıkken satırları şu
formatta yazar:

    Jul 13 15:04:05 dnsmasq[123]: query[A] example.com from 192.168.4.50

Bu modül o log dosyasını `tail -f` gibi izler ve her satırı (tip, domain, ip)
üçlüsüne ayrıştırır. HTTPS içeriği şifreli olduğu için içerik değil, hangi
domain'e gidildiği loglanır — 5651 kapsamındaki pratik de zaten budur.
"""
import asyncio
import os
import re

QUERY_RE = re.compile(r"query\[(?P<qtype>\w+)\]\s+(?P<domain>\S+)\s+from\s+(?P<ip>\S+)")


async def follow(path: str, poll_interval: float = 1.0):
    """Dosyayı sondan izler; dosya henüz yoksa oluşana kadar bekler,
    log-rotate ile küçülürse baştan açar."""
    while not os.path.exists(path):
        await asyncio.sleep(poll_interval)

    f = open(path, "r", encoding="utf-8", errors="ignore")
    try:
        f.seek(0, os.SEEK_END)
        while True:
            line = f.readline()
            if not line:
                await asyncio.sleep(poll_interval)
                try:
                    if os.path.getsize(path) < f.tell():
                        f.close()
                        f = open(path, "r", encoding="utf-8", errors="ignore")
                except OSError:
                    pass
                continue
            yield line.rstrip("\n")
    finally:
        f.close()


def parse_query_line(line: str):
    """Bir dnsmasq log satırını (qtype, domain, ip) olarak döndürür; eşleşmezse None."""
    match = QUERY_RE.search(line)
    if not match:
        return None
    return match.group("qtype"), match.group("domain"), match.group("ip")
