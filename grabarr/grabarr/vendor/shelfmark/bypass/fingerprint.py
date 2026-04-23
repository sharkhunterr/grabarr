"""Vendored from calibre-web-automated-book-downloader at tag v1.2.1 (commit 019d36b27e3e8576eb4a4d6d76090ee442a05a44), 2026-04-23.

Original file: shelfmark/bypass/fingerprint.py.

Licensed MIT; see grabarr/vendor/shelfmark/ATTRIBUTION.md for the full license text.
The only modifications applied during vendoring are import-path rewrites per
Constitution Article III (`shelfmark.X` → `grabarr.vendor.shelfmark.X`) and
substitution of the shelfmark config/logger with Grabarr's `_grabarr_adapter` shim.
Original logic is unchanged.
"""

"""Browser fingerprint profile management for bypass stealth."""

import random
from typing import Optional

from grabarr.core.logging import setup_logger

logger = setup_logger(__name__)

COMMON_RESOLUTIONS = [
    (1920, 1080, 0.35),  
    (1366, 768, 0.18),   
    (1536, 864, 0.10),   
    (1440, 900, 0.08),   
    (1280, 720, 0.07),   
    (1600, 900, 0.06),   
    (1280, 800, 0.05),   
    (2560, 1440, 0.04),  
    (1680, 1050, 0.04),  
    (1920, 1200, 0.03),  
]

# Current screen size (module-level singleton)
_current_screen_size: Optional[tuple[int, int]] = None


def get_screen_size() -> tuple[int, int]:
    global _current_screen_size
    if _current_screen_size is None:
        _current_screen_size = _generate_screen_size()
        logger.debug(f"Generated initial screen size: {_current_screen_size[0]}x{_current_screen_size[1]}")
    return _current_screen_size


def rotate_screen_size() -> tuple[int, int]:
    global _current_screen_size
    old_size = _current_screen_size
    _current_screen_size = _generate_screen_size()
    width, height = _current_screen_size

    if old_size:
        logger.info(f"Rotated screen size: {old_size[0]}x{old_size[1]} -> {width}x{height}")
    else:
        logger.info(f"Generated screen size: {width}x{height}")

    return _current_screen_size


def clear_screen_size() -> None:
    global _current_screen_size
    _current_screen_size = None


def _generate_screen_size() -> tuple[int, int]:
    resolutions = [(w, h) for w, h, _ in COMMON_RESOLUTIONS]
    weights = [weight for _, _, weight in COMMON_RESOLUTIONS]
    return random.choices(resolutions, weights=weights)[0]
