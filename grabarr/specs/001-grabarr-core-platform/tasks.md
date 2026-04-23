---
description: "Task list for Grabarr Core Platform v1.0"
---

# Tasks: Grabarr Core Platform — Full Release (v1.0)

**Input**: Design documents from `/specs/001-grabarr-core-platform/`
**Prerequisites**: plan.md ✓, spec.md ✓, research.md ✓, data-model.md ✓, contracts/ ✓, quickstart.md ✓

**Tests**: Spec FR-040 explicitly mandates `tests/vendor_compat/`, so the vendor-compat suite is **required**. Additional unit and integration tests are included because acceptance scenarios (SC-011, SC-012, SC-014) require a runnable pytest suite.

**Organization**: Tasks are grouped by user story. Each story is independently implementable and shippable.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Different file, no dependency on incomplete tasks — can run in parallel
- **[USn]**: Maps to User Story `n` from spec.md (P1=US1,US2; P2=US3,US4; P3=US5)
- Every task includes an exact file path

## Path Conventions

Single-project Python layout under the repository root; package is `grabarr/`, tests under `tests/`, deployment artefacts at the root. Paths match Constitution §"Project Layout" and plan.md §"Project Structure".

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Bootstrap the repo, dependency management, build tooling, and directory skeleton so that every later phase has somewhere to land code.

- [X] T001 Create `pyproject.toml` at repo root declaring the `grabarr` package, Python >= 3.12, and all runtime dependencies listed in `plan.md` §"Technical Context" (FastAPI, SQLAlchemy 2.0, Alembic, libtorrent, httpx, BeautifulSoup4+lxml, pydantic-settings, apscheduler, async-lru, apprise, prometheus-client, Jinja2, cryptography, uuid-utils, bcrypt, aiofiles) plus `[project.optional-dependencies]` groups `dev` (pytest, pytest-asyncio, respx, ruff, mypy) and `internal-bypasser` (seleniumbase).
- [X] T002 Run `uv lock` to generate `uv.lock` at repo root (binds versions listed in `pyproject.toml`).
- [X] T003 [P] Configure `ruff` and `mypy --strict` in `pyproject.toml` (`[tool.ruff]`, `[tool.ruff.lint]`, `[tool.mypy]` sections with per-package overrides so vendored code is exempt from lint/type checks).
- [X] T004 [P] Create `.gitignore` at repo root (standard Python + `/data/`, `/downloads/`, `/config.yaml`, `/grabarr/web/static/css/tailwind.build.css`, `*.session_state`, `.venv/`, `.pytest_cache/`).
- [X] T005 [P] Create `config.example.yaml` at repo root with every credential-shaped setting documented inline (AA member key, Z-Lib cookies, bypass.flaresolverr_url, IA contact email).
- [X] T006 [P] Create the full directory skeleton matching `plan.md` §"Project Structure" — every `grabarr/**` subdir ships a `__init__.py`, plus `tests/unit/`, `tests/integration/`, `tests/vendor_compat/`, `alembic.ini` placeholder.
- [X] T007 [P] Create `grabarr/web/static/css/tailwind.input.css` importing Tailwind's base/components/utilities and declaring component classes used by templates (`btn`, `card`, `badge`, `toast`, etc.).
- [X] T008 Create `Makefile` at repo root with targets `dev`, `test`, `lint`, `format`, `tailwind-build`, `tailwind-watch`, `vendor-shelfmark` (downloads the standalone Tailwind binary on first run).
- [X] T009 Create `alembic.ini` at repo root pointing at `grabarr/db/migrations/` with `sqlalchemy.url = sqlite+aiosqlite:///data/grabarr.db`.

**Checkpoint**: Repo has a working `uv sync`, `make lint`, and an empty but navigable package tree.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Vendor Shelfmark, wire core cross-cutting modules, build the database base layer, and run the vendor-compatibility tests. Nothing in Phase 3+ may start before this phase is complete — every adapter, orchestrator, and UI depends on these primitives.

**⚠️ CRITICAL**: No user-story phase may start until this phase is green.

### Vendoring (Constitution Articles III, VII, VIII)

