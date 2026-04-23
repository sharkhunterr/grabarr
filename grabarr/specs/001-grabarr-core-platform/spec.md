# Feature Specification: Grabarr Core Platform — Full Release (v1.0)

**Feature Branch**: `001-grabarr-core-platform`
**Created**: 2026-04-23
**Status**: Draft
**Input**: User description: "Grabarr Core Platform — Full Release. A multi-source
media indexer and download bridge that exposes Anna's Archive, LibGen, Z-Library
and Internet Archive as Torznab indexers for the *arr ecosystem. ~60% vendored
from Shelfmark, ~40% new Grabarr-specific code. See constitution v1.0.0."

## Clarifications

### Session 2026-04-23

- Q: Default download strategy for a fresh install (before the operator changes it)? → A: `sync` — download the full file, then return the torrent.
- Q: Default bypass mode for a fresh install? → A: `external` — FlareSolverr only; internal bypasser is opt-in.
- Q: When is a downloaded file under `/downloads/ready/{token}/{filename}` removed from disk? → A: When the seed-retention window (default 24 h from torrent generation, configurable) expires; the 30-day history row is kept for observability.
- Q: Which endpoints require a reverse proxy vs which must be publicly reachable? → A: All endpoints are equally unauthenticated by Grabarr itself (except the per-profile API key on `/torznab/{slug}/api`). Grabarr assumes network isolation; if the operator wants edge auth, they put a reverse proxy in front of whichever subset they choose. No in-app split between admin and public surfaces.
- Q: How is notification spam during source flapping prevented? → A: 10-minute cooldown per `(source, event_type)` — first transition fires, repeats within the window are coalesced. `quota_exhausted` has an until-midnight-UTC cooldown (matching the quota reset boundary).

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Homelab Deployment and First-Run Indexing (Priority: P1)

A self-hosted user has a working *arr stack (Prowlarr + Bookshelf + Deluge) and
wants Anna's Archive, LibGen, Z-Library, and Internet Archive to appear as
additional Torznab indexers. They clone the project, run `docker-compose up -d`,
open the admin UI, paste one of the pre-generated Prowlarr import blobs into
Prowlarr, and from that point on their existing "wanted" books are satisfied
through Grabarr without any code change on either side.

**Why this priority**: This is the project's reason for existing. Without this
journey working end-to-end, nothing else matters. It also exercises the
critical path through every subsystem — vendored Shelfmark cascade, bypass
service, download manager, torrent generation, Torznab endpoint, and Prowlarr
integration — so delivering it as MVP validates the architecture.

**Independent Test**: Deploy a clean Grabarr + FlareSolverr pair via the
provided compose file; open the UI; copy the exported Prowlarr JSON for the
`ebooks_general` profile into a test Prowlarr instance; mark a book as
"wanted" in Bookshelf; verify the book is searched, grabbed, downloaded, seeded
to Deluge, imported, and renamed — entirely through the standard *arr UI with
no Grabarr-specific client plugin.

**Acceptance Scenarios**:

1. **Given** a host with Docker and Docker Compose installed, **When** the
   operator runs `docker-compose up -d` using the supplied example file and
   opens the admin UI, **Then** the dashboard is reachable within 60 seconds
   of the first boot, the seven default profiles are pre-seeded, and the
   `Copy Prowlarr Config` action on each profile produces a valid JSON blob
   that Prowlarr accepts on first import.
2. **Given** the `ebooks_general` Torznab endpoint has been added to Prowlarr
   and synced to Bookshelf, **When** a "wanted" book is marked in Bookshelf,
   **Then** Grabarr returns a result from the first responsive source in the
   cascade, produces a `.torrent` that Deluge accepts, delivers the file, and
   Bookshelf imports and renames it — all without manual intervention.
3. **Given** a first-time search against Anna's Archive with no cached
   Cloudflare clearance, **When** the user triggers the search, **Then**
   FlareSolverr resolves the challenge and returns results within 30 seconds;
   a subsequent search against the same domain returns in under 2 seconds.

---

### User Story 2 — Reliable Large Downloads Without *arr Timeouts (Priority: P1)

