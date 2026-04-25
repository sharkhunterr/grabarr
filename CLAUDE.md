# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

Grabarr is a multi-source media indexer + download bridge that exposes
shadow libraries (Anna's Archive, LibGen, Z-Library, Internet Archive)
as standard **Torznab** indexers consumable by Prowlarr and the *arr
apps (Bookshelf, Readarr, Mylar3). It downloads HTTP files and generates
seedable `.torrent` files on the fly so any BitTorrent client (Deluge,
qBittorrent, Transmission, rTorrent) can consume them transparently.

Python 3.12+, FastAPI (async), SQLAlchemy 2.0 async, Alembic, libtorrent,
Tailwind via CDN/standalone CLI. `uv` is the package manager.

## Heritage: vendored Shelfmark

The AA / LibGen / Z-Library cascade is **not** original Grabarr code —
it is a verbatim vendor of [Shelfmark](https://github.com/calibrain/calibre-web-automated-book-downloader)
v1.2.1 (commit `019d36b27e3e8576eb4a4d6d76090ee442a05a44`, MIT) under
[grabarr/vendor/shelfmark/](grabarr/vendor/shelfmark/). Per Constitution
Articles III + VII, **only two changes** are allowed in that tree:

1. Import-path rewrites (`shelfmark.X` → `grabarr.vendor.shelfmark.X`).
2. Routing `core.config` + `core.logger` through
   [_grabarr_adapter.py](grabarr/vendor/shelfmark/_grabarr_adapter.py),
   which proxies onto Grabarr's own `core.config` / `core.logging`.

No business-logic patches in `vendor/`. Bug found inside the cascade?
Fix upstream and re-vendor with `make vendor-shelfmark`. The Internet
Archive adapter ([grabarr/adapters/internet_archive.py](grabarr/adapters/internet_archive.py))
is the only adapter that is Grabarr-native end-to-end.

The Shelfmark→Grabarr config bridge lives in `_SettingsBackend` inside
[grabarr/api/app.py](grabarr/api/app.py). It translates Shelfmark's
upstream env-style keys (`EXT_BYPASSER_URL`, `AA_DONATOR_KEY`, `CUSTOM_DNS`,
`USE_DOH`, `AA_BASE_URL`, `AA_MIRROR_URLS`, …) into Grabarr's namespaced
settings keys. When a vendored module reads the wrong value, look here
first before suspecting Shelfmark.

## Starting and stopping the server

**Always go through the wrapper scripts** — never `uv run uvicorn …`
directly. The wrappers do three things raw uvicorn does not:

1. Export `LOG_ROOT` / `CONFIG_DIR` / `TMP_DIR` / `INGEST_DIR` into
   `./data/shelfmark/*` so the vendored code (which hardcodes
   `/var/log/shelfmark` + `/config`) doesn't crash trying to write
   under `/var`.
2. Always invoke `./stop.sh` first, killing any stale uvicorn parent +
   reloader + child + anything bound to port 8080. Without this you end
   up with multiple instances fighting over the SQLite DB.
3. Wait on `/healthz` and surface boot-failure tails from the log.

### Local terminal launch

```bash
./start.sh                 # background, writes .grabarr.pid, waits for /healthz
./start.sh --foreground    # attached, Ctrl-C to stop (./run.sh is an alias)
./stop.sh                  # idempotent; safe even when nothing is running
HOST=127.0.0.1 ./start.sh  # bind local-only
RELOAD=0 ./start.sh        # disable hot reload
FLARESOLVERR_URL=host:port ./start.sh   # wire an external bypasser
```

The FastAPI lifespan also runs a **zombie sweeper** on boot that flips
any download stuck in `resolving / downloading / verifying / ready` to
`failed` (interrupted by restart). That sweep is what makes Ctrl-C →
restart cycles safe; it only fires through the lifespan, so the
wrapper-based stop+start sequence is the supported recovery path.

### Docker (the most reliable path on networks that block CF mirrors)

The image bundles Chromium + Xvfb + ffmpeg so `bypass.mode=internal`
(SeleniumBase cdp_driver) works out of the box — no FlareSolverr
sidecar needed. This is the recommended path when the host network
poisons mirror DNS or lacks a working browser.

```bash
docker compose up -d --build
docker compose logs -f grabarr
docker compose restart grabarr
docker compose down
```

Compose ships `shm_size: 2gb` (Chromium dies on Docker's default 64 MB),
runs as `${UID}:${GID}` so files in `./data` / `./downloads` stay
host-owned, and forces public DNS (1.1.1.1, 8.8.8.8) to bypass any
host Pi-hole/AdGuard that poisons libgen/annas-archive lookups.

### Network helpers

- [install-deps.sh](install-deps.sh) — one-shot `apt install chromium
  xvfb ffmpeg` for local `bypass.mode=internal`. Idempotent. Re-run
  with sudo.
- [use-public-dns.sh](use-public-dns.sh) — drops a systemd-resolved
  drop-in routing every host lookup through Cloudflare/Google/Quad9.
  `--restore` undoes it. Use only when Pi-hole/router DNS is poisoning
  mirror hostnames *and* you can't move to Docker.
- [reset-downloads.sh](reset-downloads.sh) — wipes `downloads /
  torrents / search_tokens / search_cache` rows + on-disk staging.
  Profiles, settings, credentials, API keys are preserved. `--yes` to
  skip the confirm prompt.

## Common dev commands

`Makefile` is the source of truth — `make help` lists every target.
Highlights:

```bash
make test              # pytest -q (full suite)
make test-unit         # tests/unit only
make test-integration  # tests/integration only
make test-vendor-compat  # FR-040 vendored-Shelfmark import sanity (tests/vendor_compat)
make lint              # ruff check + ruff format --check + mypy --strict
make format            # ruff format + ruff check --fix (auto-fix)
make tailwind-build    # download + compile Tailwind once (production CSS)
make tailwind-watch    # rebuild Tailwind on change (dev)
make vendor-shelfmark  # re-pull Shelfmark + re-vendor (only way to update vendor/)
```

Single test: `uv run pytest tests/unit/test_torrent_modes.py::test_active_seed_dispatch -q`.
Skip the slow ones: `uv run pytest -m "not slow" -q`. Browser tests are
gated behind `requires_browser` and skipped by default.

`pyproject.toml` configures ruff (line 100, py312, security + async lint
on, `vendor/` excluded), mypy (`--strict`, `vendor/` excluded), and
pytest (`asyncio_mode=auto`, warnings-as-errors).

## Architecture (big picture)

```
grabarr/
├── api/             FastAPI: app.py (lifespan), torznab.py, admin.py, health.py, metrics.py
├── adapters/        Per-source adapter; base.py defines the contract; health.py runs the circuit breaker
├── profiles/        orchestrator.py is the search aggregator (first_match | aggregate_all, dedup, weights, timeouts, filters, member-required-skip)
├── downloads/       service.py + manager.py + sync.py / async_streaming.py / hybrid.py dispatch
├── torrents/        active_seed.py (libtorrent), webseed.py (BEP-19 + url-list), tracker.py, server.py
├── bypass/          service.py — facade over external (FlareSolverr) | internal (SeleniumBase) | auto | off
├── core/            config.py, logging.py, settings_service.py (cache), models.py, registry.py
├── db/              SQLAlchemy models + Alembic migrations (run in subprocess on lifespan startup)
├── notifications/   Apprise + generic webhook with Jinja2 body, flap-suppression
├── web/             Jinja templates + static (Tailwind CSS, htmx, sortable, chart.js)
└── vendor/shelfmark/  Verbatim Shelfmark v1.2.1 — DO NOT EDIT (see Heritage above)
```

Boot sequence (lifespan in [grabarr/api/app.py](grabarr/api/app.py)):

1. Redirect Shelfmark's hardcoded paths (`LOG_ROOT` etc.) into `./data/shelfmark/`.
2. `load_settings()` → `pydantic-settings` (env > config.yaml > defaults).
3. Configure root logger (level + format + on-disk rotation).
4. Run pending Alembic migrations in a subprocess (Alembic's env.py
   uses `asyncio.run()`, can't nest in our loop).
5. Seed default profiles if `profiles` table is empty (7 profiles).
6. Warm `settings_service` cache, then `install_shelfmark_bridge(_SettingsBackend())`.
7. Zombie sweeper: any `Download` stuck in flight → `failed`.
8. Start adapter health monitor (60 s) + cleanup sweeper.

Shutdown: stop monitor + sweeper, persist libtorrent session state, dispose engine.

Search request flow: HTTP `/torznab/{slug}/api?t=search&q=…` → torznab
router → `Profile` lookup → `Orchestrator.search()` (parallel adapter
calls with timeouts/weights/filters, dedup, round-robin interleave) →
results converted to Torznab XML with stable per-item pseudo-info-hashes
(so Prowlarr doesn't drop them).

Download request flow: Prowlarr GETs `/download/{token}.torrent` → token
maps to a `Download` row → resolve via the source adapter (cascade if
AA) → fetch via `sync` / `async_streaming` / `hybrid` mode → verify
magic bytes → generate `.torrent` (`active_seed` adds to libtorrent
session and serves on 45000-45100; `webseed` writes a BEP-19 torrent
with `url-list` pointing back to `/seed/{token}`) → return `.torrent`
bytes with `X-Grabarr-Torrent-Mode` header.

Settings live in two places: **boot-time only** keys (`server.host`,
`server.port`, paths, source credentials, `master_secret`) come from
`config.yaml` / env via `pydantic-settings`. **UI-mutable** keys live
in the `settings` SQLite table behind `settings_service` with a sync
cache (`get_sync` is what the Shelfmark bridge calls). `config.yaml ::
initial_settings` only seeds the table on the very first boot.

## Things that look weird but are intentional

- **`vendor/` not under `.venv/`** — Shelfmark is checked in, not `pip
  install`-ed. That is the constitution. See `vendor/shelfmark/ATTRIBUTION.md`.
- **Alembic runs in a subprocess at boot** — its `env.py` calls
  `asyncio.run()` at import time which can't nest in our loop.
- **`master_secret` auto-generated to `{data_dir}/.fernet_key` on first
  boot if blank** — used to encrypt Apprise URLs at rest.
- **Two torrent modes** (`active_seed` libtorrent vs `webseed` pure
  Python BEP-19) are both first-class per Constitution Article IX. Pick
  per-profile.
- **Three download modes** (`sync` / `async_streaming` / `hybrid`) are
  Constitution Article X. Default `sync`; `hybrid` HEAD-probes
  `Content-Length` and switches at the 50 MiB threshold.
- **`config.example.yaml` is the full reference**; `config.yaml` is
  auto-created by `start.sh` with only credentials + a few defaults
  (this file is gitignored).
- **`LICENSE` is GPL-3.0-or-later for original code; MIT for `vendor/`.**

## Where the docs live

- [README.md](README.md) — short overview + licensing + non-goals.
- [CHANGELOG.md](CHANGELOG.md) — v1.0.0 release notes (sources, core, UI, deployment, tests).
- [docs/configuration.md](docs/configuration.md) — every settings key with default + override path.
- [docs/troubleshooting.md](docs/troubleshooting.md) — "symptom → cause → fix" for the common operator issues (Prowlarr indexer test failures, AA timeouts, Z-Library empty results, Deluge not seeding, libtorrent ImportError, etc.).
- [docs/DEVELOPING_ADAPTERS.md](docs/DEVELOPING_ADAPTERS.md) — adding a new source adapter.
- [feature_requests.md](feature_requests.md) — v1.1+ deferred work, tagged with original task IDs.
- [.specify/memory/constitution.md](.specify/memory/constitution.md) — 16 articles + governance. Articles I (transparent *arr), II (no auth), III + VII (vendor sacred), IX (dual torrent), X (triple download), XI (file integrity), XII (rate limits), XIII (no secrets in logs) are the load-bearing ones.
- [specs/001-grabarr-core-platform/](specs/001-grabarr-core-platform/) — full v1.0 spec, plan, data model, contracts, quickstart, 177-task breakdown.
