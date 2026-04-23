# Phase 0 Research — Grabarr Core Platform v1.0

**Feature**: 001-grabarr-core-platform
**Date**: 2026-04-23

The constitution (`.specify/memory/constitution.md` v1.0.0) locks the language,
framework, database, torrent library, HTTP client, templating, and test stack,
so most "what do we use" questions are already answered. The clarifications
session resolved five additional product defaults. This document records the
remaining decisions the spec did not spell out and gathers the external-
reference material the implementation must cite.

No `[NEEDS CLARIFICATION]` markers remain in the spec; no additional
clarifications are required before Phase 1.

---

## R-1 — Vendoring bridge: how Shelfmark code talks to Grabarr

**Decision**: Introduce a single shim module, `grabarr/vendor/shelfmark/
_grabarr_adapter.py`, that exposes exactly the names Shelfmark imports from
its own `shelfmark.core.config` and `shelfmark.core.logger` modules. The shim
proxies those names onto Grabarr's `core.config` and `core.logging`. Every
vendored file's `from shelfmark.X` import is rewritten to
`from grabarr.vendor.shelfmark.X`; the two config/logger imports specifically
are rewritten to pull from `_grabarr_adapter`.

**Rationale**: The constitution bans modifying vendored logic (Article III).
Shelfmark's code expects a module-global `config` object with a `.get(key,
default)` API and a `setup_logger(name)` function. Bridging these through a
single shim is the minimum adaptation that satisfies both the "imports only"
rule and Shelfmark's runtime contract. It concentrates the blast radius of
any future Shelfmark refactor to one file we own.

**Alternatives considered**:
- *Monkey-patch `sys.modules` at startup*. Rejected: opaque, violates the
  "grep-friendly imports" principle, and leaves `from shelfmark...` imports
  pointing at non-existent modules, which confuses IDEs and static analyzers.
- *Fork Shelfmark into a private package and depend on it via PyPI*.
  Rejected: adds a release dependency for a project whose whole point is to
  be a homelab appliance; also complicates the SHA-pinned "vendored at
  commit X" attribution Article III requires.

**Implementation notes**:
- The shim MUST be imported by every vendored module BEFORE any logic runs,
  so place it in the vendored subtree's `__init__.py` chain.
- `ShelfmarkConfigProxy.get(key, default)` MUST translate Shelfmark keys
  (e.g. `AA_MEMBER_KEY`, `AA_DONATOR_KEY`, `CF_BYPASS_MODE`) into Grabarr's
  pydantic-settings equivalents (e.g. `sources.anna_archive.member_key`).
  Unknown keys return `default`.
- `setup_logger(name)` MUST return a logger with the Grabarr redaction filter
  applied (Constitution Article XIII).

---

## R-2 — libtorrent session + internal HTTP tracker integration

**Decision**: Run libtorrent in `SEED_MODE` without DHT/LSD, with PEX
restricted to the internal peer set. Use the Python `libtorrent` binding's
`add_torrent_params` with `save_path` pointing at `/downloads/ready/{token}/`.
The internal HTTP tracker is a separate FastAPI route mounted on the main
app (not a standalone server) at `GET /announce`; it reads peers from SQLite
keyed by `info_hash`. The only peer we expect is Grabarr itself, so the
tracker's job is to reply with a compact-format response listing Grabarr's
own listen address plus the real client that just announced.

**Rationale**:
- The constitution bans DHT/LSD (Article IX); PEX is allowed but restricted.
- One-tracker-per-torrent + one-peer-per-torrent is the minimal setup that
  satisfies "any standard BitTorrent client" while still producing legal
  torrents. Deluge/qBittorrent/Transmission/rTorrent all speak the BEP-3
  compact announce protocol.
- Mounting the tracker on the main FastAPI app avoids a second asyncio loop
  and simplifies port exposure (still a separate port per the spec — 8999 —
  but a single process).

**Alternatives considered**:
- *External tracker (opentracker/xbt-tracker)*. Rejected: extra container,
  extra port, and overkill when the only peer is us.
- *Use libtorrent's built-in HTTP tracker*. Rejected: tying the tracker
  lifecycle to libtorrent means a tracker restart on every libtorrent
  restart, which is worse than SQLite-backed persistence.

**Implementation notes**:
- `lt.session_params(flags=lt.session_flags.disable_dht |
  lt.session_flags.disable_lsd)`.
- `lt.settings_pack` with `listen_interfaces = 0.0.0.0:45000-45100` and
  `enable_outgoing_*` left default.
- Session state: `session.state()` dumped to `/data/session.state` on
  shutdown, reloaded on startup (`session.load_state()`).
- Peer store schema: `(info_hash, peer_id, ip, port, last_seen)` with a
  30-minute TTL sweeper task.

---

## R-3 — Async-streaming download coordination

**Decision**: Pre-compute the torrent's piece hashes *after* the first N MB
of the HTTP download have arrived (where N = one piece size, default 256 KiB
for small files, up to 4 MiB for > 1 GiB files). Use libtorrent's
`create_torrent(..., piece_size=P)` to generate the `.torrent` bencoded blob
immediately when N bytes are in, return it to the *arr client, and continue
downloading in the background. The internal tracker serves Grabarr as a
"we've got piece 0..K" peer while background bytes fill in; once the full
file is written, libtorrent flips to full `SEED_MODE`.

**Rationale**: Async-streaming's promise is "torrent in 500 ms, real bytes
flowing to Deluge within 60 s" (SC-004). libtorrent requires all piece hashes
to be known before issuing the torrent, so we cannot return the torrent
until at least the first piece is hashed. Choosing the piece size based on
the source's `Content-Length` keeps the first-piece wait bounded and the
total piece count manageable.

**Alternatives considered**:
- *Compute all piece hashes ahead of time by fully downloading first*.
  Rejected: defeats the entire purpose of async-streaming (this is what
  `sync` mode does).
- *Use BEP-30 (Merkle hashes)*. Rejected: client support is inconsistent;
  Transmission notably lacks it. Article I (transparent *arr integration)
  forbids us from picking a feature that breaks a popular client.
- *Webseed-only for everything > 50 MiB*. Rejected: webseed has its own
  trade-offs (some clients treat webseed as advisory and still try peers
  first), and Article IX requires active-seed to work for any file size.

**Implementation notes**:
- Piece size ladder: `< 50 MiB → 256 KiB`, `50 MiB–1 GiB → 1 MiB`,
  `> 1 GiB → 4 MiB`. Store in `core/enums.py`.
- Background task writes to a pre-allocated file via `aiofiles` so the
  libtorrent file handle can mmap from the start.
- Producer-consumer coordination: a per-download `asyncio.Event` per piece
  boundary; libtorrent's `have_piece(piece)` callback is fired after each
  piece is fully flushed to disk.
- On source-side 5xx/network blip: abort the piece, retry with HTTP range
  resumption (`Range: bytes=X-`); libtorrent's piece state remains
  `not-have` until retry succeeds.

---

## R-4 — Internet Archive file-preference selector

**Decision**: Codify the IA file-preference ladders from the spec into a
`dict[MediaType, list[FilePreference]]` module-level constant in
`grabarr/adapters/internet_archive.py`. Each `FilePreference` is `(format
string, score int, ext hint str | None)`. At search time, fetch the item's
`/metadata/{identifier}` JSON, iterate its `files` array, match each file
against the ladder, keep the highest-scoring match, return that file's
`download_url` as the search result.

**Rationale**: The spec mandates nine distinct ladders (ebook, audiobook,
comic, magazine, music, software, paper, game_rom, video) with a total of
~40 scored rows. Hard-coding these as data, not code, keeps the adapter
readable and the ladders auditable. The `ext hint` is a tiebreaker when IA
lists multiple files with the same `format` string but different extensions
(e.g. several `128Kbps MP3` files at different bitrates).

**Rationale for the scoring values**: The values in the spec are
pre-validated by the user against IA's real-world `format` vocabulary (they
were extracted from the feature prompt). Changing them is a scope decision,
not a technical one.

**Alternatives considered**:
- *Use IA's `ia` Python SDK*. Rejected: extra dependency with its own HTTP
  client, breaks the `httpx`-only policy, and the raw `advancedsearch.php`
  + `metadata` JSON endpoints cover 100 % of what we need.
- *Defer file selection to profile-level filters*. Rejected: the preferred
  format for an ebook profile is the same across all IA requests, so moving
  it to profiles would force every user to re-enter the same ladder.

**Blacklist implementation**: A flat `set[str]` of IA `format` values to
skip ({ "Metadata", "Item Tile", "Thumbnail", "JPEG Thumb", "Spectrogram",
"Item Image", "Reviews", "JSON", "Web ARChive ZIP" }), consulted before
scoring.

**CDL filter**: Every `advancedsearch.php` query appends
` AND -access-restricted-item:true`.

---

## R-5 — Bypass session cache invariants

**Decision**: Store cache entries as `(domain, user_agent, cf_clearance_cookie,
issued_at, expires_at)` in a single `bypass_sessions` table. Entries expire
at `issued_at + 30 min`. Cache hit: attach the cookie and User-Agent to the
next `httpx` request; on 200 response, bump `issued_at` by 5 minutes (sliding
TTL, capped at the original 30-minute hard ceiling). Cache miss: invoke the
configured bypasser, persist the new entry. Invalidation: any direct request
to the domain that returns 403, 503, or a Cloudflare-challenge HTML body
(detected by `<title>Just a moment...</title>` in the response body) MUST
delete the entry before re-invoking the bypasser.

**Rationale**: The spec says 30-minute TTL (FR-010) but does not resolve
what happens when the cookie is revoked mid-window. A sliding TTL inside a
hard ceiling lets busy deployments benefit from warm cookies while still
bounding how long a stale cookie can linger. The 5-minute slide and 30-
minute ceiling match Cloudflare's own documented cf_clearance behaviour in
published research.

**Alternatives considered**:
- *Purely time-based TTL with no invalidation*. Rejected: a 403 response
  that indicates Cloudflare has revoked the clearance would otherwise sit
  in cache for up to 30 minutes, causing a burst of failed requests.
- *Probe-based freshness (HEAD to a cheap path every N requests)*. Rejected:
  wastes requests against the source's rate limit for no operational gain
  vs the 403-reactive invalidation above.

**Implementation notes**:
- Challenge-HTML detection is handled by `grabarr/bypass/service.py`'s post-
  request interceptor; the vendored bypass modules already handle the
  challenge flow correctly when invoked.
- Cache is keyed by bare domain (e.g. `annas-archive.org`), not scheme or
  port; cookies are domain-scoped anyway.

---

## R-6 — Profile → Torznab category mapping

**Decision**: Ship a Newznab category table as `grabarr/core/categories.py`
with the canonical Newznab codes used by Prowlarr's book/audiobook/music
presets: `7020` (eBook), `7030` (Comic), `7040` (Magazine), `7050`
(Audiobook — legacy), `7060` (eBook / academic / "other"), `3030`
(Audiobook), `3040` (Lossless), `3010` (Music MP3), `1070` (PC ROMs), etc.
Each seeded default profile declares its `newznab_categories` list from
this table; Prowlarr uses those codes to route traffic to the correct *arr
app.

**Rationale**: Prowlarr's indexer-import expects Newznab-standard category
codes; inventing our own would break Article I. Prowlarr's own Generic
Torznab import form pre-fills categories from the caps response the
indexer publishes, so getting these right is what makes SC-002 ("all seven
profiles pass Prowlarr's test first try") achievable.

**Alternatives considered**:
- *Free-form category strings*. Rejected: Prowlarr rejects them.
- *Auto-derive categories from `MediaType`*. Rejected: `ebook` alone needs
  both 7020 and 7060 depending on whether it is general or academic.

**Source of truth**: Prowlarr's `IndexerCategory.cs` and the Newznab
specification at newznab.com/api/2.0 (both MIT-licensed/permissive).

---

## R-7 — Admin UI HTMX polling cadence

**Decision**: Dashboard active-downloads table polls via
`hx-trigger="every 2s"` (matching the spec). Sources page health dots poll
every 10 s. Notifications and Stats pages do not poll (rendered on
navigation). Theme toggle uses `localStorage` persisted client-side, no
round-trip.

**Rationale**: 2 s is tight enough to feel real-time without pounding the
server when 10 tabs are open; SC-014 (50 concurrent searches, 10 concurrent
downloads) has headroom for ~50 active tabs each polling at 2 s = 25 RPS,
which FastAPI handles trivially.

**Alternatives considered**:
- *Server-Sent Events (SSE)*. Rejected: HTMX supports SSE but this project's
  traffic pattern is bounded-cadence polling; SSE adds connection-lifecycle
  complexity with no observable benefit for a single-tenant homelab tool.
- *WebSockets*. Rejected: same reason; also complicates the reverse-proxy
  story (WS requires `Upgrade` header passthrough).

---

## R-8 — Config-file hot-reload policy

**Decision**: Mutable settings (Apprise URLs, download mode, torrent mode,
rate limits, bypass mode, IA contact email, timeout values, retention
windows) are stored in SQLite's `settings` key-value table and modified
exclusively via the admin UI / API — NOT reloaded from `config.yaml` at
runtime. `config.yaml` is read ONCE at startup to populate the `settings`
table's initial row for a fresh install; on subsequent starts it is
ignored except for credentials that MUST live in files/env (AA member key,
Z-Lib cookies, any non-UI-facing secrets).

**Rationale**: The spec requires "no service restart required for any
change" (FR-011, and by extension FR-009's bypass mode and FR-017's
download mode). Two-way sync between a YAML file and a database is a
notorious footgun. Picking one source of truth per setting — UI-editable
settings live in SQLite, boot-time-only credentials live in
`config.yaml`/env — keeps the mental model clean.

**Alternatives considered**:
- *Auto-write back to `config.yaml` when the UI saves*. Rejected: Docker
  volumes + YAML round-tripping loses comments and reorders keys, and a
  crash mid-write leaves the file corrupt.
- *Watch `config.yaml` for changes via inotify*. Rejected: doesn't
  handle reverse edits from the UI; two-way reconciliation loops.

**Implementation notes**:
- Add a `_config_versioning` row in `settings` so Alembic migrations can
  trigger settings-table schema updates on upgrade (FR-038).
- Startup sequence: (1) load `config.yaml`, (2) run Alembic migrations,
  (3) if `settings` is empty, seed from `config.yaml`, else leave
  `settings` untouched and only re-read credentials from `config.yaml`.

---

## R-9 — `uv`-based dependency management and Docker build

**Decision**: Use `uv` for lockfile generation (`uv lock`) and install
(`uv sync --frozen`). The Dockerfile copies `pyproject.toml` + `uv.lock`
first, runs `uv sync --frozen --no-install-project`, then copies source
and runs `uv sync --frozen`. Tailwind is built via the standalone
`tailwindcss` binary (downloaded in a builder stage) so Node.js never
enters the runtime image.

**Rationale**: `uv` is mandated by the constitution. A standalone Tailwind
binary keeps the runtime image free of Node.js (saves ~200 MB). The
two-stage `uv sync` pattern maximises Docker layer caching — a lock-only
change does not rebuild the source-copy layer.

**Alternatives considered**:
- *Poetry*. Rejected: constitution mandates uv.
- *Node-based Tailwind build*. Rejected: ~200 MB of runtime bloat for a
  build-time tool.
- *PostCSS-only with no Tailwind*. Rejected: Tailwind is constitution-
  mandated for the UI CSS; we ship compiled CSS, not raw Tailwind.

---

## R-10 — libtorrent Python binding availability on `python:3.12-slim`

**Decision**: Install `libtorrent` via Debian `apt-get install
python3-libtorrent=2.0.*` in the Docker image. The `python:3.12-slim`
base uses Debian 12 (bookworm), whose `python3-libtorrent` package is
built against the system Python (3.11), NOT against Python 3.12 from
python.org. We therefore ship a builder stage that compiles the
`libtorrent` Python binding from source against the runtime image's
Python 3.12, caching the compiled `.so` in a layer for fast rebuilds.

**Rationale**: No `pip install libtorrent` package exists (libtorrent's
Python binding is a C++ extension bound with Boost.Python, published
only as a source dist; binary wheels are unofficial and often stale).
Compiling from source is slow (~3 min) but the resulting `.so` is
~12 MB and cacheable. This is the only hard build-time cost in the
image.

**Alternatives considered**:
- *Ship a `python:3.11-slim` base to match Debian's libtorrent*.
  Rejected: constitution mandates Python 3.12+.
- *Use the third-party `pylibtorrent` PyPI wheel*. Rejected:
  unmaintained, last release trails upstream libtorrent by 18 months
  at time of writing, and mixes v1/v2 API in confusing ways.
- *Use `libtorrent-rasterbar-2` apt package only (no Python binding)
  and call via `cffi`*. Rejected: re-implements the binding.

**Implementation notes**:
- Builder stage: `apt-get install -y build-essential python3-dev
  libboost-python-dev libboost-system-dev libtorrent-rasterbar-dev`
  then `pip wheel libtorrent==2.0.*` against a local vcpkg or apt-
  shipped headers.
- Runtime stage: `apt-get install -y libboost-python1.83.0
  libboost-system1.83.0 libtorrent-rasterbar2.0` then `pip install
  /wheels/libtorrent-*.whl`.

---

## R-11 — SeleniumBase availability and CI policy

**Decision**: `seleniumbase` is declared as an *optional* dependency group
in `pyproject.toml` (`[project.optional-dependencies] internal-bypasser`).
The default image installs it (so operators can flip to
`bypass.mode=internal` without rebuilding), but does NOT install Chromium.
CI smoke-tests `internal_bypasser.py` by importing the module only — no
browser launch (spec FR-040 explicitly permits skipping the browser
launch in CI).

**Rationale**: SeleniumBase + a bundled browser adds ~500 MB to the image
and is disabled by default per the bypass clarification. Operators who
opt in must accept one extra `docker exec grabarr playwright install
chromium`-equivalent step (documented in the quickstart).

**Alternatives considered**:
- *Ship Chromium in the default image*. Rejected: doubles the image size
  for a feature ~95 % of users will never enable.
- *Make `internal-bypasser` a separate Docker tag (`grabarr:with-
  selenium`)*. Rejected: two tags to maintain, two compose files to
  document, for a minor optimisation.

---

## R-12 — FlareSolverr version pinning

**Decision**: `docker-compose.example.yml` pins
`ghcr.io/flaresolverr/flaresolverr:3.x` (latest stable major). The
Grabarr app's bypass service detects FlareSolverr version via the
`/` endpoint's JSON health response and refuses to use an
incompatible version (< 3.0.0 has a different solver protocol), logging
a clear error in Sources page → health reason.

**Rationale**: FlareSolverr occasionally breaks its protocol between
majors. Pinning to 3.x matches the vendored Shelfmark bypass expectation
and gives operators a clear upgrade path.

**Alternatives considered**:
- *Pin to `:latest`*. Rejected: breaks on FlareSolverr major bumps with
  no warning.
- *Auto-adapt to any version*. Rejected: infinite protocol-branching
  complexity.

---

## R-13 — Default per-media-type output path templating

**Decision**: Output paths are configurable per MediaType via Jinja2-style
templates in Settings → Paths. Defaults: `/downloads/ready/{media_type}/
{profile_slug}/{sanitized_title}_{external_id}/{filename}`. The
`sanitized_title` uses the vendored `grabarr.vendor.shelfmark.core.naming`
sanitizer.

**Rationale**: The template style is familiar to *arr users who already
configure Sonarr/Radarr naming schemes. Using the vendored sanitizer
keeps naming decisions in one place (Article III).

**Alternatives considered**:
- *Flat `/downloads/ready/` for everything*. Rejected: a single operator-
  year's history makes the directory unusable.
- *Hash-based subdirectories*. Rejected: makes manual inspection hard.

---

## R-14 — Search-result quality scoring

**Decision**: Each `SearchResult` carries a `quality_score: float`
computed by the adapter. Base scoring rubric (Grabarr-side, applied
uniformly):

| Signal | Score contribution |
|--------|--------------------|
| Format preference match (per MediaType ladder) | 0–100 |
| Language preference match (full / partial / none) | 0 / –20 / –40 |
| Source weight (profile-level) | × (0.1–2.0 multiplier) |
| Has ISBN / identifier | +10 |
| Size within min/max window | +5 |
| Size out of window | result REJECTED |
| Title fuzzy-match score against query | 0–40 |

The orchestrator applies the source weight multiplier; adapters compute
the other components. Final scores are sorted descending; ties broken
by source-order position in the profile.

**Rationale**: Some scoring rubric is required for `aggregate_all` mode
(FR-013) to rank cross-source results. Keeping the rubric documented
here — not hidden in code — makes SC-002 (Prowlarr test pass) debuggable
when a wrong result beats a right one.

**Alternatives considered**:
- *Source-native scores only, no Grabarr normalization*. Rejected:
  Shelfmark's AA scoring and IA's advancedsearch scoring use different
  scales (0–1 vs 0–100 vs boolean "relevance").
- *Machine-learned ranker*. Rejected: out of scope for a homelab
  tool.

---

## R-15 — Alembic migration naming and ordering

**Decision**: Migration filenames use `YYYYMMDD_HHMM_<slug>.py` (human-
sortable, timestamp-prefixed). Every migration is reversible. Data
migrations live alongside schema migrations but are idempotent (SELECT
+ INSERT ON CONFLICT DO NOTHING), so re-running them is safe. The first
migration creates all tables; subsequent migrations are small + focused.

**Rationale**: FR-038 mandates migrations on startup and FR-039 mandates
state preservation across upgrades, so reversibility is both a safety
net and a requirement.

**Alternatives considered**:
- *Sequential integer naming*. Rejected: merge conflicts in team setups
  (though v1.0 is single-dev, keep the discipline for later).

---

## References

- **Shelfmark upstream**: https://github.com/calibrain/calibre-web-
  automated-book-downloader (MIT). Vendoring commit SHA to be recorded in
  `grabarr/vendor/shelfmark/ATTRIBUTION.md` during implementation.
- **Torznab spec**: https://torznab.github.io/spec-1.3-draft/ (cap fields,
  category codes, RSS extensions).
- **Newznab category reference**:
  https://github.com/Prowlarr/Prowlarr/blob/develop/src/NzbDrone.Core/
  Indexers/Newznab/NewznabCategory.cs (reference only; we do not copy
  source).
- **BEP-3 (BitTorrent Protocol Specification)**:
  http://bittorrent.org/beps/bep_0003.html.
- **BEP-19 (WebSeed — GetRight style)**:
  http://bittorrent.org/beps/bep_0019.html.
- **Internet Archive advancedsearch docs**:
  https://archive.org/advancedsearch.php.
- **FlareSolverr README**: https://github.com/FlareSolverr/FlareSolverr
  (v3.x protocol).