A user wants a modern audiobook (≥ 500 MB) whose only reachable source is
Anna's Archive's slow tier, which enforces a countdown and streams at a
throttled rate. Bookshelf's default HTTP grab would time out long before the
file finished. The user needs Grabarr to hand a seedable torrent back
immediately, stream bytes into it in the background, and let Deluge pull
pieces as they arrive.

**Why this priority**: Large audiobooks and high-resolution scans are the
exact content that *arr users most want from shadow libraries. If Grabarr
cannot deliver them without the *arr timing out, the project does not solve
its actual problem. This story is P1 because it tests the asynchronous
streaming download mode, which is the feature that differentiates Grabarr
from a naive HTTP grabber.

**Independent Test**: Queue a known-large audiobook via the
`audiobooks_general` profile; confirm a valid `.torrent` returns within 2
seconds; confirm Deluge begins receiving pieces within 60 seconds; confirm
the download completes at the source's natural rate without Bookshelf or
Deluge reporting a timeout; confirm the imported file passes magic-byte
verification.

**Acceptance Scenarios**:

1. **Given** a profile configured with `download_mode = async_streaming`,
   **When** a grab is triggered for a 500 MB file, **Then** Grabarr returns
   the torrent within 2 seconds, Deluge starts receiving bytes within 60
   seconds, and the download completes successfully even if the source
   throttles to 200 KB/s.
2. **Given** the hybrid mode is active with a 50 MB threshold, **When** a 10
   MB file is grabbed, **Then** the sync path is taken; **When** a 200 MB
   file is grabbed, **Then** the async-streaming path is taken; both
   resulting torrents are valid and accepted by Deluge.
3. **Given** an in-flight asynchronous download, **When** the user toggles
   the global torrent mode in Settings, **Then** the in-flight download
   completes under the original mode and the next new download uses the new
   mode (no mid-flight reconfiguration).

---

### User Story 3 — Profile-Driven Multi-Source Routing (Priority: P2)

A user wants different media types to hit different sources with different
priorities — for example, public-domain ebooks should go to Internet Archive
first, modern ebooks should prefer Anna's Archive, and ROMs should only ever
hit Internet Archive's game collections. They configure this through the UI
without editing code and without restarting the service.

**Why this priority**: Once the base flow works, unlocking profile
customization is what turns Grabarr from a single-purpose bridge into a
generally useful indexer. It is not an MVP requirement — the seven seeded
defaults cover the common cases — but power users need it to avoid
workarounds.

**Independent Test**: Using the UI, duplicate the `ebooks_general` profile;
rename it; change source order via drag-and-drop; add a French-language
filter; save; copy the new Torznab URL to Prowlarr; confirm the new indexer
appears, passes Prowlarr's test, and returns filtered results in Bookshelf.

**Acceptance Scenarios**:

1. **Given** the admin UI is open, **When** the user creates a new profile
   with a custom source order and a language filter, **Then** the profile is
   persisted, its Torznab endpoint is immediately live at `/torznab/{slug}/api`,
   and no service restart is required.
2. **Given** a profile with two sources in a specific order, **When** the
   first source is marked unhealthy, **Then** searches flow through to the
   second source without user action.
3. **Given** a profile in `aggregate_all` mode, **When** a search runs,
   **Then** results from every enabled source are concatenated, deduplicated
   by (title, author, year, format), and ranked by weight-adjusted quality
   score.

---

### User Story 4 — Outage Resilience and Notifications (Priority: P2)

The user is not watching dashboards. When FlareSolverr crashes, when Z-Library
cookies expire, when Z-Library's daily quota runs out, or when any source
becomes unhealthy, the user wants (a) Grabarr to automatically route around
the failure, (b) a push notification so they know about it, and (c) automatic
recovery when the condition clears.

**Why this priority**: Self-hosted operators do not babysit services. A
bridge that silently fails is worse than no bridge. P2 because a functioning
MVP can ship without notifications, but a stable v1.0 cannot.

**Independent Test**: Kill the FlareSolverr container; wait up to 60 seconds;
verify AA and Z-Lib show unhealthy in `/healthz` and the Sources page; verify
LibGen and IA still serve searches; verify an Apprise ping was sent; restart
FlareSolverr; verify AA and Z-Lib auto-recover within a minute and a
`source_recovered` notification fires.

