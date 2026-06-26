# Canopy Production Dockerfile
FROM python:3.11-slim

LABEL org.opencontainers.image.title="Canopy"
LABEL org.opencontainers.image.description="Nature-Tech Crypto Trading Terminal"

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates build-essential libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data/cache /app/logs

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8080/api/kpi || exit 1

CMD ["python", "-m", "canopy.web.server"]
