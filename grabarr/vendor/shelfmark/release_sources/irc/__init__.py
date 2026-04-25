# Vendored from calibre-web-automated-book-downloader at v1.2.1 (019d36b27e3e8576eb4a4d6d76090ee442a05a44), 2026-04-23.
# Original path: shelfmark/release_sources/irc/__init__.py. Licensed MIT; see ATTRIBUTION.md.
# Import paths were rewritten per Constitution §III; no logic change.
"""IRC release source plugin.

Searches and downloads ebook and audiobook releases from IRC channels via DCC protocol.
Available when IRC server, channel, and nickname are configured in settings.

Based on OpenBooks (https://github.com/evan-buss/openbooks).
"""

from grabarr.vendor.shelfmark.release_sources.irc import source  # noqa: F401
from grabarr.vendor.shelfmark.release_sources.irc import handler  # noqa: F401
from grabarr.vendor.shelfmark.release_sources.irc import settings  # noqa: F401