**Acceptance Scenarios**:

1. **Given** FlareSolverr is unreachable, **When** a search targets a profile
   that requires bypass, **Then** the bypass-requiring sources are skipped
   cleanly; the non-bypass sources still serve results; an Apprise
   notification fires within 60 seconds.
2. **Given** Z-Library returns a login page (cookie expired), **When** the
   adapter detects this, **Then** the adapter is marked `cookie_expired`,
   Apprise fires, and the UI surfaces the reason clearly on the Sources page.
3. **Given** the Z-Library daily quota is exhausted, **When** additional
   searches are attempted, **Then** they return empty without consuming
   further quota; a `quota_exhausted` notification fires once per day; the
   quota resets at midnight UTC and searches resume automatically.

---

### User Story 5 — Developer Extensibility (Priority: P3)

A developer wants to add a new source adapter (for example, a Welib-only
endpoint or a hypothetical future aggregator) without touching any core code,
registry, or configuration UI. Adding a new source must be a single new file.

**Why this priority**: The project's long-term value depends on being easy to
extend. P3 because v1.0 ships with the four main sources; new adapters can
wait for v1.1.

**Independent Test**: Add a new wrapper file in `grabarr/adapters/` with the
`@register_adapter` decorator, declaring its supported media types; restart
the service; confirm the new source appears in the Sources UI, is usable in
profile builder, and can serve search/download without editing any other
file.

**Acceptance Scenarios**:

1. **Given** a new adapter file in `grabarr/adapters/` that implements the
   `SourceAdapter` protocol and uses `@register_adapter`, **When** the
   service starts, **Then** the adapter auto-registers and is usable in all
   profile-related UI without further code changes.
2. **Given** a hypothetical Welib wrapper (whose underlying logic is already
   vendored from Shelfmark), **When** the wrapper is written, **Then** it is
   no more than ~150 lines and requires no changes outside its own file.

---

### Edge Cases

- A source returns an HTML login page instead of a file: the adapter's
  cookie-expired detection fires, the download is rejected by Content-Type
  and magic-byte checks, no partial file reaches the torrent client, the
  user is notified.
- Anna's Archive slow tier countdown exceeds the 600-second cap: the cascade
  moves on to the next sub-source (libgen → zlib → ipfs) without blocking
  the request indefinitely.
- A file downloaded from Internet Archive is actually CDL-restricted: magic-
  byte verification rejects it, the download is marked failed, the user sees
  a clear error on the Downloads page.
- Two concurrent grabs request the same file: the download manager
  de-duplicates by external_id so the source is hit only once; both torrents
  reference the same underlying file.
- The user disables all sources in a profile, then triggers a search: the
  Torznab response is a valid empty-result XML, not a 500.
- FlareSolverr takes longer than the per-request timeout to return: the
  request is abandoned, the source is marked degraded, other sources still
  answer, the bypass cache is not poisoned.
- The service is killed mid-seed: on restart, the libtorrent session
  restores seed state and the internal tracker re-registers info-hashes;
  Deluge's existing torrents keep working.
- Z-Library quota resets during an in-flight request: the request completes
  under the pre-reset quota; post-reset requests see the new counter.
- Magic-byte check would pass but the file is a ZIP bomb: the configured
  max-size cap (default 5 GB) rejects it before it fills disk.
- The admin UI is loaded on a 360 px-wide phone in landscape: navigation
  collapses to a hamburger, tables become cards, no horizontal scroll
  appears.

## Requirements *(mandatory)*

### Functional Requirements

#### Sources and Vendoring

- **FR-001**: The system MUST expose four content sources — Anna's Archive,
  LibGen, Z-Library, and Internet Archive — each via a dedicated adapter in
  `grabarr/adapters/`.
- **FR-002**: The Anna's Archive, LibGen, and Z-Library adapters MUST be
  thin wrappers over vendored Shelfmark code in
  `grabarr/vendor/shelfmark/release_sources/direct_download.py`; they MUST
  NOT reimplement the cascade, URL-extraction strategies, countdown
  handling, mirror rotation, or failure thresholds. The Internet Archive
  adapter MUST be new Grabarr-specific code.
