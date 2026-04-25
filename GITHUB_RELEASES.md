# GitHub Releases — Grabarr

> Release notes for each tagged release. The first ``# vX.Y.Z`` block
> is consumed by the GitLab CI `release:gitlab` / `release:github`
> jobs as the description posted to the GitLab and GitHub release
> pages. CHANGELOG.md is the commit-by-commit machine-generated
> record; this file is the **human-curated highlight reel**.

> **Workflow** : edit this file BEFORE running `npm run release:full`.
> Add a new ``# vX.Y.Z`` block at the top describing the user-visible
> changes. The release script bumps the version, regenerates
> CHANGELOG.md from conventional commits, then tags + pushes; CI picks
> up the tag and posts THIS file's first block as the release body.

---

# v1.2.0

## 🎉 First public release — full *arr bridge for shadow libraries + ROMs

Grabarr is now feature-complete for its v1.x line: nine upstream
sources unified behind one Torznab feed, dual torrent modes,
in-process Cloudflare bypass, and a tag-only GitLab → Docker Hub →
GitHub release pipeline.

> [!IMPORTANT]
> Pull the new image with `docker compose pull` and recreate the
> container. SQLite migrations run automatically on first boot via
> Alembic; existing profiles, settings, API keys, and credentials
> are preserved.

---

### 📚 Sources — 9 upstreams, 1 Torznab feed

| Source | Status | Notes |
|--------|--------|-------|
| Anna's Archive | ✅ | Cascade with LibGen + Z-Library fallback (vendored Shelfmark) |
| LibGen | ✅ | Multi-mirror with auto-rotation |
| Z-Library | ✅ | Cookie session + quota detection |
| Internet Archive | ✅ | **NEW** — login support + romset filename match |
| Vimm's Lair | 🆕 | Console ROMs (NES → Wii, PS1, Saturn, Dreamcast) via dl3.vimm.net |
| Edge Emulation | 🆕 | ~50 systems, exposes SHA-1 hashes via custom Torznab attr |
| RomsFun | 🆕 | CF-protected, JS-countdown token rotation |
| CDRomance | 🆕 | WordPress AJAX "Show Links" pattern |
| MyAbandonware | 🆕 | DOS / Win95 / Mac / Amiga, captcha-aware |

---

### 🎮 Scene-style result titles

Every search hit now renders as
`[Source] [Console] [Region] [Lang] [Version] Title (Year) [FORMAT]`,
populated from each adapter's metadata extraction.
Console / region / language / version (No-Intro, Hack, year)
recognition is tiered with a **relevance score** so when a source
returns more hits than the per-source `max_results` cap, the **top
matches** are kept rather than the first-N raw.

> [!TIP]
> Console-name maps are **editable from the UI** (Sources page →
> JSON overrides) — no code changes needed to tweak how a system is
> labelled in titles.

---

### ☁️ Cloudflare bypass — built-in

The Docker image now bundles **Chromium + Xvfb + ffmpeg** so
`bypass.mode=internal` (SeleniumBase cdp_driver) works out of the
box — no FlareSolverr sidecar required. This is the most reliable
path on networks that block CF mirrors at the DNS layer.

Two reusable bypass primitives land for adapter authors:

- `bypass.service.fetch_html(url, prefer_internal=True)` — render a
  CF-challenged page through Chromium and return the HTML.
- `bypass.click_driver.fetch_session(url, *, pre_action_js,
  wait_until_ready_js)` — drive Chromium through a click + DOM
  mutation wait, snapshot HTML + cookies + UA.

The new `internal` mode powers RomsFun, CDRomance, MyAbandonware
end-to-end — search **and** download.

---

### 🌱 Dual torrent modes — Constitution Article IX

| Mode | Stack | When to use |
|------|-------|-------------|
| `active_seed` | libtorrent 2.0 session, ports 45000–45100 | **Default**. Real seeding to your client over BitTorrent. |
| `webseed` | Pure-Python BEP-19 + `url-list` | Fallback when libtorrent isn't available; client fetches via HTTP Range. |

Both ship as first-class with per-profile selection. The webseed
generator emits `url-list` as a bare string (not a 1-element list)
to stay compatible with qBittorrent and Transmission.

---

### 🧠 Smart search orchestration

- **Per-source `max_results`** — bumped to 20–30 per upstream so
  searches like "crash team racing" return >150 candidates instead
  of being capped at 51.
- **Top-relevance ranking** — when a source overshoots the cap, the
  highest-scoring results are kept (tiered: +60 exact match,
  +35 substring, +N per matched token).
- **Round-robin interleave + dedup** across sources — no more pages
  of duplicates when AA + LibGen both return the same book.
- **Mandatory `[Source]` prefix** on every result title for clarity
  in Prowlarr's release picker.

---

### 🛡️ Operator-grade reliability

- **Zombie sweeper** at boot flips any download stuck in
  `resolving / downloading / verifying / ready` to `failed`. Safe
  Ctrl-C → restart cycles.
- **Per-adapter circuit breaker** — 5 failures within 60 s trips
  the breaker; auto-recovery after 60 s healthy interval.
- **Apprise notifications** with Jinja2 body template, flap
  suppression (10 min cooldown per event; until-midnight for
  `quota_exhausted`).
- **`/healthz`** subsystem report + Prometheus-style **`/metrics`**.

---

### 🚀 Release pipeline — `npm run release:full`

A complete tag-only release pipeline ports the Ghostarr workflow
to Grabarr's Python / `uv` stack:

- `npm run release:full` — bumps version (standard-version), pushes
  tag, GitLab CI runs validate → test → build → deploy → release.
- **Tag-only workflow** — branch pushes never trigger CI; the
  release pipeline is the **only** pipeline.
