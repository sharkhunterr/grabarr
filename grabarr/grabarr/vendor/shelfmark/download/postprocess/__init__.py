"""Vendored from calibre-web-automated-book-downloader at tag v1.2.1 (commit 019d36b27e3e8576eb4a4d6d76090ee442a05a44), 2026-04-23.

Original file: shelfmark/download/postprocess/__init__.py.

Licensed MIT; see grabarr/vendor/shelfmark/ATTRIBUTION.md for the full license text.
The only modifications applied during vendoring are import-path rewrites per
Constitution Article III (`shelfmark.X` → `grabarr.vendor.shelfmark.X`) and
substitution of the shelfmark config/logger with Grabarr's `_grabarr_adapter` shim.
Original logic is unchanged.
"""

"""Post-download processing pipeline.

This package contains the post-download processing pipeline (staging, scanning,
archive extraction, transfers, and safe cleanup) and the router that selects an
output handler.

Output handlers live in `shelfmark.download.outputs` and should depend on
`pipeline` (not `router`) to avoid circular imports.
"""

from .router import post_process_download