- **FR-003**: Vendoring MUST follow the mandatory procedure defined in
  Constitution §"Vendoring Procedure": file-for-file copy, MIT headers
  preserved, `ATTRIBUTION.md` present with upstream commit SHA, imports
  rewritten from `shelfmark.X` to `grabarr.vendor.shelfmark.X`, logic
  untouched.
- **FR-004**: For Anna's Archive, every behaviour listed in Constitution
  Article VII MUST be preserved by delegation to vendored code: sub-source
  taxonomy (`aa-fast`, `aa-slow-nowait`, `aa-slow-wait`, `aa-slow`,
  `libgen`, `zlib`, `welib`, `ipfs`), failure threshold of 4, CF-bypass
  gating, member-key fast path, free-mode cascade, multi-strategy URL
  extraction (eight distinct strategies), countdown live wait (capped at
  600 s), AA-discovered external mirrors, round-robin rotation, and status
  callbacks.
- **FR-005**: The Z-Library adapter MUST add (on top of the vendored
  download logic) daily quota tracking persisted in the database and reset
  at midnight UTC, and cookie-expired detection that marks the source
  unhealthy and fires a `cookie_expired` notification.
- **FR-006**: The Internet Archive adapter MUST filter out
  `access-restricted-item:true` results, select the best file per media
  type using a documented preference ladder (EPUB > PDF > DjVu for ebooks;
  FLAC > VBR MP3 > 128 kbps for music; ISO > ZIP > ROM-file for ROMs;
  etc.), blacklist non-content formats (Metadata, Item Tile, Thumbnail,
  etc.), expose collection-aware search filters, and send a User-Agent that
  includes a configurable contact email per IA policy.
- **FR-007**: The adapter registry MUST auto-discover every file in
  `grabarr/adapters/` that uses `@register_adapter` at startup; no global
  list may be hand-edited to add an adapter.
- **FR-008**: Every adapter MUST conform to the `SourceAdapter` protocol,
  exposing `id`, `display_name`, `supported_media_types`,
  `requires_cf_bypass`, `supports_member_key`, `supports_authentication`,
  `search(...)`, `get_download_info(...)`, `health_check(...)`,
  `get_config_schema(...)`, and `get_quota_status(...)`.

#### Bypass Service

- **FR-009**: The system MUST expose `grabarr/bypass/service.py` as a thin
  async service that selects between vendored `external_bypasser.py`
  (FlareSolverr client) and vendored `internal_bypasser.py` (SeleniumBase
  fallback) based on `config.bypass.mode` set to `external`, `internal`, or
  `auto`. In `auto`, external is tried first; on failure, the service
  falls back to internal. The **shipping default** is `external` —
  matching the compose file that ships FlareSolverr as a sidecar; the
  internal bypasser is opt-in.
- **FR-010**: The bypass service MUST maintain a persisted session cache
  keyed by domain, storing `(cf_clearance, user_agent)` with a 30-minute
  TTL; cache hits MUST bypass the full bypass flow; the cache MUST be
  invalidated when a subsequent direct request returns 403 or 503.

#### Profiles and Orchestration

- **FR-011**: The system MUST persist Profiles with the full schema
  (`slug`, `name`, `description`, `media_type`, `sources`, `filters`,
  `mode`, `newznab_categories`, `download_mode_override`,
  `torrent_mode_override`, `enabled`, `api_key_hash`, `is_default`).
  Profiles MUST support full CRUD through both the UI and `/api/profiles/*`
  endpoints, with no service restart required for any change.
- **FR-012**: The system MUST seed seven default profiles on first launch:
  `ebooks_general`, `audiobooks_general`, `ebooks_public_domain`,
  `roms_all`, `papers_academic`, `music_general`, `comics_general`, with
  the source compositions, weights, filters, and Newznab categories
  specified in the feature input. Default profiles MUST NOT be deletable
  (they may be disabled).
- **FR-013**: The Search Orchestrator MUST iterate profile sources in
  order, skipping disabled entries, unhealthy adapters, and
  member-required entries without a configured key; apply per-entry
  timeouts and per-profile filters; apply weight multipliers to result
  quality scores; support `first_match` and `aggregate_all` modes;
  deduplicate results by `(normalized_title, author, year, format)`;
  cap at 100 results; and cache by `(normalized_query, profile_slug,
  filters_hash)` for 15 minutes.

