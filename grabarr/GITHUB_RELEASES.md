# GitHub Releases — Grabarr

> Release notes for each tagged release. The first ``# vX.Y.Z`` block
> is consumed by `scripts/release.py` AND by the GitLab CI
> `release:gitlab` / `release:github` jobs as the description posted to
> the GitLab and GitHub release pages. CHANGELOG.md is the
> commit-by-commit machine-generated record; this file is the
> human-curated highlight reel.

> **Workflow** : edit this file BEFORE running `make release-full`.
> Add a new ``# vX.Y.Z`` block at the top describing the user-visible
> changes. The release script bumps the version, regenerates
> CHANGELOG.md from conventional commits, then tags + pushes; CI picks
> up the tag and posts THIS file's first block as the release body.

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
