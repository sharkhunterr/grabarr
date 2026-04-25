# Changelog

All notable changes to this project will be documented in this file. See [standard-version](https://github.com/conventional-changelog/standard-version) for commit guidelines.

## 1.1.0 (2026-04-25)


### Features

* **aa:** 4-minute hard timeout on AA grabs with cascade cancellation ([abec4e3](https://github.com/sharkhunterr/grabarr/-/commit/abec4e393b9d3eadf740b5bae475ba2a3c77e7ae))
* **aa:** constrain Shelfmark cascade to AA-only during download ([99b87ec](https://github.com/sharkhunterr/grabarr/-/commit/99b87ecadd3c7f0ae7f7b2b1d1a7b3c2e71c4a28))
* **adapter:** Edge Emulation source — multi-platform retro ROMs ([af3943e](https://github.com/sharkhunterr/grabarr/-/commit/af3943e2ded08c99539e5579f594d646ea5347de))
* **adapter:** IA login + drop access-restricted filter when authenticated ([f6521f2](https://github.com/sharkhunterr/grabarr/-/commit/f6521f2d68d3c4a09386f9cc8939e67f70964f40))
* **adapter:** RomsFun full search + download via fetch_session countdown ([c9b2380](https://github.com/sharkhunterr/grabarr/-/commit/c9b238024a3c560ff49781d7679d384450bdbb98))
* **adapters:** thread query_hint through search → download for IA romsets ([8fc1dd5](https://github.com/sharkhunterr/grabarr/-/commit/8fc1dd52e80dec6749f0d7ba928d339d44cd6c02))
* **adapter:** Vimm's Lair source — search + dl3.vimm.net download ([2ff3c00](https://github.com/sharkhunterr/grabarr/-/commit/2ff3c0024d4edd871688581cccb881ebd06a926e))
* **api:** retry + cancel actions + /docs link + debug endpoint ([875b3cb](https://github.com/sharkhunterr/grabarr/-/commit/875b3cb10ca1aeccf03df79a4d479d817429d587))
* **bypass:** add click_and_capture click-driver + honour prefer_internal ([ce167d4](https://github.com/sharkhunterr/grabarr/-/commit/ce167d44ffb52ffc5600f9b170bf82b04c646429))
* **bypass:** expose fetch_html(url) for non-Shelfmark adapters + 003 spec ([fb275fb](https://github.com/sharkhunterr/grabarr/-/commit/fb275fb517737a9a0094142fee445b6e7112c921))
* delegate AA downloads to Shelfmark's full cascade ([f27bdf8](https://github.com/sharkhunterr/grabarr/-/commit/f27bdf8f6b54285ac09289f36dfc70bf32d5022f))
* docker image with chromium + xvfb bundled + cancel/retry buttons ([e482b19](https://github.com/sharkhunterr/grabarr/-/commit/e482b198f582ca314e27289429f8a0da3a0e12b2))
* **downloads:** accept raw ROM dumps in magic-byte verifier ([58ac02b](https://github.com/sharkhunterr/grabarr/-/commit/58ac02b517ecefea867b33c7421cc761df6df380))
* **downloads:** Clear-all UI + reset-downloads.sh ([642d61c](https://github.com/sharkhunterr/grabarr/-/commit/642d61c8cf1d813927560b312062b938592d10ed))
* **downloads:** split search tokens from download history ([7557eff](https://github.com/sharkhunterr/grabarr/-/commit/7557eff01e94cd87c2a99165336f5e974ff1fa94))
* install-deps.sh — one-shot native-package installer ([87ebe8a](https://github.com/sharkhunterr/grabarr/-/commit/87ebe8a57fad7ac1197ca936f6107625f0301695))
* logs-API/UI, hot reload, AA candidate iteration + FlareSolverr knob ([44c7efe](https://github.com/sharkhunterr/grabarr/-/commit/44c7efec55740a1af6e714f204d529618e8937c9))
* **orchestrator:** dedup by source + round-robin interleave ([bf6c806](https://github.com/sharkhunterr/grabarr/-/commit/bf6c806337fc7b65674d8416b6e091cd248e1f4e))
* per-source max_results + AA mirror editor + prowlarr setup polish ([4d27183](https://github.com/sharkhunterr/grabarr/-/commit/4d27183a570a02316bf99d746a95a6667a862887))
* **phase2:** ORM models, Alembic schema, FastAPI skeleton, vendor-compat tests ([bf8d6d8](https://github.com/sharkhunterr/grabarr/-/commit/bf8d6d819722dd1ad9474c86654249527656182f))
* **prowlarr-ux:** stable API key + dedicated setup page + empty-query fallback ([1139f82](https://github.com/sharkhunterr/grabarr/-/commit/1139f82395a683bdae6f5223882145a56d317d51))
* **release:** tag-only CI pipeline + scripts ported from Ghostarr ([6a46478](https://github.com/sharkhunterr/grabarr/-/commit/6a46478c4fecf8c8ec81e97def3c6231b3077c62))
* **rom-sources:** CDRomance + MyAbandonware adapters + scene-style metadata tags ([1a2112e](https://github.com/sharkhunterr/grabarr/-/commit/1a2112e193966ece79a1614d27ecc249a83e6cca))
* **rom-sources:** per-source coverage bump + tiered relevance scoring + UI-overrideable system maps ([dac2d04](https://github.com/sharkhunterr/grabarr/-/commit/dac2d0419cba3753b272dee36890089efbdfa644))
* **rom-sources:** single aggregate roms_all + idempotent boot reseed ([36c2ba3](https://github.com/sharkhunterr/grabarr/-/commit/36c2ba3b3e2803de3a973a0e2618b38b3f92d46a))
* **settings:** expose Shelfmark DoH/CustomDNS — bypass host DNS ([6a3f19b](https://github.com/sharkhunterr/grabarr/-/commit/6a3f19b990ed9b6bafcba69cad57e6d7f8237416))
* **settings:** fix padding + add "Test FlareSolverr" button ([b7fda1a](https://github.com/sharkhunterr/grabarr/-/commit/b7fda1a8ccd994d362657444360513f185be0603))
* **settings:** server.public_base_url for VPN / container clients ([1ccbfee](https://github.com/sharkhunterr/grabarr/-/commit/1ccbfee95f1d98bda7da7913ca7469b6fff633d8))
* **settings:** wire UI-edited values to Shelfmark's config proxy ([b70b0de](https://github.com/sharkhunterr/grabarr/-/commit/b70b0dec0b03acc0eb1e0cff82f70b4ba854db27))
* **setup+vendor:** Phase 1 scaffolding + Shelfmark v1.2.1 vendored ([1589a52](https://github.com/sharkhunterr/grabarr/-/commit/1589a5258a217aed91ada9e96d4cac628d2a39f5))
* **sources:** AA mirror picker on the Sources card ([40b1e6e](https://github.com/sharkhunterr/grabarr/-/commit/40b1e6ef23ef5b6c3ff0affbd1937f11778bfc7d))
* start.sh/stop.sh + Shelfmark CustomLogger compat shim ([ca3ed47](https://github.com/sharkhunterr/grabarr/-/commit/ca3ed47838a08a9a3adaf956c355fa4e72b401c7))
* **torrents:** active_seed mode with libtorrent (Constitution Article IX) ([c42def2](https://github.com/sharkhunterr/grabarr/-/commit/c42def2346ed2da03e6a099496cc748eb8b9d2e1))
* **torznab:** live activity panel — see what Prowlarr/Bookshelf sent ([4b94e10](https://github.com/sharkhunterr/grabarr/-/commit/4b94e101f27c95f2f489de549607b4293b8cf1ae))
* **torznab:** tag releases with their source adapter ([9df8262](https://github.com/sharkhunterr/grabarr/-/commit/9df8262b07863c5a6d041fae719a0e938cce5f77))
* **ui+launcher:** Settings, Downloads history, Stats pages + ./run.sh ([ff942e8](https://github.com/sharkhunterr/grabarr/-/commit/ff942e828170982c49186aa622830f63ae8d616c))
* **ui+torznab:** modal pattern across pages + Bookshelf-grade RSS ([62336fe](https://github.com/sharkhunterr/grabarr/-/commit/62336fe5405f945d7bf57a966d77b58931d341df))
* **ui:** real modal edit + form redesign + breathing room ([64832b0](https://github.com/sharkhunterr/grabarr/-/commit/64832b04c4c47009bde1ac3c2fc294a96deb0c25))
* **ui:** UX overhaul — mobile nav, modals/toasts, useful dashboard, /health page ([4f6a8b2](https://github.com/sharkhunterr/grabarr/-/commit/4f6a8b2d4925036958bbb6d7b5940dca77e50e79))
* **us1-complete:** MVP end-to-end — download + torrent + UI + Docker ([2b869ad](https://github.com/sharkhunterr/grabarr/-/commit/2b869ade4280073018260b7b6cdacdd1df9eb3a4))
* **us1-partial:** 4 adapters + orchestrator + Torznab endpoint + /api/prowlarr-config ([107f3e0](https://github.com/sharkhunterr/grabarr/-/commit/107f3e0d1c87c8e8abd26cab7364fc587e6d0bd7))
* **us2:** async-streaming + hybrid download modes, per-profile override ([ec06ea7](https://github.com/sharkhunterr/grabarr/-/commit/ec06ea74d91d6ca01b7dbec7cc2398d3eaa553ae))
* **us3:** profile CRUD + aggregate_all + edit UI with drag-and-drop ([5a96464](https://github.com/sharkhunterr/grabarr/-/commit/5a9646454b4cfbab9ebddb584c99b8208b260c4e))
* **us4:** notifications, adapter health monitor, bypass service, Z-Lib quota ([6846d03](https://github.com/sharkhunterr/grabarr/-/commit/6846d036b50dbac7705e61f325ddcec461ba3adf))
* **us5+polish:** extensibility docs, metrics, cleanup sweeper, release docs ([544db33](https://github.com/sharkhunterr/grabarr/-/commit/544db3362bce169041e9d9a39bad9b9c7c0ac6ea))
* use-public-dns.sh — one-shot DNS override for mirror-blocking networks ([7af0a08](https://github.com/sharkhunterr/grabarr/-/commit/7af0a08539862cdd5b6b1036047e1720841f1545))
* **vendor+core:** vendor full Shelfmark v1.2.1, land Phase 2 core modules ([fdd4dbe](https://github.com/sharkhunterr/grabarr/-/commit/fdd4dbecdbb53e81dcd816ced29ec370fc3b8516))


### Bug Fixes

* AA mirror fallback + SQLite WAL mode (concurrency + dead-domain recovery) ([d99ee24](https://github.com/sharkhunterr/grabarr/-/commit/d99ee24bf403f9570a7dfa036b98ec2032fad6cd))
* **aa:** let Shelfmark cascade fall through libgen/welib/zlib ([9595870](https://github.com/sharkhunterr/grabarr/-/commit/95958702b1d8c277717c188ab95573827023de74))
* **aa:** normalize language codes before passing to AA search ([74b69a3](https://github.com/sharkhunterr/grabarr/-/commit/74b69a32b48e82401022d52e8d3ada3b1d2068ba))
* dark-mode readable info box on prowlarr-setup + widen roms collection ([b8988fd](https://github.com/sharkhunterr/grabarr/-/commit/b8988fdb97452e3c3b79e8d903f07efee5ea7331))
* **docker:** google-chrome + chrome-safe flags for internal bypasser ([ead1cc2](https://github.com/sharkhunterr/grabarr/-/commit/ead1cc275f9c848977cd07ba70213af970b9eb65))
* **downloads:** allow re-grabbing the same file ([fe0f265](https://github.com/sharkhunterr/grabarr/-/commit/fe0f265d43c0ce45741d52c4d4210807458c0543))
* **downloads:** honour torrent.mode/download.mode settings from DB ([12b5669](https://github.com/sharkhunterr/grabarr/-/commit/12b566912e39387f8972e2f0fbd7fbaffa5ae3b3))
* **downloads:** startup sweeper recovers zombie grabs ([5fb060a](https://github.com/sharkhunterr/grabarr/-/commit/5fb060a0db872c39577f3a6ca2839cefca7c1e42))
* **shelfmark-env:** default Shelfmark runtime dirs into ./data/shelfmark ([1e55ef8](https://github.com/sharkhunterr/grabarr/-/commit/1e55ef857a50574e42b479a64204985c4a8b3943))
* **test:** align notifications test to renamed section header ([5fb6aae](https://github.com/sharkhunterr/grabarr/-/commit/5fb6aae0e3bdf65a124fbd5b9169808c2a985a7b))
* **torznab:** escape `"` in XML output to fix Prowlarr parse errors ([7f39b1f](https://github.com/sharkhunterr/grabarr/-/commit/7f39b1f11afde27da14fcccc36fb34916d69a81f))
* **torznab:** stable per-item pseudo info_hash so Prowlarr doesn't drop results ([9917f60](https://github.com/sharkhunterr/grabarr/-/commit/9917f603c468ba65e8b0e06db3c5e005e65bf029))
* **torznab:** vintage pubDate + Vimm size estimate so Prowlarr stops showing 0 B / 0 minute ([8c39e70](https://github.com/sharkhunterr/grabarr/-/commit/8c39e70b0aecf543c0eef50f3185edc8e846e9a6))
* **ui+rss:** profile filters persist + Prowlarr Size/Age columns populated ([febd829](https://github.com/sharkhunterr/grabarr/-/commit/febd829cd52f69448062a68ce80ffbd9fbf6f85a))
* **webseed:** emit url-list as string + add httpseeds fallback ([c2b770c](https://github.com/sharkhunterr/grabarr/-/commit/c2b770c4a714142f758fa2d4ad3a20f641e93c87))

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