#### Torznab Surface

- **FR-014**: The system MUST expose one independent Torznab endpoint per
  profile at `/torznab/{slug}/api`, supporting `t=caps`, `t=search`,
  `t=book`, `t=movie`, and `t=music` queries; and a download route at
  `/torznab/{slug}/download/{token}.torrent`.
- **FR-015**: Torznab responses MUST include the standard RSS fields
  (title, description, size, category, pubDate, link, enclosure with
  `length` and `type="application/x-bittorrent"`, guid) and
  Torznab-specific attributes (`seeders=1`, `peers=0`,
  `downloadvolumefactor=0`, `uploadvolumefactor=1`, `infohash`).
- **FR-016**: The Torznab endpoint MUST authenticate requests via a
  per-profile bcrypt-hashed API key; missing or invalid keys MUST receive
  401 with `WWW-Authenticate`. API keys MUST be revocable and
  regeneratable through the UI.

#### Download Manager

- **FR-017**: The system MUST implement three download strategies —
  `sync`, `async_streaming`, and `hybrid` — switchable globally with
  per-profile override. The **shipping default** for a fresh install is
  `sync`. The hybrid strategy MUST default to a 50 MB threshold (sync
  below, async-streaming above) when the operator selects it.
- **FR-018**: Sync downloads MUST stream the source file to
  `/downloads/incoming/{token}/{filename}`, run all integrity checks,
  move to `/downloads/ready/{token}/{filename}` on success, and return
  the path plus metadata. The default per-profile timeout is 5 minutes.
- **FR-019**: Async-streaming downloads MUST return the torrent within
  500 ms of the download request, run the HTTP download in a background
  task that also serves byte ranges to the torrent client, and tolerate
  client disconnects and source-side range resumption.
- **FR-020**: Every downloaded file MUST be verified before handover:
  Content-Type check (reject HTML/JSON/XML), size check against
  configured min/max, magic-byte check per format (EPUB, PDF, MOBI, MP3,
  FLAC, ZIP/CBZ, ISO as defined in Constitution Article XI), and
  max-size cap (default 5 GB).
- **FR-021**: Post-processing hooks MUST be configurable per media type:
  ZIP/7Z/RAR extraction for `game_rom` and `software`, M3U playlist
  generation for multi-disc audio.

#### Torrent Server

- **FR-022**: The system MUST implement two torrent modes — `active_seed`
  (default) and `webseed` (BEP-19) — switchable globally with per-profile
  override. The in-flight semantics MUST ensure: switching the mode does
  not disrupt in-flight downloads; new downloads after the switch use the
  new mode.
- **FR-023**: In `active_seed` mode, the system MUST run an internal HTTP
  tracker (default port 8999, configurable) that tracks peers with a
  30-minute TTL, supports compact and non-compact announce responses, and
  run an in-process libtorrent session (DHT off, LSD off, PEX restricted
  to the internal set, listen ports 45000–45100 configurable, max 100
  concurrent seeds, state persisted across restarts).
- **FR-024**: In `webseed` mode, the system MUST emit torrents whose
  webseed URL points to Grabarr's own HTTP endpoint
  (`/torznab/{slug}/seed/{token}`), which MUST support HTTP range
  requests. Tokens MUST be valid for 24 hours.

#### Admin UI

- **FR-025**: The admin UI MUST include seven distinct views: Dashboard
  (active + recent downloads, per-source stats), Profiles (card list +
  edit form with drag-and-drop source ordering, weight sliders, inline
  test), Sources (health status, per-adapter config, rate-limit controls,
  quota panel), Settings (bypass, downloads, torrents, paths, metadata,
  backup), Downloads History (paginated, per-entry detail, retry, delete),
  Notifications (Apprise URLs, event map, generic webhook), Stats (charts,
  Prometheus URL, CSV/JSON export).
- **FR-026**: The UI MUST be fully responsive from 360 px to 4K, fully
  keyboard-navigable, WCAG AA compliant, themable in light and dark with
  a user toggle, and include confirmation dialogs for destructive
  actions.