- **Docker Hub auto-publish** — `sharkhunterr/grabarr:vX.Y.Z` +
  `:latest` on every tag.
- **GitHub mirror** — branch + tag mirrored to
  [`sharkhunterr/grabarr`](https://github.com/sharkhunterr/grabarr).
- **GitLab + GitHub releases** auto-created with this file's first
  block as the description.

See [docs/release/README.md](docs/release/README.md) for the runbook.

---

### 🔧 Quality of life

- **Internet Archive** — optional login/password
  (`sources.internet_archive.login_email`). When set, the
  `-access-restricted-item:true` filter is dropped so CDL / borrow
  items show up in search.
- **IA romset matching** — the user's query is now threaded from
  search to download, so `nointro.snes` correctly resolves to
  `Super Mario World (USA).zip` rather than an arbitrary ZIP.
- **AA mirror picker** on the Sources page — paste your own
  `.gl` / `.fi` / `.li` mirror, save, done.
- **`server.public_base_url`** setting for VPN / container clients
  that can't route back to the host's LAN IP.
- **Torznab `<size>` and `<pubDate>`** populated for every ROM hit
  — vintage default `2000-01-01` and per-system size estimates
  prevent Prowlarr from showing `0 B` / `0 minute`.
- **Per-item pseudo info-hashes** so Prowlarr never silently drops
  results during indexer tests.
- **XML escaping fix** — `"` properly escaped to fix the Prowlarr
  "fat is an unexpected token" parse error.

---

### 🐛 Bug fixes

- **Webseed url-list** emitted as bare string (qBittorrent /
  Transmission compatibility).
- **AA mirror fallback** + SQLite WAL mode for concurrency under
  load and dead-domain recovery.
- **Re-grabbing** the same file no longer 409s.
- **Shelfmark cascade** correctly falls through libgen → welib →
  zlib instead of stopping on the first AA failure.
- **Language code normalisation** before passing to AA search.
- **Settings precedence** — `torrent.mode` / `download.mode`
  honour the DB cache (was previously falling through to env-only).
- **Dark-mode contrast** fix on the Prowlarr-setup info box.

---

### 🛠️ Technology stack

| Layer | Technologies |
|-------|--------------|
| Backend | Python 3.12 • FastAPI (async) • SQLAlchemy 2.0 • Alembic • `uv` |
| Frontend | Jinja2 • Tailwind CSS • htmx • sortable.js • chart.js |
| Torrents | libtorrent 2.0 • pure-Python bencode + BEP-19 webseed |
| Bypass | SeleniumBase cdp_driver • Chromium • Xvfb • FlareSolverr (optional) |
| DevOps | Docker • GitLab CI • standard-version • semantic versioning |

---

### 🚀 Get started

```bash
docker run -d \
  --name grabarr \
  -p 8080:8080 -p 8999:8999 -p 45000-45100:45000-45100 \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/downloads:/app/downloads \
  --shm-size 2g \
  sharkhunterr/grabarr:latest
```

Open http://localhost:8080 → 7 default profiles seeded → copy
Torznab URLs into Prowlarr → done.

📖 See the [README](README.md) for full details.

---

# v1.0.1

## 🎮 ROM ecosystem complete

Six end-to-end ROM sources land in the `roms_all` profile:

- **Vimm's Lair** — curated retro (NES → Wii, PS1, Saturn, Dreamcast)
- **Edge Emulation** — wide multi-platform (~50 systems)
- **RomsFun** — JS-countdown CDN, click-driven
- **CDRomance** — WordPress AJAX "Show Links" pattern
- **MyAbandonware** — DOS / Win95 / Mac / Amiga abandonware
- **Internet Archive** — romsets + arcade collections, with new
  filename matching for multi-file items

### Scene-style title format

Every result now renders as
`[Source] [Console] [Region] [Lang] [Version] Title (Year) [FORMAT]`,
populated from each adapter's metadata. Edge Emulation also exposes a
SHA-1 hash via a custom `<torznab:attr name="hash" …>` element.

### Internet Archive

- Optional login/password (`sources.internet_archive.login_email`).
  When set, the `-access-restricted-item:true` filter is dropped from
  search so CDL / borrow items show up.
- Romset filename match: the user's query is now threaded from search
  to download, so `nointro.snes` correctly resolves to `Super Mario
  World (USA).zip` rather than an arbitrary ZIP.

### Bypass infrastructure (reusable)

- `bypass.service.fetch_html(url, prefer_internal=True)` — render a CF-
  challenged page through SeleniumBase and return the HTML.
- `bypass.click_driver.fetch_session(url, *, pre_action_js,
  wait_until_ready_js)` — drive Chromium through a click + DOM-mutation
  wait, snapshot HTML + cookies + UA. Powers RomsFun, CDRomance,
  MyAbandonware. Reusable by any future adapter.

### Operator overrides

Per-adapter system label / size maps are now editable from the Sources
page UI as JSON overrides
(`sources.{vimm,romsfun,cdromance,...}.system_overrides`).

### Quality of life

- Docker container: rebuilt with bundled Chromium + Xvfb, no
  FlareSolverr sidecar required for `bypass.mode=internal`.
- Torznab `<size>` and `<pubDate>` no longer render `0 B` / `now()`
  for ROM hits — vintage default `2000-01-01` and per-system size
  estimates.
- XML escape `"` to fix Prowlarr indexer-test parse errors.

---

# v1.0.0

Initial release. Multi-source media indexer + download bridge for the
*arr ecosystem. Anna's Archive, LibGen, Z-Library, Internet Archive
exposed as Torznab indexers consumable by Prowlarr.