- [X] T010 Create `grabarr/vendor/shelfmark/__init__.py` that eagerly imports `_grabarr_adapter` before anything else so vendored modules can resolve `config` and `setup_logger` at import time.
- [X] T011 Create `grabarr/vendor/shelfmark/ATTRIBUTION.md` with the full MIT license text, upstream repository URL (`https://github.com/calibrain/calibre-web-automated-book-downloader`), and a `COMMIT_SHA` placeholder the vendor-refresh script fills in.
- [X] T012 Vendor Shelfmark bypass module: copy `shelfmark/bypass/__init__.py`, `external_bypasser.py`, `internal_bypasser.py`, `fingerprint.py` verbatim into `grabarr/vendor/shelfmark/bypass/`, rewrite every `from shelfmark.X` import to `from grabarr.vendor.shelfmark.X`, prepend the mandatory header comment per research R-1.
- [X] T013 [P] Vendor Shelfmark core utilities: copy `shelfmark/core/mirrors.py` and `naming.py` into `grabarr/vendor/shelfmark/core/`, apply the same import rewrites + header, plus `core/__init__.py`.
- [X] T014 Vendor Shelfmark release source: copy `shelfmark/release_sources/direct_download.py` + `__init__.py` into `grabarr/vendor/shelfmark/release_sources/`, apply import rewrites + header. **Do not modify logic.**
- [X] T015 Create `grabarr/vendor/shelfmark/_grabarr_adapter.py` implementing `ShelfmarkConfigProxy` (exposing `.get(key, default)` over Grabarr's pydantic settings) and re-exporting `setup_logger` from `grabarr.core.logging`, per research R-1.
- [X] T016 Create `grabarr/cli/vendor_refresh.py` — script that re-pulls Shelfmark `main`, re-copies the eight vendored files, re-applies the import fixups, and updates `ATTRIBUTION.md` with the new commit SHA (documented but optional to run).

### Core modules

- [X] T017 [P] Create `grabarr/core/enums.py` with every enum from `data-model.md` §"Enums" (MediaType, DownloadMode, TorrentMode, BypassMode, ProfileMode, DownloadStatus, AdapterHealth, UnhealthyReason, NotificationEvent).
- [X] T018 [P] Create `grabarr/core/models.py` with every transient dataclass from `data-model.md` §"Derived / transient objects" (SearchResult, DownloadInfo, HealthStatus, QuotaStatus, ConfigField, ConfigSchema) plus `SearchFilters` and `SourcePriorityEntry`.
- [X] T019 [P] Create `grabarr/core/config.py` — a pydantic-settings class that loads `/config.yaml` with `YamlSettingsSource` and environment-variable override support; expose only boot-time/secret settings per research R-8.
- [X] T020 [P] Create `grabarr/core/logging.py` — structured logger factory with a `RedactionFilter` covering every known secret key (AA member key, Z-Lib cookies, Apprise URLs, API keys), text + JSON modes, correlation-ID context var, and `setup_logger(name)` for the vendor bridge.
- [X] T021 [P] Create `grabarr/core/rate_limit.py` — async token-bucket implementation keyed by `(adapter_id, kind)` with tokens-per-minute config.
- [X] T022 [P] Create `grabarr/core/categories.py` — Newznab category table (`NEWZNAB_CATEGORIES: dict[int, str]`) per research R-6, used by caps-response builder.
- [X] T023 Create `grabarr/core/registry.py` implementing `register_adapter` decorator and `get_registered_adapters()` function; adapter auto-discovery via `importlib` walking `grabarr.adapters.*` at startup.
- [X] T024 Create `grabarr/adapters/base.py` mirroring `contracts/source-adapter.py` exactly — `SourceAdapter` Protocol, all error classes (`AdapterError`, `AdapterConnectivityError`, `AdapterBypassError`, `AdapterAuthError`, `AdapterQuotaError`, `AdapterRateLimitError`, `AdapterServerError`, `AdapterNotFound`), and the `@register_adapter` re-export from `grabarr.core.registry`.
- [X] T025 Create `grabarr/adapters/__init__.py` — triggers registry auto-discovery when the package is imported.

### Database base + migrations

- [X] T026 [P] Create `grabarr/db/base.py` — `Base = declarative_base()`, UUIDv7 column type, TIMESTAMPTZ helper, `JSON` column alias.
- [X] T027 [P] Create `grabarr/db/session.py` — async engine factory, `async_sessionmaker`, `get_session()` FastAPI dependency, `AsyncSession` context manager.
- [X] T028 Create `grabarr/db/migrations/env.py` — Alembic async env wiring pointing at `grabarr.db.base:Base.metadata` and every ORM model's module.
- [X] T029 Create `grabarr/db/migrations/versions/20260423_1000_initial.py` — first Alembic migration creating every table per `data-model.md` (profiles, settings, downloads, torrents, tracker_peers, bypass_sessions, adapter_health, zlibrary_quota, notifications_log, apprise_urls, webhook_config, search_cache) with all indexes and CHECK constraints listed there.

### ORM models (one table per file, all parallel — different files, no interdependency)

- [X] T030 [P] Create `grabarr/profiles/models.py` — `Profile` ORM class with embedded JSON `sources` and `filters` columns, SQLAlchemy-level validators enforcing `data-model.md` invariants (slug regex, weight bounds, year/size ordering).
- [X] T031 [P] Create `grabarr/downloads/models.py` — `Download` ORM class with the full state-machine invariants as SQLAlchemy `CheckConstraint`s.
- [X] T032 [P] Create `grabarr/torrents/models.py` — `Torrent` and `TrackerPeer` ORM classes.
- [X] T033 [P] Create `grabarr/bypass/models.py` — `BypassSession` ORM class.
- [X] T034 [P] Create `grabarr/notifications/models.py` — `AppriseUrl`, `WebhookConfig`, `NotificationLog` ORM classes with `cryptography.fernet` wrapper for URL encryption.
- [X] T035 [P] Create `grabarr/core/settings_model.py` — `Settings` KV ORM class with a module-level allowlist of permissible keys.
- [X] T036 [P] Create `grabarr/adapters/health_model.py` — `AdapterHealth` ORM class.
- [X] T037 [P] Create `grabarr/adapters/zlibrary_quota_model.py` — `ZLibraryQuota` ORM class (singleton-per-day pattern).
- [X] T038 [P] Create `grabarr/profiles/search_cache_model.py` — `SearchCache` ORM class.

### Vendor-compatibility tests (FR-040 — required, gates foundation)

- [X] T039 [P] Create `tests/vendor_compat/__init__.py` and `tests/vendor_compat/conftest.py` with shared `respx_mock` fixture.
- [X] T040 [P] Create `tests/vendor_compat/test_external_bypasser.py` — mock FlareSolverr JSON protocol with respx, verify the vendored client calls `/v1` with `cmd=request.get`, parses the `solution` envelope, handles 4xx/5xx, and fires `AdapterBypassError` on protocol mismatch.
- [X] T041 [P] Create `tests/vendor_compat/test_internal_bypasser.py` — import the module, assert `SeleniumBase` import succeeds, skip all browser-launching tests on CI (`pytest.mark.skipif(os.getenv("CI") == "true")`).
- [X] T042 [P] Create `tests/vendor_compat/test_fingerprint.py` — run `randomize_screen_size()` 10000× and assert the output distribution matches the documented weight pool within ±2 %.
- [X] T043 [P] Create `tests/vendor_compat/test_mirrors.py` — mock DNS + HTTP, verify `AAMirrorSelector.next_mirror_or_rotate_dns()` round-robins correctly and falls back to DNS rotation after a full cycle.
- [X] T044 [P] Create `tests/vendor_compat/test_naming.py` — parametrized regression test: every known problematic filename (unicode, slashes, control chars, ridiculously long) round-trips through the sanitizer to a safe output.
- [X] T045 [P] Create `tests/vendor_compat/test_direct_download_aa.py` — respx-mocked AA HTML fixtures exercising: fast-path with member key, slow-path with countdown (live wait mocked via `monkeypatch`), failure threshold tripping sub-source skip, dynamic sub-source classification via `_url_source_types`.
- [X] T046 [P] Create `tests/vendor_compat/test_direct_download_libgen.py` — mocked LibGen mirror pages, verify multi-strategy URL extraction + fiction/nonfiction/scimag routing.
- [X] T047 [P] Create `tests/vendor_compat/test_direct_download_zlib.py` — mocked Z-Library pages including login-page regression fixture (for cookie-expired detection later in US4).

### FastAPI skeleton

- [X] T048 Create `grabarr/api/app.py` — FastAPI factory, `lifespan` context manager running: (1) Alembic migrations, (2) seed defaults if empty, (3) libtorrent session restore, (4) register bypass cache sweepers; shutdown: (1) libtorrent session save, (2) stop schedulers.
- [X] T049 Create `grabarr/api/health.py` — minimal `/healthz` returning `{"status": "ok"}` (expanded in US4 to list per-subsystem).
- [X] T050 Create `grabarr/cli/main.py` — module-level `app` object + `main()` entry that runs first-run setup (generate `config.yaml` from `config.example.yaml` if missing, apply migrations, seed defaults, start uvicorn).

### Default-profile seeding

- [X] T051 Create `grabarr/profiles/defaults.py` — definitions of all seven default profiles per `spec.md` §FR-012 (slug, name, sources, weights, filters, mode, Newznab categories).
- [X] T052 Create `grabarr/cli/seed_defaults.py` — idempotent seeder that inserts rows missing from `profiles` table and leaves existing rows untouched.

**Checkpoint**: Foundation is green. `uv run pytest tests/vendor_compat` passes at 100 %. `uv run uvicorn grabarr.api.app:app` boots and serves `/healthz` returning `{"status": "ok"}`.

---

## Phase 3: User Story 1 — Homelab Deployment and First-Run Indexing (Priority: P1) 🎯 MVP

**Goal**: Operator can `docker-compose up`, copy a Prowlarr config blob, and see Bookshelf satisfy a "wanted" ebook end-to-end — through sync downloads and active-seed torrents, with all seven profiles live.

**Independent Test**: Per `quickstart.md` §"AC demo 1" — public-domain ebook round-trip via `ebooks_public_domain` profile (IA source, no bypass) completes in < 20 s with zero manual UI clicks.

### Source adapters

- [X] T053 [US1] Create `grabarr/adapters/internet_archive.py` — shell file with `@register_adapter`, class definition, protocol-required attributes (`id="internet_archive"`, media types, `requires_cf_bypass=False`, `supports_member_key=False`).
- [X] T054 [US1] Extend `grabarr/adapters/internet_archive.py` — declare the `FILE_PREFERENCE_LADDERS: dict[MediaType, list[FilePreference]]` constant per research R-4 (9 ladders, ~40 rows).
- [X] T055 [US1] Extend `grabarr/adapters/internet_archive.py` — implement `search()` hitting `advancedsearch.php` with CDL filter appended, map the JSON response into `SearchResult` objects, apply user-agent with contact email.
- [X] T056 [US1] Extend `grabarr/adapters/internet_archive.py` — implement `get_download_info()` fetching `/metadata/{identifier}`, applying the ladder + blacklist, returning the best file URL.
- [X] T057 [US1] Extend `grabarr/adapters/internet_archive.py` — implement `health_check()` (probe `/services/search/v1/scrape?q=*&rows=1`), `get_config_schema()` (contact email field + collection filters), `get_quota_status()` returning `None`.
- [X] T058 [P] [US1] Create `grabarr/adapters/anna_archive.py` — thin wrapper class delegating `search()` and `get_download_info()` to the vendored `grabarr.vendor.shelfmark.release_sources.direct_download` module; translate `MediaType` to Shelfmark's `mediatype` filter; declare `supports_member_key=True`, `requires_cf_bypass=True`.
- [X] T059 [P] [US1] Create `grabarr/adapters/libgen.py` — thin wrapper delegating to vendored LibGen paths within `direct_download.py`; media types per spec FR-1.2.
- [X] T060 [P] [US1] Create `grabarr/adapters/zlibrary.py` — thin wrapper delegating to vendored Z-Lib paths; config schema exposes `remix_userid` + `remix_userkey` fields; quota + cookie-expired logic is deferred to US4.

### Bypass service

- [ ] T061 [US1] Create `grabarr/bypass/__init__.py` and `grabarr/bypass/service.py` — `BypassService` with mode dispatch (`external` default) delegating to the vendored `external_bypasser.py`; ignores `internal` and `auto` (filled in US4).
- [ ] T062 [US1] Create `grabarr/bypass/cache.py` — persisted `bypass_sessions` cache per research R-5, with `get(domain)` / `set(domain, cookie, ua)` / `invalidate(domain)` methods.

### Profiles, orchestrator, search-cache

- [X] T063 [US1] Create `grabarr/profiles/service.py` — CRUD methods (`list`, `get_by_slug`, `create`, `update`, `delete` with `is_default` guard, `regenerate_api_key`, `duplicate`); bcrypt hashing for API keys; cache invalidation on mutation.
- [X] T064 [US1] Create `grabarr/profiles/orchestrator.py` — `SearchOrchestrator.search(profile, query, filters)`, implementing `first_match` mode (aggregate_all deferred to US3), per-entry timeout, weight multiplier applied to `quality_score`, dedup by `(normalized_title, author, year, format)`.
- [ ] T065 [US1] Create `grabarr/profiles/cache.py` — 15-minute TTL search cache keyed by `sha256(normalized_query | profile_slug | filters_hash)` backed by `search_cache` table.

### Torznab endpoint

- [X] T066 [US1] Create `grabarr/api/torznab.py` — `t=caps` handler emitting the XML schema from `contracts/torznab-xml.md` with per-profile category filtering.
- [X] T067 [US1] Extend `grabarr/api/torznab.py` — `t=search`, `t=book`, `t=movie`, `t=music` handlers calling the orchestrator and rendering the RSS response with Torznab attrs (seeders=1, peers=0, downloadvolumefactor=0, uploadvolumefactor=1, infohash).
- [ ] T068 [US1] Extend `grabarr/api/torznab.py` — `/download/{token}.torrent` handler that kicks off the download-manager flow, waits for the torrent bytes, returns `application/x-bittorrent` with the `X-Grabarr-*` response headers.
- [X] T069 [US1] Create `grabarr/api/torznab.py` API-key middleware — verifies `apikey` query parameter against the target profile's bcrypt hash; returns 401 with `WWW-Authenticate` header on failure.

### Admin API (MVP scope: profiles + Prowlarr export)

- [X] T070 [US1] Create `grabarr/api/admin.py` — `/api/profiles` GET list, GET detail, POST create, PATCH update, DELETE (with `is_default` guard), POST `/regenerate-key`.
- [X] T071 [US1] Extend `grabarr/api/admin.py` — `/api/prowlarr-config?profile={slug}` endpoint returning the JSON blob per `contracts/prowlarr-export.json` with `{host}`, `{api_key_plain}`, `{profile_slug}` substitutions (a one-shot fresh API key is minted and shown in the JSON).

### Download manager (sync mode — the clarified shipping default)

- [ ] T072 [US1] Create `grabarr/downloads/verification.py` — per-format magic-byte table (EPUB, PDF, MOBI, MP3, FLAC, ZIP/CBZ, ISO), Content-Type rejection list (HTML/JSON/XML), size checks, 5 GB cap.
- [ ] T073 [US1] Create `grabarr/downloads/sync.py` — `SyncDownloader.run(handle)` streaming the source into `/downloads/incoming/{token}/{filename}`, running verification, moving to `/downloads/ready/{token}/{filename}`, returning `(path, metadata)`.
- [ ] T074 [US1] Create `grabarr/downloads/manager.py` — `DownloadManager.prepare_download(token, search_result)` dispatching by `settings.download.mode` (sync branch only for MVP; async/hybrid are US2).
- [ ] T075 [US1] Create `grabarr/downloads/service.py` — high-level flow orchestrating `adapter.get_download_info()` → `DownloadManager` → TorrentServer handoff; persists state transitions in `downloads` table.

### Torrent server (active_seed — the shipping default)

- [ ] T076 [US1] Create `grabarr/torrents/tracker.py` — FastAPI router mounted at `/announce` on the dedicated tracker port; bencoded compact + non-compact responses; SQLite `tracker_peers` reads/writes; 30-minute TTL sweeper task.
- [ ] T077 [US1] Create `grabarr/torrents/active_seed.py` — `ActiveSeedGenerator` wrapping libtorrent: `session_params` with DHT/LSD disabled + PEX restricted, `create_torrent(info_hash, piece_size)` with internal tracker URL, `add_torrent` with `SEED_MODE` flag, piece-size ladder per research R-3.
- [ ] T078 [US1] Create `grabarr/torrents/state.py` — shutdown hook dumps `session.state()` to `/data/session.state`; startup hook restores it if present.
- [ ] T079 [US1] Create `grabarr/torrents/server.py` — `TorrentServer.generate(download)` dispatches by `settings.torrent.mode` (active_seed branch only for MVP); orchestrates tracker + session.
- [ ] T080 [US1] Wire tracker listener startup + shutdown into `grabarr/api/app.py` lifespan (separate uvicorn worker on `settings.torrent.tracker_port`).

### Minimal admin UI (profiles list + Copy Prowlarr Config)

- [ ] T081 [US1] Create `grabarr/web/routes.py` with HTML routes: `GET /` (dashboard), `GET /profiles`.
- [ ] T082 [US1] Create `grabarr/web/templates/_base.html` — Tailwind shell, sticky nav, theme toggle (persisted in `localStorage`), dark/light system-detect, toast region.
- [ ] T083 [US1] Create `grabarr/web/templates/partials/nav.html` — navigation links (Dashboard, Profiles, Sources, Downloads, Notifications, Stats, Settings) with hamburger menu under 768 px.
- [ ] T084 [US1] Create `grabarr/web/templates/dashboard.html` — minimal: health banner, count of active downloads, count of seeded torrents, link to `/profiles`.
- [ ] T085 [US1] Create `grabarr/web/templates/profiles/list.html` — card list of seeded profiles, each with: media-type badge, enabled toggle, `Copy Prowlarr Config` button (triggers `GET /api/prowlarr-config?profile={slug}` and offers download), link to `/profiles/{slug}` (placeholder for US3 edit page).
- [ ] T086 [US1] Add vendored HTMX, Sortable, Chart.js scripts under `grabarr/web/static/js/` (downloaded via Makefile target, so static assets ship with the package).
- [ ] T087 [US1] Run `make tailwind-build` once to produce the initial `grabarr/web/static/css/tailwind.build.css`.

### Docker deployment

- [ ] T088 [US1] Create `Dockerfile` at repo root: builder stage installs libtorrent build deps + compiles the Python wheel per research R-10; runtime stage installs runtime libs, `uv sync --frozen`, copies source, copies compiled wheel, compiles Tailwind via the standalone binary, exposes 8080/8999/45000-45100, `CMD ["uvicorn", "grabarr.api.app:app", "--host", "0.0.0.0", "--port", "8080"]`.
- [ ] T089 [US1] Create `docker-compose.example.yml` — `grabarr` service with all ports + volumes, `flaresolverr` sidecar pinned to `ghcr.io/flaresolverr/flaresolverr:3`, shared `grabarr_net` network, `restart: unless-stopped`, inline-documented env vars.

### US1 integration smoke

- [ ] T090 [US1] Create `tests/integration/test_us1_smoke.py` — spin up the app via `pytest-asyncio` + `httpx.AsyncClient`, mock IA `advancedsearch.php` + `metadata/{id}` with respx, POST a Torznab search, grab the returned `.torrent`, assert magic bytes match, assert the Prowlarr export JSON parses and contains the right fields.
- [ ] T091 [US1] Create `tests/integration/test_us1_caps.py` — hit `/torznab/ebooks_general/api?t=caps` for every seeded profile, assert XML validates against the Torznab 1.3 schema.

**Checkpoint**: US1 is shippable. A clean `docker compose up -d` boots, Prowlarr imports the seven profiles first-try, and a public-domain ebook grab completes end-to-end.

---

## Phase 4: User Story 2 — Reliable Large Downloads Without *arr Timeouts (Priority: P1)

**Goal**: Asynchronous streaming mode returns a valid torrent within 2 s for arbitrarily large files and begins delivering bytes to the destination client within 60 s; hybrid mode picks sync vs async automatically; webseed mode is also available.

**Independent Test**: Per `quickstart.md` §"AC demo 2" — grab a 200 MB mock source via `async_streaming` mode, assert the `.torrent` is returned in < 2 s and the background download completes with bytes flowing during the wait.

- [ ] T092 [US2] Create `grabarr/downloads/async_streaming.py` — `AsyncStreamingDownloader.run(handle)`: pre-allocate file via `aiofiles`, start the source fetch in a background task, pre-compute the first piece's SHA-1 as soon as those bytes land, build the torrent with `create_torrent(piece_size=P)` where P comes from the ladder in research R-3, emit `have_piece` callbacks to libtorrent as background pieces complete.
- [ ] T093 [US2] Create `grabarr/downloads/hybrid.py` — `HybridDownloader.run(handle)`: fetch `Content-Length` via HEAD, delegate to `SyncDownloader` if < `settings.download.hybrid_threshold_mb`, else to `AsyncStreamingDownloader`.
- [ ] T094 [US2] Extend `grabarr/downloads/manager.py` dispatcher to handle `async_streaming` and `hybrid` modes; honour per-profile `download_mode_override`.
- [ ] T095 [US2] Extend `grabarr/torrents/active_seed.py` — support partial-file seeding (`add_torrent` with `SEED_MODE` flag cleared; manually invoke `have_piece(i)` as background writes complete; flip to full-seed once all pieces are verified).
- [ ] T096 [US2] Create `grabarr/torrents/webseed.py` — `WebseedGenerator.create(download)` emits a `.torrent` with `url-list = ["http://{host}/torznab/{slug}/seed/{token}"]` plus a dummy (but valid) announce URL so clients don't reject it.
- [ ] T097 [US2] Extend `grabarr/api/torznab.py` — `/torznab/{slug}/seed/{token}` handler supporting `Range: bytes=X-Y` with 206 Partial Content, `HEAD` returning `Content-Length`, 404 for unknown tokens, 410 Gone for expired tokens.
- [ ] T098 [US2] Extend `grabarr/torrents/server.py` dispatcher to route `settings.torrent.mode == "webseed"` to `WebseedGenerator`; honour per-profile `torrent_mode_override`.
- [ ] T099 [US2] Extend `grabarr/downloads/service.py` to pass `settings.torrent.seed_retention_hours` through to `Torrent.expires_at` (enables the cleanup sweeper planned for Polish).
- [ ] T100 [US2] Create `tests/integration/test_us2_async_streaming.py` — mock a 200 MB source with throttled body yielding 256 KiB chunks, assert torrent returns within 2 s, assert background file assembly completes and passes verification.
- [ ] T101 [US2] Create `tests/integration/test_us2_hybrid_threshold.py` — two runs, one 10 MB (sync path taken), one 200 MB (async path taken); assert each resulting `.torrent` is valid and the file-on-disk hashes match.
- [ ] T102 [US2] Create `tests/integration/test_us2_webseed.py` — generate a webseed torrent, hit `/seed/{token}` with a Range request, assert 206 response with correct bytes.

**Checkpoint**: Both P1 stories complete. Grabarr handles small and large downloads, both torrent modes, and both Phase-3 + Phase-4 acceptance tests green. v1.0 beta is releasable.

---

## Phase 5: User Story 3 — Profile-Driven Multi-Source Routing (Priority: P2)

**Goal**: Operators can create, duplicate, and edit custom profiles through the UI without restarting; `aggregate_all` mode works.

**Independent Test**: Per `quickstart.md` §"AC demo 3" — duplicate `ebooks_general`, drag IA to the top, add `languages=["fr"]`, save, copy URL to Prowlarr, confirm indexer appears and returns filtered results.

- [ ] T103 [P] [US3] Extend `grabarr/profiles/orchestrator.py` — `aggregate_all` mode: run every enabled source in parallel (bounded by a shared semaphore from rate_limit), concatenate results, dedup, sort by weight-adjusted `quality_score`, cap at 100.
- [ ] T104 [P] [US3] Extend `grabarr/profiles/service.py` `duplicate(slug, new_slug)` method — clones source entries, filters, overrides; mints a new API key; flips `is_default` to false.
- [ ] T105 [US3] Extend `grabarr/api/admin.py` — `POST /api/profiles/{slug}/test` running a real test search with full source breakdown (per `contracts/admin-api.md`).
- [ ] T106 [US3] Extend `grabarr/api/admin.py` — `POST /api/profiles/{slug}/duplicate`.
- [ ] T107 [US3] Create `grabarr/web/templates/profiles/edit.html` — full edit form with drag-and-drop source ordering (Sortable.js), weight sliders, filters chips (language + format multiselect, year/size min/max), mode radio, per-profile mode overrides, HTMX-submitted save button.
- [ ] T108 [US3] Create `grabarr/web/templates/profiles/new.html` — new-profile form reusing the edit template's components.
- [ ] T109 [US3] Create `grabarr/web/templates/partials/profile_test_results.html` — HTMX fragment rendered inline after `POST /api/profiles/{slug}/test`.
- [ ] T110 [US3] Extend `grabarr/web/routes.py` — `GET /profiles/new`, `GET /profiles/{slug}/edit`.
- [ ] T111 [US3] Extend `grabarr/web/templates/profiles/list.html` — add "Duplicate" and "Edit" actions per card.
- [ ] T112 [US3] Create `tests/integration/test_us3_custom_profile.py` — POST a new profile, assert its Torznab endpoint is immediately live (no restart), assert filters apply end-to-end in a mocked search, assert an `aggregate_all` profile returns concatenated dedup'd results.

**Checkpoint**: UI-driven profile customization works. Power users are unblocked.

---

## Phase 6: User Story 4 — Outage Resilience and Notifications (Priority: P2)

**Goal**: When a source fails, it's skipped cleanly; when FlareSolverr dies, bypass-requiring sources are marked unhealthy within 60 s; Apprise fires (with flap suppression); quota/cookie expiry surfaces clearly; automatic recovery on restoration.

**Independent Test**: Per `quickstart.md` §"AC demo 4" — stop FlareSolverr, verify AA + Z-Lib unhealthy within 60 s, IA + LibGen still serve, single Apprise ping fires, start FlareSolverr, verify full recovery in < 60 s.

### Notifications subsystem

- [ ] T113 [P] [US4] Create `grabarr/notifications/__init__.py` + `grabarr/notifications/apprise_backend.py` — `AppriseBackend.send(event, urls)` using the `apprise` library, retry 3× with exponential backoff.
- [ ] T114 [P] [US4] Create `grabarr/notifications/webhook_backend.py` — `WebhookBackend.send(event)` rendering `body_template` via Jinja2 with the event payload, POSTing with configured headers.
- [ ] T115 [US4] Create `grabarr/notifications/dispatcher.py` — `NotificationDispatcher.dispatch(event)` applies flap-suppression per research + `spec.md` FR-031a (10-minute cooldown per `(source, event_type)`; until-midnight cooldown for `quota_exhausted`), logs every attempt to `notifications_log` with `dispatch_status`, fan-outs to subscribed Apprise URLs + webhook.
- [ ] T116 [US4] Create `grabarr/notifications/encryption.py` — `cryptography.fernet` envelope for `apprise_urls.url_encrypted` using a key derived from the config master secret.

### Adapter health + circuit breaker

- [ ] T117 [US4] Create `grabarr/adapters/health.py` — `HealthMonitor`: background task running every 60 s, probes each adapter via `health_check()`, updates `adapter_health` table, trips the circuit breaker after 5 consecutive failures (`status = unhealthy`, `next_recheck_at = NOW() + 60s`), fires `source_unhealthy`/`source_recovered` events.
- [ ] T118 [US4] Extend `grabarr/profiles/orchestrator.py` to consult `adapter_health` and skip entries with `status = unhealthy`.

### Z-Library quota + cookie expiry (FR-005)

- [ ] T119 [US4] Extend `grabarr/adapters/zlibrary.py` — daily-quota tracking backed by `zlibrary_quota` table, reset at midnight UTC, `get_quota_status()` returns real values.
- [ ] T120 [US4] Extend `grabarr/adapters/zlibrary.py` — cookie-expired detection: when search returns a login page (detected by response body marker), mark `AdapterHealth.status = unhealthy` with reason `cookie_expired`, raise `AdapterAuthError`.
- [ ] T121 [US4] Extend `grabarr/adapters/zlibrary.py` — `quota_exhausted` detection fires the notification event (with the until-midnight flap suppression applied by the dispatcher).

### Bypass service — full completion

- [ ] T122 [US4] Extend `grabarr/bypass/service.py` — `auto` mode: try external first, fall back to internal on connection failure; `internal` mode dispatches directly to vendored `internal_bypasser.py`.
- [ ] T123 [US4] Extend `grabarr/bypass/service.py` — FlareSolverr version check per research R-12; incompatible version surfaces `UnhealthyReason.FLARESOLVERR_DOWN`.
- [ ] T124 [US4] Extend `grabarr/bypass/cache.py` — reactive invalidation: a 403, 503, or Cloudflare-challenge HTML (`<title>Just a moment...</title>`) on a direct request invalidates the cached entry and triggers a fresh bypass (research R-5).

### Sources admin UI + API

- [ ] T125 [US4] Extend `grabarr/api/admin.py` — `/api/sources` GET list, PATCH enable-toggle, POST `/config` with secret-field handling, POST `/test` invoking `health_check()`.
- [ ] T126 [US4] Create `grabarr/web/templates/sources.html` — adapter list with: health dot (green/yellow/red) + last-check time + reason, enable toggle, expandable config pane rendered from `ConfigSchema`, per-source rate-limit controls, `Test Now` button, Z-Library quota panel.
- [ ] T127 [US4] Extend `grabarr/web/routes.py` — `GET /sources`.

### Notifications admin UI + API

- [ ] T128 [US4] Extend `grabarr/api/admin.py` — `/api/notifications/apprise` CRUD + `/test`, `/api/notifications/webhook` PUT + `/test`, `/api/notifications/log` pagination.
- [ ] T129 [US4] Create `grabarr/web/templates/notifications.html` — Apprise URL list (URLs displayed masked), add/edit form, event-to-URL mapping (checkbox grid), generic webhook form with body-template editor, test button, log view.
- [ ] T130 [US4] Extend `grabarr/web/routes.py` — `GET /notifications`.

### Health endpoint expansion

- [ ] T131 [US4] Expand `grabarr/api/health.py` `/healthz` to return per-subsystem status per `contracts/admin-api.md`: `database`, `flaresolverr`, `libtorrent_session`, `internal_tracker`, `adapters` (each named). Return 503 when any core subsystem is failing; adapter-level failures do NOT flip overall status.

### US4 integration tests

- [ ] T132 [US4] Create `tests/integration/test_us4_outage.py` — stop FlareSolverr (mocked), wait one health cycle, assert AA + Z-Lib in `unhealthy` state, assert LibGen + IA searches still succeed, assert a single Apprise event logged (flap suppression should coalesce subsequent ticks), restore FlareSolverr, assert `source_recovered` fires within a cycle.
- [ ] T133 [US4] Create `tests/integration/test_us4_zlib_quota.py` — exhaust Z-Lib quota, assert subsequent searches return empty + log notification once, roll time to next UTC day, assert quota resets + adapter returns to healthy.
- [ ] T134 [US4] Create `tests/integration/test_us4_cookie_expired.py` — mock Z-Lib login-page response, assert adapter marked `cookie_expired`, assert Apprise fires, update config, assert adapter recovers on next health cycle.

**Checkpoint**: The service is operationally robust. US1–US4 complete means the v1.0 release gate is within reach.

---

## Phase 7: User Story 5 — Developer Extensibility (Priority: P3)

**Goal**: Adding a new adapter is a single file in `grabarr/adapters/` with `@register_adapter`; no other file needs touching.

**Independent Test**: Drop a new fake adapter in `tests/fixtures/adapters/`, start the service pointed at that package, confirm the fake appears in `/sources` and is usable in a profile.

- [ ] T135 [P] [US5] Create `docs/DEVELOPING_ADAPTERS.md` — step-by-step guide with the full `SourceAdapter` Protocol signature, a minimal copy-pasteable adapter skeleton, `get_config_schema()` example, registration flow explanation.
- [ ] T136 [P] [US5] Create `grabarr/adapters/_welib_template.py.example` — ~150-line reference implementation for a hypothetical Welib adapter (already vendored as part of AA's `_DOWNLOAD_SOURCES`), demonstrating the wrapper pattern; file ends in `.example` so the registry does NOT load it automatically.
- [ ] T137 [US5] Create `tests/fixtures/adapters/fake_source.py` — minimal passing adapter used by the registry test.
- [ ] T138 [US5] Create `tests/integration/test_us5_registry_discovery.py` — monkeypatch the adapter discovery path to include `tests.fixtures.adapters`, boot the service, assert the fake appears in `GET /api/sources`, assert a profile referencing it can be created and searched.
- [ ] T139 [US5] Add a unit test `tests/unit/test_source_adapter_protocol.py` asserting each shipped adapter `isinstance`s the `SourceAdapter` Protocol at runtime (`runtime_checkable` enforces it).

**Checkpoint**: All five user stories complete. Remaining work is polish + cross-cutting.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: The observability, documentation, cleanup, and full-UI work required for an actual v1.0 release rather than a feature-complete prototype. All tasks in this phase are [P]-compatible across files.

### Observability (Constitution Article XIV, SC-010)

- [ ] T140 [P] Create `grabarr/api/metrics.py` — `prometheus-client` exposition at `/metrics` with every counter/histogram/gauge from spec FR-028: per-source search/download counters, bypass invocations, error counts, response + download + bypass duration histograms, active downloads by mode, seeded torrents, queue depth, source health, quota remaining. Target: > 50 distinct series under load.
- [ ] T141 [P] Extend `grabarr/core/logging.py` with a FastAPI middleware that attaches a `correlation_id` context var per request and includes it in every log record.
- [ ] T142 [P] Create `grabarr/contrib/grafana-dashboard.json` — Grafana dashboard definition covering all metric families (can be imported cleanly into a fresh Grafana per SC-010).

### Admin UI — remaining pages (Constitution Article XVI)

- [ ] T143 [P] Create `grabarr/web/templates/settings/bypass.html`, `downloads.html`, `torrents.html`, `paths.html`, `metadata.html`, `backup.html` — the six Settings sub-pages per spec FR-9.4.
- [ ] T144 [P] Create `grabarr/web/templates/downloads.html` — paginated history, per-entry detail modal (timings, info_hash, file status), retry button, delete action with confirmation dialog.
- [ ] T145 [P] Create `grabarr/web/templates/stats.html` — Chart.js graphs wired to `/api/stats/series`, top-queries table, Prometheus URL display, CSV/JSON export buttons.
- [ ] T146 [P] Extend `grabarr/api/admin.py` — `/api/settings` GET/PATCH, `/api/settings/backup` export, `/api/settings/restore` import (multipart), `/api/downloads` list + detail + retry + delete, `/api/stats/overview`, `/api/stats/series`, `/api/stats/top-queries`, `/api/stats/export`.
- [ ] T147 [P] Extend `grabarr/web/routes.py` with `/settings`, `/settings/{section}`, `/downloads`, `/stats` HTML routes.
- [ ] T148 [P] Extend `grabarr/web/templates/_base.html` — toast notifications helper, confirmation-dialog component, keyboard-shortcuts help modal bound to `?`.
- [ ] T149 [P] Run accessibility audit on every template (WCAG AA): ensure all form inputs have `<label>`, focus outlines visible, no color-only information, screen-reader-only helper text where needed.

### Background workers + cleanup (spec FR-039a, state invariants)

- [ ] T150 [P] Create `grabarr/downloads/cleanup.py` — apscheduler task that removes files whose `ready_at + seed_retention_hours` has passed, clears `file_path`, sets `file_removed_at`.
- [ ] T151 [P] Create `grabarr/downloads/post_processors.py` — ZIP/7Z/RAR extractors for `game_rom` and `software` media types, M3U playlist builder for multi-disc audio; configurable per media type via `settings.paths.post_processors`.
- [ ] T152 [P] Create `grabarr/bypass/cache.py` — sweeper that purges `bypass_sessions` rows with `expires_at < NOW()`.
- [ ] T153 [P] Extend `grabarr/torrents/tracker.py` — peer-TTL sweeper (already stubbed in T076; add the scheduled registration here).
- [ ] T154 [P] Create `grabarr/profiles/cache.py` — `search_cache` TTL sweeper (15-minute entries).
- [ ] T155 [P] Create `grabarr/notifications/cleanup.py` — `notifications_log` retention (30 days).
- [ ] T156 [P] Create `grabarr/downloads/retention.py` — `downloads` row retention sweeper (30 days from `started_at`).

### Unit tests (supporting acceptance criteria)

- [ ] T157 [P] Create `tests/unit/test_rate_limit.py` — token bucket correctness under concurrency.
- [ ] T158 [P] Create `tests/unit/test_verification.py` — parametrized magic-byte test matrix covering every format + rejection paths.
- [ ] T159 [P] Create `tests/unit/test_orchestrator.py` — first_match short-circuit, aggregate_all dedup, weight multiplier correctness, filter application, member-required skip, unhealthy skip.
- [ ] T160 [P] Create `tests/unit/test_bypass_cache.py` — TTL expiry, sliding refresh, 403/503 reactive invalidation.
- [ ] T161 [P] Create `tests/unit/test_flap_suppression.py` — 10-minute coalescing, until-midnight coalescing for `quota_exhausted`, suppressed entries logged correctly.
- [ ] T162 [P] Create `tests/unit/test_quality_scoring.py` — every scoring rule from research R-14.
- [ ] T163 [P] Create `tests/unit/test_torznab_xml.py` — every caps + search XML response validates against the Torznab 1.3 schema; required attrs present with correct values.
- [ ] T164 [P] Create `tests/unit/test_ia_file_selector.py` — every MediaType ladder picks the right file given a representative `metadata/{id}` fixture; blacklist drops Metadata / Thumbnail etc.
- [ ] T165 [P] Create `tests/unit/test_circuit_breaker.py` — 5-failure trip, 60-second recheck, recovery flip.
- [ ] T166 [P] Create `tests/unit/test_redaction.py` — every known secret key is redacted in both text and JSON log output.

### Documentation

- [ ] T167 [P] Create `README.md` at repo root — project pitch, quickstart link, feature matrix, non-goals, license note (GPL-3.0).
- [ ] T168 [P] Create `docs/quickstart.md` — mirror of `specs/001-grabarr-core-platform/quickstart.md` minus the acceptance-walkthrough section.
- [ ] T169 [P] Create `docs/configuration.md` — every `settings` key + every `config.yaml` field with semantics, defaults, validity ranges.
- [ ] T170 [P] Create `docs/troubleshooting.md` — the table from `quickstart.md` §"Common operator issues" plus an expanded FAQ.
- [ ] T171 [P] Create `CHANGELOG.md` with a v1.0.0 entry.
- [ ] T172 [P] Create `LICENSE` at repo root (GPL-3.0 per Constitution §Technology Stack).

### Release gate

- [ ] T173 Run the complete acceptance walk-through from `quickstart.md` §3 manually and record pass/fail per SC in `docs/release-v1.0-checklist.md`.
- [ ] T174 Run `uv run pytest -q` — all suites (unit, integration, vendor_compat) MUST pass.
- [ ] T175 Run `uv run ruff check grabarr/ tests/` — clean (vendored code excluded via config).
- [ ] T176 Run `uv run mypy grabarr/` — clean under `--strict` (vendored code excluded).
- [ ] T177 Run `docker compose -f docker-compose.example.yml up -d` against the built image and walk through SC-001 by hand.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: no dependencies.
- **Phase 2 (Foundational)**: depends on Phase 1; BLOCKS every user story.
- **Phase 3 (US1 — MVP)**: depends on Phase 2. Independently shippable as beta.
- **Phase 4 (US2)**: depends on Phase 2; logically builds on US1's download/torrent plumbing but does not block parallel work.
- **Phase 5 (US3)**: depends on Phase 2 + US1 (needs minimal profile list UI to extend).
- **Phase 6 (US4)**: depends on Phase 2; notification + health work is largely independent.
- **Phase 7 (US5)**: depends on Phase 2 adapter protocol; can start any time after T024 lands.
- **Phase 8 (Polish)**: depends on Phase 2; individual tasks may start alongside the user stories once their inputs exist, but the final release gate (T173–T177) runs last.

### User Story Parallelism

Once Phase 2 is green, a three-developer team could split:

- **Dev A**: Phase 3 (US1 MVP) then Phase 4 (US2).
- **Dev B**: Phase 6 (US4 — notifications + health) in parallel with US1.
- **Dev C**: Phase 5 (US3 UI — after US1 minimal UI lands) then Phase 7 (US5).

Phase 8 polish is mostly [P]-parallel and can be picked up opportunistically.

### Within each phase

- Models before services before endpoints.
- Adapters before orchestrator before Torznab endpoint.
- Download + Torrent before US1 smoke test.
- Vendor-compat tests run immediately after vendoring; they gate US1.

### Parallel Opportunities

- All of T017–T025 (core modules) can run in parallel — different files, only internal package imports once created.
- All of T030–T038 (ORM models) — one file each, no cross-dependencies.
- All of T040–T047 (vendor-compat tests) — independent test files.
- All of T058–T060 (AA, LibGen, Z-Lib adapters) — each a single wrapper file.
- All of T103–T104 (orchestrator aggregate + duplicate) are file-independent.
- All of T113–T116 (notifications subsystem) — fan-out across files.
- Nearly every Polish task (T140–T172) — [P]-marked, few interdependencies.

---

## Parallel Example: Phase 2 Core Modules + ORM

Once T001–T016 are done, the following can launch together in the same message:

```bash
# Five engineers working simultaneously on independent files:
Dev 1: T017 + T022 (enums + Newznab categories)
Dev 2: T018 + T019 (dataclasses + pydantic-settings config)
Dev 3: T020 + T021 (logging + rate_limit)
Dev 4: T023 + T024 (registry + base.py)
Dev 5: T026 + T027 + T028 (db/base, session, Alembic env)

# Then in a second wave:
All devs split T030–T038 (one ORM model per dev)
All devs split T040–T047 (one vendor-compat test per dev)
```

---

## Implementation Strategy

### MVP First (US1 only)

1. Complete Phase 1 (Setup) — ~0.5 day.
2. Complete Phase 2 (Foundational, including vendor-compat green) — ~2–3 days.
3. Complete Phase 3 (US1). At this point, `docker compose up` with Prowlarr works end-to-end and ships as a **private beta**.
4. **Stop & validate** — run `quickstart.md` AC demo 1 and AC demo 3 by hand.

### Incremental Delivery

1. Beta 1: Setup + Foundation + US1 (MVP).
2. Beta 2: Add US2 — large-file downloads reliable.
3. Beta 3: Add US3 — UI customization.
4. Beta 4: Add US4 — outage resilience + notifications. (This is close to a 1.0.)
5. RC: Add US5 + Polish phase.
6. GA: Run T173–T177 release gate, tag v1.0.0.

Each beta is shippable. Each subsequent story adds value without breaking the earlier ones.

### Parallel Team Strategy

See "User Story Parallelism" under Dependencies above.

---

## Notes

- [P] tasks operate on different files with no in-phase dependencies — safe to run in parallel.
- [USn] labels let anyone cross-reference spec stories from a task at a glance.
- Vendored Shelfmark files live under `grabarr/vendor/shelfmark/` and MUST remain untouched except for import rewrites (Constitution §Governance rule 5).
- Any new adapter added after v1.0 is, by design, ~1 task (one file + one unit test) — not a whole phase (SC-008).
- Verify each test fails before implementing (where tests precede code); commit after each task or logical group for clean bisect.
- Stop at any checkpoint to validate the corresponding story independently.