- **FR-027**: The UI MUST provide a `Copy Prowlarr Config` action per
  profile that downloads a JSON blob matching Prowlarr's Generic Torznab
  import schema; an equivalent API endpoint
  `GET /api/prowlarr-config?profile={slug}` MUST be available for
  automation.

#### Observability and Notifications

- **FR-028**: The system MUST expose Prometheus metrics at `/metrics`
  including per-source counters (searches, downloads, bypass invocations,
  errors), histograms (response duration, download duration, bypass
  duration), and gauges (active downloads by mode, seeded torrents, queue
  depth, source health, quota remaining). The total distinct series MUST
  exceed 50 under normal operation.
- **FR-029**: Logging MUST default to console-colored output, support
  JSON format via `LOG_FORMAT=json`, include correlation IDs per request,
  apply a redaction filter for secrets, and support per-module level
  overrides.
- **FR-030**: The system MUST expose `GET /healthz` returning 200 OK or
  503, with a JSON body reporting per-subsystem status (database,
  flaresolverr, libtorrent_session, internal_tracker, each adapter).
- **FR-031**: The system MUST integrate with Apprise for the event
  catalogue `download_completed`, `download_failed`, `source_unhealthy`,
  `source_recovered`, `quota_exhausted`, `bypass_failed`,
  `cookie_expired`. Each event MUST be mappable to any subset of
  configured Apprise URLs, be delivered fire-and-forget with up to 3
  retries on exponential backoff, and include rich content (title, body,
  severity, metadata).
- **FR-031a**: Notification dispatch MUST apply **flap suppression**
  per `(source, event_type)` key: the first event fires immediately;
  subsequent events with the same key within a 10-minute window MUST
  be coalesced (not sent). `quota_exhausted` MUST use an
  until-midnight-UTC cooldown instead of 10 minutes, aligned with the
  quota-reset boundary. Coalesced events MUST still be recorded in the
  notification log with a `coalesced=true` flag for observability.
- **FR-032**: The system MUST provide a generic-webhook fallback with
  configurable headers and a Jinja2-templated JSON body for systems
  Apprise does not cover.

#### Security, Reliability, and Configuration

- **FR-033**: Authentication, OIDC, multi-user support, and role-based
  access MUST NOT be implemented (Constitution Article II). Grabarr
  itself treats every endpoint equally — no in-app distinction between
  "admin" and "public" surfaces, no per-path ACL. The **only** in-app
  auth is the per-profile bcrypt API key on `/torznab/{slug}/api`
  (FR-016). All other endpoints (admin UI, `/api/*`, `/metrics`,
  `/healthz`, `/announce`, `/seed/{token}`, `/download/*.torrent`) are
  served unauthenticated. The deployment assumption is network
  isolation (a homelab LAN or equivalent); if the operator wants edge
  authentication, they place a reverse proxy (Authentik, NPM, Traefik
  ForwardAuth) in front of whichever subset they choose. The default
  compose file does NOT ship such a proxy.
- **FR-034**: Every secret — API keys, Anna's Archive member keys,
  Z-Library cookies — MUST be stored exclusively in `config.yaml`
  (mounted volume) or environment variables; MUST NOT be logged; and
  MUST only be revealed in the UI on the Settings page and on explicit
  user action.
- **FR-035**: Every adapter MUST enforce a token-bucket rate limit. The
  defaults are: AA 30 req/min for search + 2 parallel downloads, LibGen
  60 req/min, Z-Library 10 req/min plus 10 downloads/day, Internet
  Archive 30 req/min.
- **FR-036**: A circuit breaker MUST mark any adapter unhealthy after 5
  consecutive failures; the adapter MUST be rechecked automatically 60
  seconds later. Adapter failures MUST NOT crash the service or any
  unrelated adapter.

#### Deployment

- **FR-037**: The system MUST ship a `Dockerfile` (base
  `python:3.12-slim`, libtorrent 2.0+ installed via apt, dependencies
  managed via `uv`, Tailwind CSS compiled at build time) and a
  `docker-compose.example.yml` that wires a Grabarr service and a
  FlareSolverr sidecar (ghcr.io/flaresolverr/flaresolverr:latest) on a
  shared network with volumes for `./config`, `./data`, `./downloads`.
