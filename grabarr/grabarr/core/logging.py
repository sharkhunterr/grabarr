"""Structured logging with secret redaction and correlation IDs.

Per Constitution Article XIII, no secret may ever leave the process
through a log record. Every logger returned by :func:`setup_logger` has
:class:`RedactionFilter` attached, which walks the ``args`` + ``msg`` and
masks known secret keys. The filter is deliberately paranoid: a
false-positive redaction is better than a real leak.

Per Constitution Article XIV, structured JSON output is available via
``LOG_FORMAT=json``. Every record includes a ``correlation_id`` field
pulled from the per-request :class:`contextvars.ContextVar` that
:func:`correlation_middleware` populates.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from contextvars import ContextVar
from typing import Any

# ---- correlation ID context var ------------------------------------------

_CORRELATION_ID: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def get_correlation_id() -> str | None:
    """Return the current request's correlation ID (or None outside one)."""
    return _CORRELATION_ID.get()


def set_correlation_id(value: str | None) -> None:
    """Attach a correlation ID to the current async context."""
    _CORRELATION_ID.set(value)


# ---- Secret redaction ----------------------------------------------------

# Matches the left-hand side of "<secret-ish name>=<value>" and similar
# key/value shapes that show up in kwargs, dict reprs, and URL queries.
_SECRET_KEY_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        # kwargs-style: key='value'
        r"(?P<prefix>\b(?:api[_-]?key|apikey|member[_-]?key|donator[_-]?key"
        r"|password|secret|token|cookie|remix[_-]?user(?:id|key)"
        r"|authorization|cf[_-]?clearance|fernet[_-]?key)\s*[=:]\s*)"
        r"(?P<quote>['\"]?)(?P<val>[^'\"\s,}\)]+)(?P=quote)",
    )
)

# Keys we redact when they appear on a dict.
_SECRET_DICT_KEYS: frozenset[str] = frozenset(
    {
        "api_key",
        "apikey",
        "member_key",
        "donator_key",
        "aa_donator_key",
        "password",
        "secret",
        "token",
        "cookie",
        "cookies",
        "remix_userid",
        "remix_userkey",
        "authorization",
        "cf_clearance",
        "fernet_key",
        "master_secret",
    }
)

_REDACTED = "***REDACTED***"


def _redact_string(s: str) -> str:
    """Mask every key=value pair matching a known-secret key."""
    for pattern in _SECRET_KEY_PATTERNS:
        s = pattern.sub(lambda m: f"{m.group('prefix')}{_REDACTED}", s)
    return s


def _redact_obj(obj: Any) -> Any:
    """Recursively redact dicts / lists / strings."""
    if isinstance(obj, str):
        return _redact_string(obj)
    if isinstance(obj, dict):
        out: dict[Any, Any] = {}
        for k, v in obj.items():
            if isinstance(k, str) and k.lower() in _SECRET_DICT_KEYS:
                out[k] = _REDACTED
            else:
                out[k] = _redact_obj(v)
        return out
    if isinstance(obj, list):
        return [_redact_obj(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(_redact_obj(v) for v in obj)
    return obj


class RedactionFilter(logging.Filter):
    """Redact known-secret patterns in the final formatted message.

    Strategy: if ``record.args`` is non-empty, we MUST preserve the ``%s``
    placeholder count in ``record.msg`` — rewriting placeholders causes
    TypeError: not all arguments converted. So we redact only the args
    (which are what contain the actual secrets). When there are no args,
    the msg is already-rendered text and we redact that directly.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.args:
            # Args-path: redact args only; leave msg (with %s placeholders) alone.
            if isinstance(record.args, dict):
                record.args = _redact_obj(record.args)
            elif isinstance(record.args, tuple):
                record.args = tuple(_redact_obj(a) for a in record.args)
        elif isinstance(record.msg, str):
            # No args: redact the rendered message directly.
            record.msg = _redact_string(record.msg)
        return True


# ---- Correlation-ID filter -----------------------------------------------


class CorrelationIdFilter(logging.Filter):
    """Attach the current correlation ID to every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = get_correlation_id() or "-"
        return True


# ---- Formatters ----------------------------------------------------------


class _TextFormatter(logging.Formatter):
    """Human-readable, ANSI-coloured formatter (default in dev)."""

    _COLORS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[1;31m",
    }
    _RESET = "\033[0m"

    def __init__(self, use_color: bool = True) -> None:
        super().__init__()
        self.use_color = use_color and sys.stderr.isatty()

    def format(self, record: logging.LogRecord) -> str:
        level = record.levelname
        if self.use_color and level in self._COLORS:
            level = f"{self._COLORS[level]}{level:<8}{self._RESET}"
        else:
            level = f"{level:<8}"
        corr = getattr(record, "correlation_id", "-")
        corr_bit = f" [{corr}]" if corr != "-" else ""
        base = (
            f"{self.formatTime(record, '%Y-%m-%d %H:%M:%S')} {level}"
            f" {record.name}{corr_bit}: {record.getMessage()}"
        )
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


class _JsonFormatter(logging.Formatter):
    """Structured JSON formatter (enabled via LOG_FORMAT=json)."""

    _RESERVED: frozenset[str] = frozenset(
        {
            "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
            "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
            "created", "msecs", "relativeCreated", "thread", "threadName",
            "processName", "process", "message", "asctime", "taskName",
        }
    )

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S.%f"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": getattr(record, "correlation_id", None),
        }
        # Merge any structured extras (record.__dict__ minus LogRecord
        # builtins) so that `logger.info("msg", extra={"foo": 1})` surfaces.
        for key, value in record.__dict__.items():
            if key in self._RESERVED or key.startswith("_"):
                continue
            if key not in payload:
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


# ---- Public API ----------------------------------------------------------


_configured_root = False


def configure_root(level: str = "INFO", fmt: str = "text") -> None:
    """Configure the root logger once at process start.

    ``fmt`` is ``"text"`` (default) or ``"json"``. Subsequent calls are
    idempotent — they only adjust the level and replace the formatter.
    """
    global _configured_root

    root = logging.getLogger()
    root.setLevel(level.upper())

    if not _configured_root:
        for h in list(root.handlers):
            root.removeHandler(h)
        handler = logging.StreamHandler(sys.stderr)
        handler.addFilter(RedactionFilter())
        handler.addFilter(CorrelationIdFilter())
        root.addHandler(handler)
        _configured_root = True

    formatter: logging.Formatter
    if fmt == "json" or os.environ.get("LOG_FORMAT", "").lower() == "json":
        formatter = _JsonFormatter()
    else:
        formatter = _TextFormatter()

    for h in root.handlers:
        h.setFormatter(formatter)


def setup_logger(name: str) -> logging.Logger:
    """Return a configured logger for the given dotted name.

    This is also the function vendored Shelfmark code imports via
    ``from grabarr.core.logging import setup_logger`` (see Constitution §III
    clause 3 and the bridge in
    ``grabarr/vendor/shelfmark/_grabarr_adapter.py``). A single call lazily
    configures the root handler with a redaction + correlation-ID filter;
    subsequent calls return the child logger.
    """
    if not _configured_root:
        configure_root(
            level=os.environ.get("GRABARR_LOG_LEVEL", "INFO"),
            fmt=os.environ.get("LOG_FORMAT", "text"),
        )
    return logging.getLogger(name)
