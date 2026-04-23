# Implementation Plan: Grabarr Core Platform — Full Release (v1.0)

**Branch**: `001-grabarr-core-platform` | **Date**: 2026-04-23 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-grabarr-core-platform/spec.md`

## Summary

Grabarr is a multi-source media indexer and download bridge that exposes shadow
libraries (Anna's Archive, LibGen, Z-Library, Internet Archive) as standard
Torznab endpoints consumable by Prowlarr and the downstream *arr ecosystem
(Bookshelf, Readarr, Mylar3, etc.). It downloads HTTP files and generates
seedable `.torrent` files on the fly so that any standard BitTorrent client
(Deluge, qBittorrent, Transmission, rTorrent) can consume them transparently.

**Technical approach**: ~60% of the codebase is vendored verbatim from
Shelfmark (`calibre-web-automated-book-downloader`, MIT) — its AA/LibGen/Z-Lib
cascade, bypass module, and mirror logic are untouched except for import
rewrites to `grabarr.vendor.shelfmark.*`. The remaining ~40% is Grabarr-
specific code that wraps vendored modules behind a `SourceAdapter` protocol,
plus Grabarr-native subsystems (Internet Archive adapter, profile + routing
engine, Torznab endpoint, dual-mode torrent generator, triple-mode download
manager, admin UI, observability, notifications). FlareSolverr runs as a
Docker sidecar. All state persists to SQLite + local filesystem.

## Technical Context

**Language/Version**: Python 3.12+
**Primary Dependencies**: FastAPI (async), SQLAlchemy 2.0 async, Alembic,
`libtorrent` 2.0+, `httpx`, `BeautifulSoup4` + `lxml`, `pydantic-settings`,
`apscheduler`, `async-lru`, `apprise`, `prometheus-client`, Jinja2 + HTMX +
Tailwind CSS (CLI build). For vendored code: `seleniumbase` (internal bypasser,
optional), `cryptography`, and whatever transitive deps Shelfmark already
requires.
**Storage**: SQLite (via SQLAlchemy async); local filesystem for
`/downloads/incoming/`, `/downloads/ready/`, and `/data/` (libtorrent session,
bypass-session cache, quota counters, download history). No external RDBMS.
**Testing**: `pytest` + `pytest-asyncio` + `respx` (HTTP mocks). A dedicated
`tests/vendor_compat/` suite mocks the vendored Shelfmark modules to guarantee
adaptation-layer fidelity.
**Target Platform**: Linux x86_64 (Docker). Python 3.12+ inside a
`python:3.12-slim` base image. Browser deps for the SeleniumBase bypasser are
installed but the bypasser is disabled by default.
**Project Type**: web service + embedded web UI (single FastAPI app that
serves both machine-facing Torznab/HTTP surfaces and human-facing admin UI;
no separate frontend build tool other than the Tailwind CLI).
**Performance Goals**: search p95 < 2 s for Internet Archive, < 5 s for Anna's
Archive with cached Cloudflare clearance, < 30 s for first-time AA bypass;
async-streaming download returns the torrent in < 500 ms; sync mode validation
overhead < 500 ms; UI TTFB < 500 ms on localhost, < 1.5 s on LAN; `/metrics`
exposes > 50 distinct Prometheus series.
**Constraints**: single-tenant, no in-app auth (Constitution Article II);
~60% vendored code (Article III); AA cascade preserved verbatim (Article VII);
vendored bypass module unchanged (Article VIII); all three download modes and
both torrent modes fully implemented (Articles IX–X); every secret redacted
from logs (Article XIII); Docker-first deployment with FlareSolverr sidecar.
**Scale/Scope**: 50 concurrent searches, 10 concurrent downloads, 100 active
seeds, 30-day downloads-history retention, database size < 500 MB for a year
of history, ~40 functional requirements, 7 seeded default profiles, 4 source
adapters, 7 admin UI views, 7 notification event types.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

This plan is evaluated against each article of `.specify/memory/constitution.md`
v1.0.0. All sixteen articles gate merge; unjustified violations block
progress.

| Article | Gate | Status | Notes |
|---------|------|--------|-------|
| I — Transparent *arr Integration | All *arr-facing surfaces use standard Torznab; no custom *arr client plugin. | ✅ | Torznab endpoint is the sole *arr-facing contract; `.torrent` is consumed by the *arr's existing download client. |
| II — No Authentication | No login screen, no user model; proxy handles edge auth. | ✅ | FR-033 locks this; only per-profile API key on `/torznab/{slug}/api` remains (expected by the Torznab contract). |
| III — Reuse Over Reimplementation | AA/LibGen/Z-Lib logic comes from `grabarr/vendor/shelfmark/`. | ✅ | Adapters in `grabarr/adapters/` are wrappers; vendoring procedure encoded in Phase 0 research. |
| IV — Adapter-Based Extensibility | Adapter registry auto-discovers via `@register_adapter`. | ✅ | FR-007 + the `SourceAdapter` protocol in `grabarr/adapters/base.py`. |
| V — Media Type Agnostic | `MediaType` enum declared; adapters opt in to types. | ✅ | Enum listed in research.md; default profiles cover all v1.0 types. |
| VI — Profile-First Design | Profiles drive Torznab endpoint per slug; full CRUD in UI. | ✅ | FR-011, FR-012, FR-013, FR-025. |
| VII — Shelfmark's Cascade Is Sacred | AA cascade preserved verbatim through vendored `direct_download.py`. | ✅ | FR-002, FR-004 — every sub-source, threshold, extraction strategy, countdown behaviour routed through the vendored module. |
| VIII — Bypass Reuses Shelfmark Verbatim | `grabarr/vendor/shelfmark/bypass/` is a 1:1 port. | ✅ | FR-009 wraps the vendored module; only imports adjusted. |
| IX — Dual Torrent Generation Strategy | Both `active_seed` and `webseed` fully implemented. | ✅ | FR-022, FR-023, FR-024. |
| X — Triple Download Strategy | All three of `sync` / `async_streaming` / `hybrid` shipped. | ✅ | FR-017 — clarification locks default to `sync`. |
| XI — File Integrity Is Sacred | Magic-byte, size, Content-Type checks applied pre-handoff. | ✅ | FR-020 + per-format byte signatures from Constitution Article XI. |
| XII — Rate Limit Everything | Token buckets per adapter with documented defaults. | ✅ | FR-035. |
| XIII — No Secrets In Code Or Logs | Redaction filter on every logger; secrets in `config.yaml`/env only. | ✅ | FR-034, FR-029. |
| XIV — Observability Built-In | `/metrics` (> 50 series), `/healthz`, structured logs. | ✅ | FR-028, FR-029, FR-030; SC-010 gates the series count. |
| XV — Notifications Are First-Class | Apprise + generic webhook; full event catalogue. | ✅ | FR-031 + FR-031a (flap suppression) + FR-032. |
| XVI — Admin UI Is Production-Grade | Responsive 360 px–4K, WCAG AA, keyboard, light/dark. | ✅ | FR-025, FR-026. |

**Result**: all gates pass. No complexity-tracking entries required.

## Project Structure

### Documentation (this feature)

```text
specs/001-grabarr-core-platform/
├── plan.md              # This file (/speckit.plan command output)
├── spec.md              # Feature specification (/speckit.specify)
├── research.md          # Phase 0 output (technology + vendoring decisions)
├── data-model.md        # Phase 1 output (entities + state transitions)
├── quickstart.md        # Phase 1 output (dev loop + acceptance demos)
├── contracts/           # Phase 1 output
│   ├── torznab-xml.md           # Torznab caps + search response schemas
│   ├── source-adapter.py        # Grabarr SourceAdapter protocol (source of truth)
│   ├── admin-api.md             # /api/* REST surface
│   └── prowlarr-export.json     # Sample JSON for Generic Torznab import
├── checklists/
│   └── requirements.md  # Spec quality checklist (from /speckit.specify)
└── tasks.md             # Phase 2 output (/speckit.tasks, NOT created here)
```

### Source Code (repository root)

The project layout is mandated by Constitution §"Project Layout". This plan
reproduces that structure and refines file-level detail where the spec
constrains it further.

```text
grabarr/
├── vendor/
│   └── shelfmark/                # Direct port of Shelfmark v1.2.1 (Article III)
│       ├── ATTRIBUTION.md        # MIT license + upstream commit SHA
│       ├── __init__.py           # Imports _grabarr_adapter eagerly
│       ├── _grabarr_adapter.py   # Bridges Shelfmark's config/logger (hand-authored)
│       ├── bypass/               # 4 files (FlareSolverr, SeleniumBase, fingerprint)
│       ├── config/               # 8 files (env, settings, migrations, security, ...)
│       ├── core/                 # 15 files (mirrors, naming, models, utils, queue,
│       │                           search_plan, cache, request_*, settings_registry,
│       │                           user_db, auth_modes, image_cache, activity_view_state_service)
│       ├── download/             # 10 files (network, fs, staging, permissions_debug,
│       │                           outputs/{booklore,email}, postprocess/pipeline, ...)
│       ├── metadata_providers/   # 1 file (__init__.py - type registry)
│       └── release_sources/      # 2 files (__init__.py type registry,
│                                   direct_download.py AA/LibGen/Z-Lib cascade)
│  # Total: 41 verbatim files + 1 hand-authored adapter + 1 __init__.py = 43 .py files
│
├── adapters/                     # SourceAdapter wrappers (Article IV)
│   ├── __init__.py               # Registry + @register_adapter auto-discovery
│   ├── base.py                   # SourceAdapter Protocol + shared dataclasses
│   ├── anna_archive.py           # Wrapper over vendored AA cascade
│   ├── libgen.py                 # Wrapper over vendored LibGen paths
│   ├── zlibrary.py               # Wrapper + Grabarr-specific quota/cookie logic
│   └── internet_archive.py       # NEW — Grabarr-native, not vendored
│
├── bypass/                       # Service layer over vendored bypass
│   ├── __init__.py
│   ├── service.py                # Mode selection + session cache
│   └── cache.py                  # Persisted cf_clearance cache
│
├── core/                         # Registry + enums + shared models + config
│   ├── __init__.py
│   ├── config.py                 # pydantic-settings YAML loader
│   ├── enums.py                  # MediaType, DownloadMode, TorrentMode, etc.
│   ├── logging.py                # Structured logger + secret redaction filter
│   ├── models.py                 # SearchResult, DownloadInfo, HealthStatus, ...
│   ├── rate_limit.py             # Token bucket (Article XII)
│   └── registry.py               # Adapter registry
│
├── profiles/                     # Profile CRUD + orchestration
│   ├── __init__.py
│   ├── defaults.py               # 7 seeded default profiles
│   ├── models.py                 # Profile SQLAlchemy model
│   ├── orchestrator.py           # Search orchestrator (FR-013)
│   └── service.py                # CRUD service + cache invalidation
│
├── downloads/                    # DownloadManager (Article X)
│   ├── __init__.py
│   ├── manager.py                # Dispatch by mode
│   ├── sync.py                   # Sync strategy
│   ├── async_streaming.py        # Async-streaming strategy
│   ├── hybrid.py                 # Hybrid strategy
│   ├── verification.py           # Magic-byte + Content-Type + size checks
│   ├── post_processors.py        # ZIP/7Z/RAR extractors, M3U builder
│   └── cleanup.py                # Seed-retention window expiry task (FR-039a)
│
├── torrents/                     # TorrentServer (Article IX)
│   ├── __init__.py
│   ├── server.py                 # Mode dispatcher + lifecycle
│   ├── active_seed.py            # libtorrent session
│   ├── webseed.py                # BEP-19 torrent generation
│   ├── tracker.py                # Internal HTTP tracker (SQLite peer store)
│   └── state.py                  # Persistence across restart
│
├── api/                          # FastAPI routes
│   ├── __init__.py
│   ├── app.py                    # FastAPI factory + lifespan
│   ├── torznab.py                # /torznab/{slug}/api, /download, /seed
│   ├── admin.py                  # /api/profiles, /api/sources, /api/settings...
│   ├── health.py                 # /healthz
│   └── metrics.py                # /metrics (prometheus-client)
│
├── web/                          # Jinja2 + Tailwind + HTMX admin UI
│   ├── __init__.py
│   ├── routes.py                 # HTML-rendering routes
│   ├── templates/
│   │   ├── _base.html            # Layout, theme toggle, nav
│   │   ├── dashboard.html        # /
│   │   ├── profiles/             # list.html, edit.html, form fragments
│   │   ├── sources.html          # /sources
│   │   ├── settings/             # bypass.html, downloads.html, torrents.html, paths.html, metadata.html, backup.html
│   │   ├── downloads.html        # /downloads
│   │   ├── notifications.html    # /notifications
│   │   ├── stats.html            # /stats
│   │   └── partials/             # HTMX fragments for polling + forms
│   └── static/
│       ├── css/
│       │   ├── tailwind.input.css
│       │   └── tailwind.build.css  # Generated by Tailwind CLI
│       └── js/
│           ├── htmx.min.js
│           ├── sortable.min.js
│           └── chart.umd.min.js
│
├── notifications/                # Apprise + webhook (Article XV)
│   ├── __init__.py
│   ├── dispatcher.py             # Fire-and-forget + retry + flap suppression
│   ├── apprise_backend.py
│   └── webhook_backend.py
│
├── db/                           # SQLAlchemy + Alembic
│   ├── __init__.py
│   ├── base.py                   # Declarative base, async session
│   ├── session.py                # Async sessionmaker
│   └── migrations/               # Alembic env.py + versions/
│
├── cli/                          # Management commands
│   ├── __init__.py
│   ├── main.py                   # Entry point (uvicorn + migration runner)
│   ├── vendor_refresh.py         # Re-pull Shelfmark, re-apply import fixups
│   └── seed_defaults.py          # Re-seed default profiles
│
├── pyproject.toml                # uv + deps
├── uv.lock
├── Dockerfile
├── docker-compose.example.yml
├── config.example.yaml
├── alembic.ini
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── unit/                     # Per-module unit tests
    ├── integration/              # Full-stack tests via httpx + respx
    └── vendor_compat/            # Verifies vendored modules post-adaptation (FR-040)
        ├── test_external_bypasser.py
        ├── test_internal_bypasser.py
        ├── test_fingerprint.py
        ├── test_mirrors.py
        ├── test_naming.py
        ├── test_direct_download_aa.py
        ├── test_direct_download_libgen.py
        └── test_direct_download_zlib.py
```

**Structure Decision**: The constitution mandates this exact layout; no
alternative was considered. The repo is a single Python package `grabarr/`
with test and deployment artefacts at the root. There is no separate frontend
tree because the UI is server-rendered Jinja2 + HTMX (Constitution §Technology
Stack): the only "frontend build step" is `tailwind --input web/static/css/
tailwind.input.css --output web/static/css/tailwind.build.css --minify`, which
runs as a Dockerfile layer.

## Complexity Tracking

No violations — every article of the constitution is satisfied by the
specification and the proposed structure without deviation. No rows required.