- **FR-038**: On first run, the system MUST auto-generate a `config.yaml`
  from the template if missing, run Alembic migrations, seed the seven
  default profiles into an empty database, and log setup instructions.
  On upgrade, the system MUST run pending Alembic migrations and
  auto-migrate the config schema where possible.
- **FR-039**: Service state — profiles, downloads history (30-day
  retention), seed state, Z-Library quota counter, and bypass session
  cache — MUST survive a restart intact.
- **FR-039a**: Downloaded files under `/downloads/ready/{token}/{filename}`
  MUST be removed when the **seed-retention window** expires (default
  24 hours from torrent generation, configurable per profile and
  globally). The corresponding downloads-history row MUST be retained
  for the full 30-day window for observability. A background cleanup
  task MUST remove expired files and emit a log entry per removal.

#### Vendor Compatibility Tests

- **FR-040**: The test suite MUST include `tests/vendor_compat/` with
  coverage for: `test_external_bypasser.py` (FlareSolverr protocol mocked
  with `respx`), `test_internal_bypasser.py` (SeleniumBase import smoke
  test, no browser launch in CI), `test_fingerprint.py` (screen-size
  pool distribution), `test_mirrors.py` (AA mirror rotation and DNS
  fallback), `test_direct_download_aa.py` (cascade behaviours: fast
  path, countdown wait, failure threshold, sub-source classification —
  all against mocked HTML), `test_direct_download_libgen.py`,
  `test_direct_download_zlib.py`, `test_naming.py` (filename
  sanitization regressions). The suite MUST pass at 100 % against the
  vendored modules after import adaptation.

### Key Entities *(include if feature involves data)*

- **Profile**: A named routing recipe for a specific media type. Holds
  an ordered list of source entries (each with weight, timeout, enabled
  flag, member-requirement-skip flag), a `SearchFilters` block
  (languages, preferred formats, year range, size range, ISBN
  requirement, extra query terms), an orchestration mode (`first_match`
  or `aggregate_all`), Newznab category codes, optional per-profile
  download and torrent mode overrides, an enabled flag, a bcrypt-hashed
  API key, and an `is_default` flag for the seeded set.
- **SourceAdapter (registration record)**: The runtime registration of
  a source: `id`, `display_name`, supported media types, flags
  (`requires_cf_bypass`, `supports_member_key`,
  `supports_authentication`), latest health state, and a config schema
  used by the UI to render its settings pane.
- **Download**: A single grab request from a *arr client. Holds a
  token, the originating profile, the chosen source, the resolved
  external ID, the media type, the selected download mode, file
  metadata (name, size, content type, magic-byte verification result),
  timing breakdown, post-processing artefacts, and a status lifecycle
  (queued → downloading → ready → seeding → completed | failed).
- **Torrent / Seed Record**: A torrent the system generated, holding
  its info-hash, the associated Download, the mode it was generated
  under (`active_seed` or `webseed`), seeding state (persisted for
  libtorrent restoration), and a retention deadline.
- **Bypass Session Cache Entry**: A `(domain, cf_clearance,
  user_agent, expires_at)` tuple persisted across restarts; the
  backbone of bypass reuse and the reason sub-2-second warm searches
  are achievable.
- **Adapter Health Snapshot**: The rolling health view per adapter —
  status (healthy / degraded / unhealthy), reason (e.g.
  `cookie_expired`, `flaresolverr_down`, `quota_exhausted`),
  last-check timestamp, consecutive-failure count, and the timer for
  the next automatic recheck.
- **Notification Event**: A dispatched record tying an event type
  (`download_completed`, etc.) to an Apprise URL set (or webhook),
  with payload, dispatch timestamp, and delivery status.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A first-time operator can go from `docker-compose up -d`
  to a fully working Grabarr with seven profiles imported into Prowlarr
  in under 3 minutes.
- **SC-002**: All seven default profiles pass Prowlarr's indexer test
  on the first attempt when imported via the exported JSON blob.
- **SC-003**: A public-domain ebook wanted in Bookshelf is delivered
  (resolved → downloaded → imported → renamed) in under 20 seconds when
  Internet Archive serves the result.
