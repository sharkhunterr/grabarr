# Vendored Shelfmark

The contents of `grabarr/vendor/shelfmark/` are a direct port of selected
modules from **Shelfmark** (a.k.a. `calibre-web-automated-book-downloader`),
an MIT-licensed project by CaliBrain.

## Upstream

- **Repository**: https://github.com/calibrain/calibre-web-automated-book-downloader
- **Pinned release**: `v1.2.1`
- **Pinned commit SHA**: `019d36b27e3e8576eb4a4d6d76090ee442a05a44`
- **Pinned release date**: 2026-03-21
- **Vendored into Grabarr on**: 2026-04-23

## What was vendored

Starting from the eight files named in `specs/001-grabarr-core-platform/
spec.md` §FR-002 (the bypass module, `core/mirrors.py`, `core/naming.py`,
`release_sources/direct_download.py`, and its `release_sources/__init__.py`
sibling), the full transitive import closure was computed and every
`shelfmark.*` module reachable from the seed set was copied verbatim — 41
files total. Files were NOT hand-picked for minimality; the closure
reflects Shelfmark's actual module graph at v1.2.1.

## What was changed during vendoring

Per Constitution §III ("Reuse Over Reimplementation") and §VII
("Shelfmark's Cascade Is Sacred"), **only** the following categories of
change were applied:

1. **Import-path rewrites**: every `from shelfmark.X` / `import shelfmark.X`
   is rewritten to `from grabarr.vendor.shelfmark.X` / `import
   grabarr.vendor.shelfmark.X`. No symbols are renamed, no imports are
   added or removed.
2. **Config/logger bridge**: the two imports
   - `from shelfmark.core.config import config`
   - `from shelfmark.core.logger import setup_logger`
   are routed through `grabarr/vendor/shelfmark/_grabarr_adapter.py`, which
   proxies them onto Grabarr's own `grabarr.core.config` and
   `grabarr.core.logging`. This is explicitly mandated by Constitution
   §III clause 3.
3. **Provenance header**: every vendored file has a module-level docstring
   prepended that cites the upstream path, tag, commit SHA, and vendoring
   date. The original file content follows verbatim.

No business logic, control flow, constants, error handling, or syntax was
modified. **This is a hard rule.** If the vendored code contains bugs or
limitations, they are inherited; the fix belongs upstream and a re-vendor
pulls it in.

## Why v1.2.1 rather than `main`

At vendoring time (2026-04-23) the `main` branch of Shelfmark had migrated
to Python 3.14 and adopted PEP 758 (`except A, B:` syntax without
parentheses), which does not parse on Python 3.12. Grabarr's constitution
targets Python 3.12+. Pinning to the v1.2.1 tag — the latest release
before the Python 3.14 migration — keeps the vendored code loadable on
Grabarr's supported Python versions without requiring any syntax adaptation
of the upstream.

Future vendor refreshes (`python -m grabarr.cli.vendor_refresh`) will
re-pull the then-current latest compatible tag and re-apply the two
categories of change above.

## License (MIT)

```text
MIT License

Copyright (c) 2024 CaliBrain

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Grabarr's own code

All code outside `grabarr/vendor/` is original Grabarr code licensed
**GPL-3.0-or-later**, which is compatible with vendoring MIT-licensed
dependencies.
