# Grabarr — multi-source media indexer (Docker image)
#
# Two-stage build:
#   1. builder: installs build-time deps, runs `uv sync --frozen` INCLUDING
#      the internal-bypasser extra (seleniumbase), downloads the Tailwind
#      standalone binary to compile CSS.
#   2. runtime: copies the venv + compiled CSS from builder, installs the
#      runtime libs + Chromium + Xvfb + ffmpeg so the internal CF bypasser
#      (SeleniumBase cdp_driver) can actually launch a browser.
#
# Ports:
#   - 8080: main HTTP (admin UI, Torznab, /healthz, /metrics, tracker /announce)
#   - 45000-45100 tcp+udp: libtorrent listen range for active_seed mode
# Volumes:
#   - /config:    config.yaml + any operator-provided YAML
#   - /data:      SQLite DB + libtorrent session state + Shelfmark runtime dirs
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
# --extra internal-bypasser pulls seleniumbase so bypass.mode=internal works
# out of the box. It adds ~400 MB to the venv but the whole point of running
# Grabarr in Docker is to ship a working bypasser image.
RUN uv sync --frozen --no-dev --no-install-project --extra internal-bypasser

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
RUN uv sync --frozen --no-dev --extra internal-bypasser

# ---- Runtime stage ---------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/grabarr/.venv/bin:$PATH" \
    GRABARR_SERVER__DATA_DIR=/data \
    GRABARR_SERVER__DOWNLOADS_DIR=/downloads \
    GRABARR_CONFIG_PATH=/config/grabarr.yaml \
    # Shelfmark's vendored config/env.py defaults to /var/log/shelfmark + /config.
    # Pin these to subdirs of /data so they persist across restarts + the
    # non-root 'grabarr' user can write to them.
    LOG_ROOT=/data/shelfmark/log_root \
    CONFIG_DIR=/data/shelfmark/config \
    TMP_DIR=/data/shelfmark/tmp \
    INGEST_DIR=/data/shelfmark/ingest \
    # Chrome needs a writable HOME for its profile cache, ~/.config dirs,
    # and the .local/share/applications/mimeapps.list bootstrapping it
    # does on every launch. /tmp is world-writable so the uid the user
    # picks via docker-compose's `user:` directive always works.
    HOME=/tmp \
    XDG_CONFIG_HOME=/tmp/.config \
    XDG_CACHE_HOME=/tmp/.cache

# Runtime libs + Google Chrome + Xvfb + ffmpeg. These are what make
# bypass.mode=internal actually work — SeleniumBase's cdp_driver drives
# a headless Chrome inside a virtual framebuffer and needs ffmpeg for
# its optional debug recording path.
#
# We use google-chrome-stable from Google's repo rather than Debian's
# chromium package because the latter crashes in Docker with a
# crashpad error (Trace/breakpoint trap) even with --no-sandbox +
# --disable-crashpad — see https://bugs.debian.org/cgi-bin/bugreport.cgi?bug=1052478
RUN apt-get update && apt-get install -y --no-install-recommends \
        libxml2 \
        libxslt1.1 \
        libtorrent-rasterbar2.0 \
        libboost-python1.83.0 \
        libboost-system1.83.0 \
        ca-certificates \
        curl \
        gnupg \
        xvfb \
        ffmpeg \
        fonts-liberation \
        libnss3 \
        libgbm1 \
        libasound2 \
        libxcomposite1 \
        libxdamage1 \
        libxrandr2 \
        libx11-xcb1 \
        libxkbcommon0 \
        libcairo2 \
        libpango-1.0-0 \
        libatk1.0-0 \
        libatk-bridge2.0-0 \
        libdrm2 \
    # Add Google's Chrome signing key + repo, then install chrome-stable.
    && curl -sSL https://dl.google.com/linux/linux_signing_key.pub \
        | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] https://dl.google.com/linux/chrome/deb/ stable main" \
        > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update && apt-get install -y --no-install-recommends \
        google-chrome-stable \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --create-home --home-dir /home/grabarr grabarr \
    # Shelfmark's cdp_driver looks for `chromium` or `google-chrome` in PATH;
    # make both names resolve to the Google Chrome binary.
    && ln -sf /usr/bin/google-chrome-stable /usr/local/bin/chromium \
    && ln -sf /usr/bin/google-chrome-stable /usr/local/bin/google-chrome

# Bring over the installed venv and project from builder.
COPY --from=builder --chown=grabarr:grabarr /opt/grabarr /opt/grabarr

WORKDIR /opt/grabarr

# Create volume directories up front so mount points exist at the right perms,
# including the Shelfmark runtime dirs the internal bypasser writes to.
RUN mkdir -p /config /data /downloads/incoming /downloads/ready \
             /data/shelfmark/log_root/shelfmark \
             /data/shelfmark/config \
             /data/shelfmark/tmp \
             /data/shelfmark/ingest \
             /tmp/shelfmark/seleniumbase/downloaded_files \
    && chown -R grabarr:grabarr /config /data /downloads /tmp/shelfmark \
    # SeleniumBase's cdp_driver writes a 'downloaded_files' dir in cwd by
    # default; our WORKDIR is /opt/grabarr which is chown'd to 'grabarr'
    # but when docker-compose sets user: 1000:1000 (so ./data/* files are
    # owned by the host user) that uid can't write here. Make the whole
    # workdir world-writable with sticky bit — only affects files created
    # at runtime, not the venv/code which stay read-only.
    && chmod 1777 /opt/grabarr

USER grabarr

EXPOSE 8080 45000-45100/tcp 45000-45100/udp

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8080/healthz || exit 1

CMD ["uvicorn", "grabarr.api.app:app", "--host", "0.0.0.0", "--port", "8080"]
