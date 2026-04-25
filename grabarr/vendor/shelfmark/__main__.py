# Vendored from calibre-web-automated-book-downloader at v1.2.1 (019d36b27e3e8576eb4a4d6d76090ee442a05a44), 2026-04-23.
# Original path: shelfmark/__main__.py. Licensed MIT; see ATTRIBUTION.md.
# Import paths were rewritten per Constitution §III; no logic change.
"""Package entry point for `python -m shelfmark`."""

from grabarr.vendor.shelfmark.main import app, socketio
from grabarr.vendor.shelfmark.config.env import FLASK_HOST, FLASK_PORT
from grabarr.vendor.shelfmark._grabarr_adapter import shelfmark_config_proxy as config

if __name__ == "__main__":
    socketio.run(app, host=FLASK_HOST, port=FLASK_PORT, debug=config.get("DEBUG", False))
