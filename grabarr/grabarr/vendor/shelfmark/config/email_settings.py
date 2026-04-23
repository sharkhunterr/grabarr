"""Vendored from calibre-web-automated-book-downloader at tag v1.2.1 (commit 019d36b27e3e8576eb4a4d6d76090ee442a05a44), 2026-04-23.

Original file: shelfmark/config/email_settings.py.

Licensed MIT; see grabarr/vendor/shelfmark/ATTRIBUTION.md for the full license text.
The only modifications applied during vendoring are import-path rewrites per
Constitution Article III (`shelfmark.X` → `grabarr.vendor.shelfmark.X`) and
substitution of the shelfmark config/logger with Grabarr's `_grabarr_adapter` shim.
Original logic is unchanged.
"""

from __future__ import annotations

from typing import Any

from grabarr.vendor.shelfmark._grabarr_adapter import shelfmark_config_proxy as config
from grabarr.vendor.shelfmark.download.outputs.email import EmailOutputError, build_email_smtp_config, test_smtp_connection


def test_email_connection(current_values: dict[str, Any] | None = None) -> dict[str, Any]:
    """Test SMTP connectivity using current form values (including unsaved changes)."""

    current_values = current_values or {}

    def _get_value(key: str, default: Any = None) -> Any:
        value = current_values.get(key)
        if value not in (None, ""):
            return value
        if default is None:
            return config.get(key)
        return config.get(key, default)

    settings = {
        "EMAIL_SMTP_HOST": _get_value("EMAIL_SMTP_HOST", ""),
        "EMAIL_SMTP_PORT": _get_value("EMAIL_SMTP_PORT", 587),
        "EMAIL_SMTP_SECURITY": _get_value("EMAIL_SMTP_SECURITY", "starttls"),
        "EMAIL_SMTP_USERNAME": _get_value("EMAIL_SMTP_USERNAME", ""),
        "EMAIL_SMTP_PASSWORD": _get_value("EMAIL_SMTP_PASSWORD", ""),
        "EMAIL_FROM": _get_value("EMAIL_FROM", ""),
        "EMAIL_SUBJECT_TEMPLATE": _get_value("EMAIL_SUBJECT_TEMPLATE", "{Title}"),
        "EMAIL_SMTP_TIMEOUT_SECONDS": _get_value("EMAIL_SMTP_TIMEOUT_SECONDS", 60),
        "EMAIL_ALLOW_UNVERIFIED_TLS": _get_value("EMAIL_ALLOW_UNVERIFIED_TLS", False),
    }

    try:
        smtp_config = build_email_smtp_config(settings)
        test_smtp_connection(smtp_config)
        return {"success": True, "message": "Connected to SMTP server"}
    except EmailOutputError as exc:
        return {"success": False, "message": str(exc)}
    except Exception as exc:
        return {"success": False, "message": f"SMTP test failed: {exc}"}

