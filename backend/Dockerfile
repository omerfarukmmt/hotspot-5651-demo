FROM python:3.12-slim

WORKDIR /app

# nftables: gercek hotspot kurulumunda ENABLE_NFTABLES=true iken backend'in
# (--network host + --cap-add=NET_ADMIN ile) host'un nft ruleset'ini
# duzenleyebilmesi icin gerekli (bkz. backend/nft_manager.py).
RUN apt-get -o Acquire::ForceIPv4=true update \
    && apt-get -o Acquire::ForceIPv4=true install -y --no-install-recommends nftables \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/logs

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
