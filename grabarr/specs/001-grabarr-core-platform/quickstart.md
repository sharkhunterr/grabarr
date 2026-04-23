# Quickstart — Grabarr Core Platform v1.0

This is the executable recipe for three audiences:

1. **First-time operator** who just wants Grabarr working in a homelab.
2. **Developer** who wants to run Grabarr from source, make a change, and
   see it work.
3. **Reviewer / QA** walking through the acceptance scenarios from the spec
   to verify SC-001 through SC-014.

---

## 1. Operator — `docker-compose up` to a working indexer in under 3 minutes

**Prerequisites**: Docker 24+, Docker Compose v2, outbound HTTPS to
archive.org, annas-archive.org, libgen.rs (or the current LibGen mirror),
and z-library.sk.

```bash
git clone https://github.com/{owner}/grabarr.git
cd grabarr
cp config.example.yaml config.yaml
docker compose -f docker-compose.example.yml up -d
```

Wait ~60 s for first-run setup (libtorrent session init, Alembic migrations,
default-profile seeding), then:

```bash
xdg-open http://localhost:8080         # Linux
open http://localhost:8080             # macOS
start http://localhost:8080            # Windows
```

The Dashboard shows seven seeded profiles under `/profiles`. For each, the
"Copy Prowlarr Config" button downloads a JSON blob. In Prowlarr, go to
`Indexers → Add Indexer → Generic Torznab`, paste the blob's fields, save.
Prowlarr's "Test" button should succeed on the first attempt.

Verifies: **SC-001, SC-002**.

---

## 2. Developer — run from source with hot-reload

**Prerequisites**: Python 3.12+, `uv`, Docker (for the FlareSolverr sidecar),
and the standalone Tailwind binary (downloaded on first `make dev`).

```bash
git clone https://github.com/{owner}/grabarr.git
cd grabarr
uv sync                                # installs runtime + dev deps

# Vendor Shelfmark (first time only — see R-1 in research.md)
make vendor-shelfmark

# Apply migrations + seed default profiles
uv run alembic upgrade head
uv run python -m grabarr.cli.seed_defaults

# Run FlareSolverr as a sidecar
docker run -d --name flaresolverr \
  -p 8191:8191 \
  ghcr.io/flaresolverr/flaresolverr:3

# Start Grabarr with auto-reload
uv run uvicorn grabarr.api.app:app \
    --host 0.0.0.0 --port 8080 \
    --reload

# In a second terminal: recompile Tailwind on change
./tailwindcss \
    --input grabarr/web/static/css/tailwind.input.css \
    --output grabarr/web/static/css/tailwind.build.css \
    --watch
```

Open `http://localhost:8080`. Edits to `grabarr/**.py` trigger Uvicorn
reload; edits to `grabarr/web/templates/**.html` are picked up on the next
request (Jinja2 in dev mode); edits to Tailwind classes compile in the
watcher.

### Dev-mode toggles

- `GRABARR_ENV=dev` — more verbose logs, disable the secret-redaction
  filter for named debug loggers (still applies to every other logger).
- `LOG_FORMAT=json` — switch from coloured text to structured JSON.
- `GRABARR_SEED_STATE_DIR=/tmp/grabarr-seeds` — keep the libtorrent session
  state out of your home dir during experimentation.

### Test loop

```bash
uv run pytest tests/unit -q                       # fast
uv run pytest tests/integration -q                # medium
uv run pytest tests/vendor_compat -q              # vendored-module regression
uv run pytest -q                                  # everything

uv run ruff check grabarr/ tests/
uv run ruff format --check grabarr/ tests/
uv run mypy grabarr/
```

---

## 3. Acceptance walk-through (reviewer / QA)

The acceptance scenarios in `spec.md` map to the clauses below.

### AC demo 1 — Public-domain ebook end-to-end (SC-003, User Story 1)

```bash
# In Bookshelf: add "The Time Machine" by H. G. Wells to the Wanted list
# Bookshelf uses the ebooks_public_domain profile (seeded)
# Observe:
curl -s "http://localhost:8080/api/downloads?page=1&size=5" | jq .

# The most recent row should be:
# {
#   "source_id": "internet_archive",
#   "status": "completed",
#   "timings_ms": { "total": 13800 },   # < 20 s ⇒ SC-003 pass
# }
```

### AC demo 2 — Large audiobook, async-streaming (SC-004, User Story 2)

```bash
# Edit the audiobooks_general profile in UI → set download_mode_override
# to async_streaming
# In Bookshelf: Wanted an audiobook known to be only on AA slow tier
# Expected: Deluge shows bytes flowing within 60 s of the grab event
# Logs:
docker logs grabarr 2>&1 | grep -E "async_streaming|piece_size"
```

