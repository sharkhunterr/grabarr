# Vendored from calibre-web-automated-book-downloader at v1.2.1 (019d36b27e3e8576eb4a4d6d76090ee442a05a44), 2026-04-23.
# Original path: shelfmark/release_sources/prowlarr/__init__.py. Licensed MIT; see ATTRIBUTION.md.
# Import paths were rewritten per Constitution §III; no logic change.
"""
Prowlarr release source plugin.

This plugin integrates with Prowlarr to search for book releases
across multiple indexers (torrent and usenet).

Includes:
- ProwlarrSource: Search integration with Prowlarr
- ProwlarrHandler: Download handling via external clients
"""

# Import submodules to trigger decorator registration
from grabarr.vendor.shelfmark.release_sources.prowlarr import source  # noqa: F401
from grabarr.vendor.shelfmark.release_sources.prowlarr import handler  # noqa: F401
from grabarr.vendor.shelfmark.release_sources.prowlarr import settings  # noqa: F401

# Import shared download clients/settings to trigger registration.
# This is in a try/except to handle optional dependencies gracefully.
try:
    from grabarr.vendor.shelfmark.download import clients  # noqa: F401
    from grabarr.vendor.shelfmark.download.clients import settings as client_settings  # noqa: F401
except ImportError as e:
    import logging

    logging.getLogger(__name__).debug(f"Download clients not loaded: {e}")
