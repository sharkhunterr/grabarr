<!--
SYNC IMPACT REPORT
==================
Version change: (template placeholder) → 1.0.0
Bump rationale: Initial ratification. The prior file contained only template
placeholders with no concrete principles, so this is the first versioned
constitution and takes MAJOR version 1.0.0.

Modified principles: N/A (initial adoption)
Added sections:
  - Core Principles: 16 articles (I — XVI)
  - Technology Stack & Dependency Policy
  - Vendoring Procedure & Project Layout
  - Scope Boundaries (Non-Goals)
  - Governance
Removed sections: None

Templates / artifacts requiring updates:
  - .specify/templates/plan-template.md — ⚠ pending: the generic "Constitution
    Check" gate should be populated with checks that map to the 16 articles
    (transparent Torznab surface, no auth, vendor-first for Shelfmark-covered
    sources, adapter registration, integrity verification, rate limits, secrets
    hygiene, observability surface, notification hooks, UI a11y). Left generic
    here; will be specialized by the first `/speckit.plan` run.
  - .specify/templates/spec-template.md — ✅ no changes required: the template
    is domain-agnostic and already accommodates the user-stories / SC format
    used by the Success Criteria in this constitution.
  - .specify/templates/tasks-template.md — ⚠ pending: category coverage should
    include vendor_compat tests (Article III / VIII), integrity-verification
    tests (Article XI), rate-limit tests (Article XII), metric-count check
    (SC-10), and a11y checks (Article XVI). Left generic here; to be applied
    when `/speckit.tasks` first runs for a feature that exercises those areas.
  - README.md / docs/quickstart.md — not present in repo yet; will be created
    during initial implementation and must reference this constitution.
  - .specify/templates/commands/*.md — no project-local overrides exist; the
    shipped commands already reference generic guidance.

Deferred items / TODOs: None. All placeholders were resolvable from the
supplied project brief.
-->

# Grabarr Constitution

Grabarr is a multi-source media indexer and download bridge that exposes shadow
libraries (Anna's Archive, LibGen, Z-Library, Internet Archive) as standard
Torznab indexers for Prowlarr and downstream *arr applications. It downloads
HTTP files and generates seedable torrents on the fly so that any standard
BitTorrent client can consume them transparently.

This constitution is the top-level governance document for the project. Every
principle below is binding on implementation, review, and amendment. Where the
text says MUST, MUST NOT, SHOULD, or MAY, those terms follow RFC 2119 meaning.

## Core Principles

### I. Transparent *arr Integration (NON-NEGOTIABLE)

Grabarr MUST behave as a standard Torznab indexer from the perspective of
Prowlarr and downstream *arr apps. No custom client code is required in
Bookshelf, Readarr, Mylar3, or any *arr application. No Grabarr-specific
download client is required. The *arr apps MUST interact with Grabarr exactly
as they would with a conventional scene tracker: search via Torznab XML, grab
via `download_url`, consume the returned `.torrent` with their existing
download client.

**Rationale**: The project's entire reason for existing is to bridge shadow
libraries into an unmodified *arr workflow. Any feature that breaks this
transparency defeats the project and MUST be rejected at design review.

### II. No Authentication

Grabarr MUST NOT implement authentication, OIDC, multi-user accounts, role-
based access control, API keys for the admin UI, or any form of user
management. The service is single-tenant by design. Access control is
delegated to a reverse proxy (Authentik, Nginx Proxy Manager, Traefik
ForwardAuth) deployed in front of Grabarr. Configuration is global.
Downloads history and statistics are global.

**Rationale**: Homelab deployments consistently delegate identity to a single
edge proxy; reimplementing auth inside every service produces bugs, drift, and
maintenance cost without benefit.

### III. Reuse Over Reimplementation (CRITICAL, NON-NEGOTIABLE)

Grabarr MUST reuse proven code from Shelfmark
(`calibre-web-automated-book-downloader`, MIT-licensed) rather than
reimplementing equivalent logic. The binding strategy:

1. Vendorize Shelfmark modules directly into `grabarr/vendor/shelfmark/`,
   preserving their directory structure.
2. Preserve the original MIT attribution header in every vendored file.
3. Adapt minimally: fix imports (`shelfmark.X` → `grabarr.vendor.shelfmark.X`);
   bridge Shelfmark's config and logger interfaces to Grabarr equivalents; do
   NOT modify any logic.
4. Wrap, do not rewrite. Grabarr's adapters in `grabarr/adapters/` are thin
   translation layers that expose the Grabarr `SourceAdapter` protocol over
   the vendored Shelfmark code.

Reimplementing Shelfmark's Anna's Archive / LibGen / Z-Library logic,
Cloudflare bypass, mirror rotation, countdown handling, URL-extraction
strategies, or fingerprint randomization is FORBIDDEN. Only Grabarr-specific
concerns (the adapter protocol wrapper, torrent generation, Torznab endpoint,
profiles, and the admin UI) are implemented fresh.

Expected distribution: approximately 60% of Grabarr's source comes from
vendored Shelfmark modules; approximately 40% is Grabarr-specific code.

**Rationale**: Shelfmark's cascade is battle-tested by its community; rewrites
of that logic have a long history of regressing edge cases that took years to
stabilize. The upstream license (MIT) is compatible with vendoring into a
GPL-3.0 project.

### IV. Adapter-Based Extensibility

Every content source MUST be accessible through a `SourceAdapter` wrapper
conforming to a shared protocol defined in `grabarr/adapters/base.py`. The
wrapper's responsibility is to translate between Grabarr's interface
(profiles, `MediaType`, Torznab) and the underlying implementation (vendored
Shelfmark for existing sources, fresh code for Grabarr-native sources such
as Internet Archive).

Adding a new source MUST be a single wrapper file in `grabarr/adapters/`
annotated with `@register_adapter`. The registry MUST auto-discover adapters
at startup; no global registration list MAY be hand-edited.

### V. Media Type Agnostic

Grabarr MUST support arbitrary media types via a Python enum exposing at
minimum: `ebook`, `audiobook`, `comic`, `magazine`, `music`, `software`,
`paper`, `game_rom`, `video`. Adapters MUST declare the media types they
support. The orchestrator MUST route queries only to adapters that declare
the requested type. Adding a new media type MUST require only adding an enum
value and updating the relevant adapter declarations.

### VI. Profile-First Design

User-facing behaviour MUST be driven by Profiles, not by direct source
selection. A Profile is a named recipe with: `media_type`, ordered sources
with weights, filters (language, format, year, size), mode
(`first_match` | `aggregate_all`), and Newznab categories. Each profile MUST
be exposed as an independent Torznab endpoint at `/torznab/{slug}/api`. Users
configure Prowlarr to consume whichever profiles they need. The admin UI MUST
support full CRUD of profiles without restart.

### VII. Shelfmark's Cascade Is Sacred (NON-NEGOTIABLE)

For Anna's Archive, the download cascade logic from Shelfmark's
`release_sources/direct_download.py` MUST be preserved in its entirety. The
following facets MUST NOT be simplified, reordered, or rewritten:

- The sub-source taxonomy: `aa-fast`, `aa-slow-nowait`, `aa-slow-wait`,
  `aa-slow`, `libgen`, `zlib`, `welib`, `ipfs`.
- The per-sub-source failure threshold of 4 before skipping to the next.
- The multi-strategy URL extraction (clipboard JS, download button, span URL,
  `location.href`, "copy this url" patterns).
- Countdown detection and live wait with status callbacks.
- AA-discovered external mirrors (LibGen/Welib/Z-Lib URLs found on AA pages).
- Dynamic sub-source classification via `_url_source_types`.
- The `fast_download` API path when an AA member key is present.
- Graceful cascade-down on each sub-source failure.

### VIII. Bypass Reuses Shelfmark Verbatim

The `grabarr/vendor/shelfmark/bypass/` directory MUST be a 1:1 port of
Shelfmark's bypass module: `external_bypasser.py` (FlareSolverr client),
`internal_bypasser.py` (SeleniumBase-based fallback), and `fingerprint.py`
(screen-size randomization). Imports MUST be adjusted to Grabarr's config
module; logic MUST remain untouched.

FlareSolverr MUST run as a Docker sidecar. The internal bypasser MUST be
available but disabled by default (heavier resource usage). Bypass mode MUST
be switchable via `bypass.mode = external | internal | auto`.

### IX. Dual Torrent Generation Strategy

Grabarr MUST generate torrents consumable by any standard BitTorrent client.
Two modes MUST be fully implemented and switchable globally, with per-profile
overrides allowed:

1. **Active Seed** (default): in-process `libtorrent` session with an internal
   HTTP tracker; Grabarr acts as the only peer. Maximum client compatibility.
2. **Webseed** (BEP-19): torrent file references a webseed URL pointing at
   Grabarr's own HTTP endpoint.

### X. Triple Download Strategy

The moment of HTTP download from the source MUST be configurable. All three
of the following modes MUST be fully implemented and switchable globally,
with per-profile overrides allowed:

1. **Synchronous**: the HTTP download occurs when `download_url` is called;
   the *arr client blocks until the file is complete.
2. **Asynchronous Streaming**: the torrent is returned immediately; the HTTP
   download runs in the background; bytes stream to the torrent client as
   they arrive.
3. **Hybrid**: synchronous for files below a configurable threshold (default
   50 MB), asynchronous above.

### XI. File Integrity Is Sacred

Every downloaded file MUST be verified before being handed to the torrent
client. Required checks:

- Content-Type check: reject HTML, JSON, or XML responses unless expected.
- Size check against configured minimum and maximum.
- Magic-byte verification per format:
  - EPUB: `PK\x03\x04`
  - PDF: `%PDF`
  - MOBI: `BOOKMOBI` at offset 60
  - MP3: `ID3` or `FF FB`
  - FLAC: `fLaC`
  - ZIP / CBZ: `PK\x03\x04`
  - ISO: `CD001` at offset `0x8001`
- Maximum file-size cap (default 5 GB).

Verification logic from Shelfmark MUST be reused where it exists. Grabarr-
specific checks (e.g. ROM formats) MUST be added as extensions, not
replacements.

### XII. Rate Limit Everything

Every external source MUST be rate-limited per-adapter using a token bucket.
Defaults:

- Anna's Archive: 30 requests/minute for search; 2 parallel downloads.
- LibGen: 60 requests/minute.
- Z-Library: 10 requests/minute plus 10 downloads/day quota enforcement.
- Internet Archive: 30 requests/minute.

A health check MUST be performed before consuming a quota-limited source when
that source is known to be degraded.

### XIII. No Secrets In Code Or Logs

API keys, Anna's Archive member keys, Z-Library cookies, and any other
credentials MUST live in `config.yaml` (mounted as a Docker volume) or in
environment variables. They MUST NOT be hard-coded. They MUST NOT be logged
(a redaction filter MUST be applied to every logger). The UI MAY reveal
secrets only on the Settings page, on explicit user action.

### XIV. Observability Built-In

Prometheus metrics MUST be exposed at `/metrics`, including per-source
counters, latency histograms, and health gauges (target: ≥ 50 distinct
series). Structured JSON logging MUST be available as a configurable mode. A
health endpoint `/healthz` MUST report per-subsystem status (bypass, each
adapter, torrent server, DB, FlareSolverr sidecar).

### XV. Notifications Are First-Class

Apprise integration MUST be provided for at minimum the following events:
`download_completed`, `download_failed`, `source_unhealthy`,
`source_recovered`, `quota_exhausted`, `bypass_failed`, `cookie_expired`. A
generic webhook fallback MUST also be available for systems not covered by
Apprise.

### XVI. Admin UI Is Production-Grade

The admin UI MUST be:

- Fully responsive from 360 px wide to 4K.
- WCAG AA accessible (contrast, ARIA labels, focus management).
- Fully keyboard-navigable.
- Themed light and dark, with a user toggle persisted client-side.
- Supported by inline help text on every non-obvious control.
- Guarded by confirmation dialogs for destructive actions (profile deletion,
  history purge, credential deletion).

## Technology Stack & Dependency Policy

The following stack is non-negotiable. Any substitution requires a
constitutional amendment.

- **Language**: Python 3.12+
- **Web framework**: FastAPI (async throughout)
- **Templating / frontend**: Jinja2 + HTMX + Tailwind CSS built via the
  Tailwind CLI (no webpack, no Vite, no Node-based bundler)
- **Database**: SQLite via SQLAlchemy 2.0 async; migrations via Alembic
- **Torrent generation**: `libtorrent` Python bindings 2.0+
- **HTTP client**: `httpx` (async)
- **HTML parsing**: `BeautifulSoup4` with the `lxml` parser (same as
  Shelfmark — required for direct vendoring)
- **Config**: `pydantic-settings` with YAML support
- **Scheduling**: `apscheduler` plus `asyncio.Queue`
- **Caching**: `async-lru` in-memory
- **Notifications**: `apprise`
- **Metrics**: `prometheus-client`
- **Deployment**: Docker + docker-compose, with FlareSolverr as a sidecar
- **Tests**: `pytest`, `pytest-asyncio`, `respx`
- **Linting / typing**: `ruff` and `mypy --strict`
- **Dependency management**: `uv`

**Licensing**: Grabarr is distributed under GPL-3.0 to maintain license
compatibility with vendored Shelfmark modules. Vendored files MUST retain
their original MIT headers; newly authored Grabarr files MUST carry GPL-3.0
headers.

## Vendoring Procedure & Project Layout

### Mandatory Vendoring Procedure

Implementation work that touches vendored Shelfmark code MUST follow this
procedure exactly:

1. Clone the `main` branch of
   `https://github.com/calibrain/calibre-web-automated-book-downloader` to
   obtain the reference source and commit SHA.
2. Copy the following files verbatim into `grabarr/vendor/shelfmark/`,
   preserving their subdirectory structure:
   - `bypass/external_bypasser.py`, `bypass/internal_bypasser.py`,
     `bypass/fingerprint.py`, `bypass/__init__.py`
   - `core/mirrors.py`, `core/naming.py`
   - `release_sources/direct_download.py`
   - All `__init__.py` files required on those paths.
3. Add a license header to each vendored file: preserve the original MIT
   notice and append `Vendored into Grabarr at commit {SHA}, {YYYY-MM-DD}`.
4. Create `grabarr/vendor/shelfmark/ATTRIBUTION.md` containing the full MIT
   licence text, the source commit SHA, and the upstream URL.
5. Fix imports only — replace `from shelfmark.X` with
   `from grabarr.vendor.shelfmark.X`. Do NOT modify logic or control flow.
6. Create `grabarr/vendor/shelfmark/_grabarr_adapter.py` that exposes the
   config and logger interfaces Shelfmark expects, bridging them to
   Grabarr's pydantic-settings config and application logger.
7. Add integration tests under `tests/vendor_compat/` that verify each
   vendored module still works after the import and bridge adaptation. Tests
   MUST use `respx` mocks and MUST NOT touch the live network.

### Project Layout

```text
grabarr/
├── vendor/
│   └── shelfmark/            # Direct port of Shelfmark modules
│       ├── ATTRIBUTION.md    # MIT license + source commit SHA
│       ├── __init__.py
│       ├── _grabarr_adapter.py
│       ├── bypass/           # external_bypasser, internal_bypasser, fingerprint
│       ├── core/             # mirrors, naming
│       └── release_sources/  # direct_download
├── adapters/                 # Grabarr SourceAdapter wrappers
│   ├── __init__.py           # Registry + @register_adapter
│   ├── base.py               # SourceAdapter protocol
│   ├── anna_archive.py       # Wrapper around vendored AA cascade
│   ├── libgen.py             # Wrapper around vendored LibGen logic
│   ├── zlibrary.py           # Wrapper around vendored Z-Lib logic
│   └── internet_archive.py   # NEW: Grabarr-native (not in Shelfmark)
├── bypass/                   # Service layer over vendored bypass module
│   └── service.py
├── core/                     # Registry, enums, models, config
├── downloads/                # DownloadManager (sync + async + hybrid) — NEW
├── torrents/                 # TorrentServer (active_seed + webseed) — NEW
├── profiles/                 # Profile CRUD + orchestrator — NEW
├── api/                      # /torznab/{slug}, /api/admin, /healthz, /metrics
├── web/                      # Jinja2 + Tailwind + HTMX — NEW
├── notifications/            # Apprise + webhook — NEW
├── db/                       # SQLAlchemy + Alembic
├── cli/                      # Management commands
└── tests/
    ├── unit/
    ├── integration/
    └── vendor_compat/        # Verifies vendored modules post-adaptation
```

## Scope Boundaries (Non-Goals)

To keep the project coherent with its stated purpose, the following are
explicitly OUT of scope and MUST be rejected at design review:

- Grabarr is NOT an end-user download manager. End users use Bookshelf,
  Readarr, Mylar3, etc.
- Grabarr is NOT a library manager. Audiobookshelf, ROMM, and Calibre-Web
  fill that role.
- Grabarr is NOT a metadata provider.
- Grabarr does NOT redistribute or persistently seed content. Seeding exists
  solely to satisfy the handoff contract with the *arr download client.
- Grabarr is NOT a general-purpose scraper. Each adapter targets specific,
  named sources.
- Grabarr does NOT reimplement capabilities Shelfmark already provides.
  Vendor and wrap.

## Success Criteria

These outcomes constitute the release gate for v1.0 and serve as ongoing
compliance tests after each significant change:

- **SC-01**: Adding Grabarr as a Generic Torznab indexer in Prowlarr works on
  the first try for each of the seven default profiles.
- **SC-02**: A Bookshelf "wanted" ebook triggers an auto-search; Grabarr
  returns results via the vendored Shelfmark cascade for Anna's Archive;
  Bookshelf grabs; the file reaches Deluge; the file is imported and renamed.
  Zero manual intervention.
- **SC-03**: First-time AA search with a Cloudflare challenge resolves in
  under 30 s via the vendored FlareSolverr client; subsequent searches use
  the cached `cf_clearance` in under 2 s.
- **SC-04**: An Internet Archive ebook grab completes end-to-end in under
  15 s.
- **SC-05**: A 500 MB audiobook via AA `slow_download` in Async Streaming
  mode begins flowing to Deluge within 60 s.
- **SC-06**: FlareSolverr outage correctly marks AA/Z-Lib as unhealthy;
  Bookshelf falls back to LibGen+IA; an Apprise notification fires; auto-
  recovery restores the unhealthy sources without restart.
- **SC-07**: The UI is fully functional at 360 px mobile and elegant at 4K.
- **SC-08**: Adding a hypothetical Welib adapter (module already vendored
  from Shelfmark) requires a single wrapper file of roughly 150 lines.
- **SC-09**: The service survives restart without losing profiles, downloads
  history, seed state, Z-Lib quota counter, or bypass session cache.
- **SC-10**: `/metrics` returns more than 50 distinct Prometheus series.
- **SC-11**: Vendored Shelfmark code passes the `tests/vendor_compat/`
  suite with the same behaviour it exhibits in upstream Shelfmark.

## Governance

1. **Supremacy**: This constitution supersedes all other project practices,
   including CLAUDE.md, READMEs, and individual pull-request conventions.
   Conflicts MUST be resolved by amending the constitution, not by silently
   deviating from it.

2. **Amendment procedure**: A constitutional amendment requires a pull
   request that (a) edits `.specify/memory/constitution.md`, (b) updates the
   Sync Impact Report in the comment at the top of that file, (c) bumps the
   version per the rules below, and (d) propagates the change into every
   dependent template listed in the Sync Impact Report.

3. **Versioning**: The constitution uses semantic versioning
   (`MAJOR.MINOR.PATCH`).
   - MAJOR: a backward-incompatible change, a principle removal, or a
     redefinition that invalidates prior design decisions.
   - MINOR: a new principle, section, or materially expanded guidance.
   - PATCH: clarifications, wording fixes, non-semantic refinements.

4. **Compliance review**: Every pull request MUST be reviewed against the
   Constitution Check gate in `plan-template.md`. Any identified violation
   MUST be either fixed or justified in the plan's Complexity Tracking
   table. Unjustified violations block merge.

5. **Vendoring discipline**: Changes inside `grabarr/vendor/shelfmark/`
   require an explicit note on the PR describing what upstream commit they
   correspond to. Rewriting vendored logic (as opposed to re-vendoring from
   a newer upstream commit) requires a MAJOR version bump of this
   constitution and an explicit carve-out in Article III or VII.

6. **Runtime guidance**: Operational how-to content (dev setup, testing
   recipes, deployment playbooks) lives in `README.md`, `docs/`, and
   agent-specific guidance files. Those files MUST NOT restate principles
   from this document; they MUST reference this document instead.

**Version**: 1.0.0 | **Ratified**: 2026-04-23 | **Last Amended**: 2026-04-23
