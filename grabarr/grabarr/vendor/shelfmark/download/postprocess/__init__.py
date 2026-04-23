# Vendored from calibre-web-automated-book-downloader at v1.2.1 (019d36b27e3e8576eb4a4d6d76090ee442a05a44), 2026-04-23.
# Original path: shelfmark/download/postprocess/__init__.py. Licensed MIT; see ATTRIBUTION.md.
# Import paths were rewritten per Constitution §III; no logic change.
"""Post-download processing pipeline.

This package contains the post-download processing pipeline (staging, scanning,
archive extraction, transfers, and safe cleanup) and the router that selects an
output handler.

Output handlers live in `shelfmark.download.outputs` and should depend on
`pipeline` (not `router`) to avoid circular imports.
"""

from .router import post_process_download