### AC demo 3 — Custom profile via UI (User Story 3)

```bash
# In UI → Profiles → Duplicate "ebooks_general" → rename to "my_ebooks_fr"
# Drag Internet Archive to the top → set languages=["fr"] → Save
# Copy the new Torznab URL → add to Prowlarr
# Verify in Bookshelf that the new indexer appears
```

### AC demo 4 — FlareSolverr outage (User Story 4, SC-006)

```bash
docker stop flaresolverr

# Within 60 s:
curl -s http://localhost:8080/healthz | jq '.subsystems.adapters'
# Expect: anna_archive and zlibrary → "unhealthy"
# libgen and internet_archive → "healthy"

curl -s "http://localhost:8080/api/notifications/log?event=source_unhealthy" | jq '.items[0]'
# Expect a recent dispatch

docker start flaresolverr

# Within 60 s of FlareSolverr returning:
curl -s http://localhost:8080/healthz | jq '.subsystems.adapters'
# Expect: every adapter back to "healthy"
```

### AC demo 5 — 360 px viewport (SC-007)

Open the UI in Chrome DevTools → Device Toolbar → "iPhone SE (375 x 667)"
or manually 360 × 740. Navigate every page. No horizontal scroll. All CTA
buttons reachable. Theme toggle works. Keyboard nav: `Tab` through every
interactive element; `?` opens the shortcuts modal.

### AC demo 6 — Metrics & Grafana (SC-010)

```bash
curl -s http://localhost:8080/metrics | grep -E "^grabarr_" | wc -l
# Expect > 50

# Import grabarr/contrib/grafana-dashboard.json into Grafana.
# Every panel should populate within 30 s of a Prometheus scrape.
```

### AC demo 7 — Restart resilience (SC-009)

```bash
docker restart grabarr
# Wait 30 s

curl -s http://localhost:8080/api/profiles | jq '.total'
# Expect 7 (defaults) + any you added

curl -s http://localhost:8080/api/stats/overview | jq
# active_seeds should match pre-restart count
```

### AC demo 8 — Vendor compat suite (SC-011)

```bash
uv run pytest tests/vendor_compat -v
# Expect 100% pass
```

### AC demo 9 — Attribution (SC-013)

```bash
cat grabarr/vendor/shelfmark/ATTRIBUTION.md
head -5 grabarr/vendor/shelfmark/release_sources/direct_download.py
# Each vendored file starts with:
# """Vendored from calibre-web-automated-book-downloader, commit {SHA}, {date}.
#    Original file: shelfmark/release_sources/direct_download.py.
#    Licensed MIT, see ATTRIBUTION.md."""
```

### AC demo 10 — Notification flap suppression (FR-031a)

```bash
# Simulate a flapping source with an ops script that toggles
# an adapter's health every 15 s for 5 minutes.
# Expected: only one source_unhealthy + source_recovered pair per
# (source, event_type) in any given 10-minute window.
curl -s "http://localhost:8080/api/notifications/log?event=source_unhealthy" \
  | jq '[.items[] | select(.source_id == "anna_archive")] | length'
# Should be a small number (not 20).
# Coalesced entries are still logged with dispatch_status="suppressed".
```

---

## Common operator issues

| Symptom | Fix |
|---------|-----|
| Prowlarr test fails with "unable to connect" | `http://{host}:8080` — replace `{host}` with the actual address Prowlarr can reach (Docker bridge networking means `localhost` on Prowlarr's side is NOT the same as Grabarr's). |
| AA searches time out | Check `docker logs flaresolverr`; if FlareSolverr is up, check `/sources` page for bypass errors. Session cache clears automatically on 403/503 (per R-5). |
| Z-Library returns login page | `cookie_expired` is fired automatically. Update `remix_userid`/`remix_userkey` in Sources → Z-Library → Config. |
| Disk filling up | Check `settings.torrent.seed_retention_hours`. Default 24 h. Reduce for low-disk hosts (minimum 1 h). |
| libtorrent won't bind listen ports | Check that 45000–45100 TCP/UDP aren't in use; override range in Settings → Torrents. |

---

## Upgrading

```bash
docker compose pull
docker compose up -d
# Alembic migrations run automatically at startup (FR-038).
# Your settings table is preserved; credentials in config.yaml are re-read.
```

If you need to downgrade, see `docs/downgrade.md` (not shipped in v1.0 —
downgrades are not supported without a manual DB export/reimport).
