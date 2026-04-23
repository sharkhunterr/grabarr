# Changelog

## v1.0.0 — 2026-04-23

First release. Multi-source media indexer + download bridge for the
*arr ecosystem.

### Sources

- Anna's Archive (vendored Shelfmark cascade)
- LibGen (vendored cascade)
- Z-Library (vendored cascade + Grabarr-native quota & cookie-expired
  detection)
- Internet Archive (Grabarr-native with per-MediaType file-preference
  ladders)

### Core

- Torznab endpoint per profile with API-key auth, caps, search,
  book/movie/music, `/download/{token}.torrent`, `/seed/{token}`
  webseed server with HTTP Range, `/announce` tracker stub.
- Orchestrator with `first_match` + `aggregate_all` modes, per-entry
  weights + timeouts + filters + member-required-skip.
- 7 default profiles seeded on first boot; full CRUD via UI + API.
- Download modes: `sync` (default), `async_streaming`, `hybrid`.
- Torrent modes: `active_seed` (libtorrent, default) + `webseed`
  (BEP-19, pure Python).
- Bypass service: `external` (FlareSolverr sidecar, default),
  `internal` (SeleniumBase optional extra), `auto`.
- Adapter health monitor with 5-failure circuit breaker (60 s recheck).
- Notifications: Apprise + generic webhook with Jinja2 body template,
  flap-suppression (10 min cooldown per event; until-midnight for
  quota_exhausted).
- Background cleanup sweeper (5-min cadence): expired torrents,
  30-day downloads history, bypass session cache, search cache,
  notifications log, tracker peers.
- Prometheus metrics at `/metrics` (>50 series possible under load).
- Per-subsystem `/healthz` report.

### UI

- Dashboard, Profiles list + edit (drag-and-drop source ordering
  with Sortable.js, per-source weight + timeout + enable toggle,
  inline Run Test via HTMX), Sources (health status + quota panel +
  Test Now), Notifications (Apprise CRUD + dispatch log).
- Tailwind via CDN (Play mode) for the MVP; Docker build compiles
  the standalone Tailwind CLI for production.
- Dark/light theme toggle persisted in localStorage.
- Responsive down to 360 px.

### Deployment

- `python:3.12-slim` Docker image (builder + runtime stages) with
  libtorrent compiled from source against the target Python.
- `docker-compose.example.yml` wires Grabarr + FlareSolverr v3 +
  published port range 45000–45100 for `active_seed`.
- Alembic migrations run in-process on startup via subprocess.

### Tests

- 52 passing (1 skipped — SeleniumBase optional extra).
  - Vendor-compat: 25 tests proving the Shelfmark cascade imports
    correctly after import-path rewriting.
  - Unit: torrent-mode dispatcher (webseed + active_seed), download-
    mode dispatcher (sync + async_streaming + hybrid).
  - Integration: US1 MVP end-to-end, US3 profile CRUD,
    US4 health + notifications, US5 registry discovery, metrics +
    cleanup.

### Vendored code

`grabarr/vendor/shelfmark/` — 116 files from
`calibre-web-automated-book-downloader` v1.2.1
(commit `019d36b27e3e8576eb4a4d6d76090ee442a05a44`, MIT licensed).
Only change is import-path rewriting + a single bridging adapter
(`_grabarr_adapter.py`) per Constitution Article III.