- **SC-004**: A large audiobook (≥ 500 MB) via Anna's Archive slow tier
  in async-streaming mode begins flowing to the destination BitTorrent
  client within 60 seconds and completes without any *arr timeout.
- **SC-005**: A first-time search against Anna's Archive resolves
  through Cloudflare in under 30 seconds; subsequent searches against
  the same domain return in under 2 seconds.
- **SC-006**: When FlareSolverr goes down, bypass-requiring sources are
  marked unhealthy within 60 seconds, non-bypass sources continue
  serving, an Apprise notification is delivered within the same window,
  and automatic recovery completes within 60 seconds of FlareSolverr
  returning.
- **SC-007**: The admin UI renders functionally on a 360 px-wide
  viewport (no horizontal scroll, all actions reachable) and elegantly
  on a 4K display.
- **SC-008**: Adding a new source — given only the `SourceAdapter`
  protocol and the existing adapter files as reference — requires a
  single new file under `grabarr/adapters/` of approximately 150 lines
  for a Shelfmark-backed source, with zero edits elsewhere.
- **SC-009**: After a clean restart, every runtime artefact (profiles,
  30-day downloads history, active seed state, Z-Library quota counter,
  bypass session cache) is intact and the service resumes normal
  operation without manual steps.
- **SC-010**: `GET /metrics` returns more than 50 distinct Prometheus
  series under normal operation; the supplied Grafana dashboard JSON
  imports cleanly and displays data.
- **SC-011**: The `tests/vendor_compat/` suite passes at 100 %,
  confirming the vendored Shelfmark modules function identically after
  import adaptation.
- **SC-012**: Over 30 days of continuous uptime, memory usage remains
  bounded, log files rotate, database size remains stable under the
  30-day retention window, expired seeds are cleaned up, and expired
  bypass session-cache entries are purged — with no manual
  intervention.
- **SC-013**: The vendored Shelfmark subdirectory contains
  `ATTRIBUTION.md` with the full MIT license text, upstream commit SHA,
  and repository URL; every vendored file bears a header line citing
  its origin.
- **SC-014**: Under concurrent load, the system sustains 50 concurrent
  searches, 10 concurrent downloads, and 100 active seeds without
  performance degradation or resource exhaustion; the database stays
  under 500 MB for a full year of 30-day-window history.

## Assumptions

- FlareSolverr is available as a Docker sidecar in the target
  deployment; operators who cannot run FlareSolverr will accept that
  bypass-requiring sources (AA slow tiers, Z-Lib, Welib) are skipped
  unless they explicitly switch to `bypass.mode = internal`.
- Prowlarr's "Generic Torznab" indexer implementation is the canonical
  consumer; any future *arr client that claims Torznab compatibility is
  expected to work without Grabarr-specific shims.
- Grabarr itself is single-tenant and has no login screen. The deployment
  baseline is network isolation (homelab LAN). An external reverse proxy
  (Authentik, Nginx Proxy Manager, Traefik ForwardAuth) is OPTIONAL and
  operator-chosen; Grabarr makes no assumption that one is present and
  imposes no endpoint split.
- Operators are responsible for their own legal compliance when using
  the configured sources; Grabarr does not redistribute content and
  seeds only long enough to satisfy the *arr handoff contract.
- The Shelfmark upstream (`calibre-web-automated-book-downloader`)
  remains maintained and MIT-licensed at vendoring time. A future
  vendor-refresh workflow will re-pull and re-apply the import fixups;
  substantive upstream rewrites will require manual review per
  Constitution §Governance rule 5.
- Apprise and its transport dependencies are expected to be installed;
  the generic-webhook fallback exists for operators whose target
  messaging system is not covered by Apprise.
- SQLite is sufficient for the scale targets (50 concurrent searches,
  10 concurrent downloads, 100 seeds, 30-day history retention); no
  external RDBMS is required for v1.0.
- The host running Grabarr has outbound HTTPS to each source's primary
  domain(s) and can bind ports 8080 (UI/API), 8999 (tracker), and
  45000–45100 (libtorrent listening).
- Bookshelf, Readarr, Mylar3, Lazylibrarian, and Audiobookshelf consume
  the `.torrent` files Grabarr produces via their standard BitTorrent
  download clients — no Grabarr-aware client plugin is required.
