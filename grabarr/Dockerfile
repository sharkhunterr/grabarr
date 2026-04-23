# Grabarr — multi-source media indexer (Docker image)
#
# Two-stage build:
#   1. builder: installs build-time deps, runs `uv sync --frozen`, downloads
#      the Tailwind standalone binary to compile CSS.
#   2. runtime: copies the venv + compiled CSS from builder, installs minimal
#      runtime libs only.
#
# Ports:
#   - 8080: main HTTP (admin UI, Torznab, /healthz, /metrics, tracker /announce)
# Volumes:
#   - /config:   config.yaml + any operator-provided YAML
#   - /data:     SQLite DB + libtorrent session state (future)
#   - /downloads: incoming + ready file staging

# ---- Builder stage ---------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/grabarr/.venv

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        libxml2-dev \
        libxslt-dev \
        libtorrent-rasterbar-dev \
        libboost-python-dev \
        libboost-system-dev \
        libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv.
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /uvx /usr/local/bin/

WORKDIR /opt/grabarr

# Copy dependency manifests first to maximise layer caching.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

# Download the standalone Tailwind binary for CSS compile.
RUN ARCH=$(uname -m | sed 's/x86_64/x64/;s/aarch64/arm64/') && \
    curl -sSL -o /usr/local/bin/tailwindcss \
        "https://github.com/tailwindlabs/tailwindcss/releases/download/v3.4.14/tailwindcss-linux-${ARCH}" && \
    chmod +x /usr/local/bin/tailwindcss

# Copy project source.
COPY grabarr ./grabarr
COPY alembic.ini ./alembic.ini
COPY config.example.yaml ./config.example.yaml

# Compile Tailwind CSS (best-effort; MVP templates also reference the CDN).
RUN tailwindcss \
    --input  /opt/grabarr/grabarr/web/static/css/tailwind.input.css \
    --output /opt/grabarr/grabarr/web/static/css/tailwind.build.css \
    --minify || echo "[grabarr] Tailwind CLI compile skipped (CDN fallback in templates)"

# Install the project itself.
RUN uv sync --frozen --no-dev

# ---- Runtime stage ---------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/grabarr/.venv/bin:$PATH" \
    GRABARR_SERVER__DATA_DIR=/data \
    GRABARR_SERVER__DOWNLOADS_DIR=/downloads \
    GRABARR_CONFIG_PATH=/config/grabarr.yaml

# Minimal runtime libs for lxml, cryptography, etc.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libxml2 \
        libxslt1.1 \
        libtorrent-rasterbar2.0 \
        libboost-python1.83.0 \
        libboost-system1.83.0 \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --create-home --home-dir /home/grabarr grabarr

# Bring over the installed venv and project from builder.
COPY --from=builder --chown=grabarr:grabarr /opt/grabarr /opt/grabarr

WORKDIR /opt/grabarr

# Create volume directories up front so mount points exist at the right perms.
RUN mkdir -p /config /data /downloads/incoming /downloads/ready && \
    chown -R grabarr:grabarr /config /data /downloads

USER grabarr

EXPOSE 8080 45000-45100/tcp 45000-45100/udp

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8080/healthz || exit 1

CMD ["uvicorn", "grabarr.api.app:app", "--host", "0.0.0.0", "--port", "8080"]
