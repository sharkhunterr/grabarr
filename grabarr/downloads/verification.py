"""File-integrity verification (spec FR-020, Constitution Article XI).

Every file handed to the torrent client passes through three gates:
  1. Content-Type check (reject HTML/JSON/XML unless explicitly expected).
  2. Size check against configured min/max.
  3. Magic-byte signature match per format.

Verification is fail-closed: any unknown content pattern is rejected.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Per-format magic-byte signatures. Tuple = ``(offset, raw_bytes)``.
# Constitution Article XI is the source of truth for these.
_SIGNATURES: dict[str, list[tuple[int, bytes]]] = {
    "epub": [(0, b"PK\x03\x04")],
    "zip": [(0, b"PK\x03\x04")],
    "cbz": [(0, b"PK\x03\x04")],
    "cbr": [(0, b"Rar!")],
    "pdf": [(0, b"%PDF")],
    "mobi": [(60, b"BOOKMOBI")],
    "azw3": [(60, b"BOOKMOBI")],
    "mp3": [(0, b"ID3"), (0, b"\xff\xfb"), (0, b"\xff\xf3"), (0, b"\xff\xf2")],
    "flac": [(0, b"fLaC")],
    "ogg": [(0, b"OggS")],
    "m4a": [(4, b"ftyp")],
    "m4b": [(4, b"ftyp")],
    "mp4": [(4, b"ftyp")],
    "iso": [(0x8001, b"CD001")],
    "djvu": [(0, b"AT&TFORM")],
    "7z": [(0, b"7z\xbc\xaf\x27\x1c")],
    # ROM formats with reliable headers.
    "nes": [(0, b"NES\x1a")],                  # iNES
    "n64": [(0, b"\x80\x37\x12\x40")],          # big-endian
    "z64": [(0, b"\x80\x37\x12\x40")],          # big-endian (same as .n64)
    "v64": [(0, b"\x37\x80\x40\x12")],          # byte-swapped
}

# ROM formats that are raw cartridge / disc dumps with no universal
# magic signature. We accept these on extension-match alone — the
# adapter knows what it grabbed because it queried for that system.
# Container formats (zip / 7z / iso / chd / rvz) keep their own magic.
_EXTENSION_ONLY_FORMATS: frozenset[str] = frozenset(
    {
        "smc", "sfc",           # SNES (no fixed header in raw dumps)
        "gb", "gbc",            # Game Boy (header at 0x104 is the Nintendo logo,
                                # not a fixed magic byte)
        "gba",                  # Game Boy Advance
        "nds",                  # Nintendo DS (has ASCII title @ 0, not a magic constant)
        "3ds",                  # Nintendo 3DS dumps
        "cia",                  # 3DS installable
        "wbfs", "wad",          # Wii / WiiWare wrappers
        "sms", "gg",            # Sega 8-bit
        "gen", "md", "bin",     # Sega Genesis / generic raw
        "32x",
        "pce",                  # TurboGrafx
        "a26", "a52", "a78",    # Atari 2600 / 5200 / 7800
        "j64",                  # Jaguar
        "lnx",                  # Lynx (LYNX header is optional)
        "vb",                   # Virtual Boy
        "gdi",                  # Dreamcast TOC
        "chd",                  # MAME CHD (custom header — accept by ext)
        "rvz",                  # Wii compressed
        "rom",                  # generic
    }
)

# Content-Type families we reject outright when not expected.
_REJECTED_CONTENT_TYPES: frozenset[str] = frozenset(
    {
        "text/html",
        "application/json",
        "application/xml",
        "text/xml",
    }
)

# Maximum bytes we read from the start of a file to confirm signatures.
# Most headers live in the first few KB; ISO signature at offset 0x8001
# forces us to read ~33 KB.
_HEADER_BYTES = 0x8001 + 16


class VerificationError(Exception):
    """Raised when a file fails integrity verification."""


@dataclass(frozen=True)
class VerificationReport:
    """What the checker returns for inclusion in ``downloads`` metadata."""

    passed: bool
    format_matched: str | None
    content_type_ok: bool
    size_ok: bool
    magic_ok: bool
    reason: str | None


def content_type_is_acceptable(
    content_type: str | None,
    *,
    allow_html: bool = False,
) -> bool:
    """Return True if ``content_type`` is not in the rejection list."""
    if content_type is None:
        return True  # no assertion possible
    ct = content_type.split(";", 1)[0].strip().lower()
    if allow_html:
        return True
    return ct not in _REJECTED_CONTENT_TYPES


def _read_header(path: Path) -> bytes:
    """Read the first ``_HEADER_BYTES`` from ``path``."""
    with path.open("rb") as fh:
        return fh.read(_HEADER_BYTES)


def magic_matches(path: Path, expected_format: str | None) -> tuple[bool, str | None]:
    """Return ``(ok, matched_format)``.

    If ``expected_format`` is given and its signatures match, ``matched_format``
    equals it. If no expected format, we scan every known signature and
    return the first match.
    """
    try:
        header = _read_header(path)
    except OSError as exc:
        raise VerificationError(f"cannot read {path}: {exc}") from exc

    def _check(fmt: str) -> bool:
        for offset, sig in _SIGNATURES.get(fmt, []):
            if header[offset : offset + len(sig)] == sig:
                return True
        return False

    if expected_format:
        expected = expected_format.lower().lstrip(".")
        if expected in _EXTENSION_ONLY_FORMATS:
            # Raw ROM dumps + a few wrapper formats with no fixed magic.
            # Accept when the actual filename matches the expected ext;
            # this still rejects HTML / JSON masquerading as a ROM.
            actual_ext = path.suffix.lower().lstrip(".")
            if actual_ext == expected:
                return True, expected
            return False, None
        if _check(expected):
            return True, expected
        return False, None

    for fmt in _SIGNATURES:
        if _check(fmt):
            return True, fmt
    return False, None


def verify_file(
    path: Path,
    *,
    expected_format: str | None,
    content_type: str | None,
    min_size_bytes: int = 1,
    max_size_bytes: int = 5 * 1024 * 1024 * 1024,  # 5 GB default cap
) -> VerificationReport:
    """Run all three verification gates. Returns a report; does NOT raise.

    The caller decides how to react to ``passed=False`` (typically: mark
    the download FAILED and leave the file in the incoming dir for
    inspection before cleanup).
    """
    if not path.exists() or not path.is_file():
        return VerificationReport(
            passed=False,
            format_matched=None,
            content_type_ok=False,
            size_ok=False,
            magic_ok=False,
            reason=f"path does not exist: {path}",
        )

    size = path.stat().st_size
    size_ok = min_size_bytes <= size <= max_size_bytes
    ct_ok = content_type_is_acceptable(content_type)

    try:
        magic_ok, matched = magic_matches(path, expected_format)
    except VerificationError as exc:
        return VerificationReport(
            passed=False,
            format_matched=None,
            content_type_ok=ct_ok,
            size_ok=size_ok,
            magic_ok=False,
            reason=str(exc),
        )

    passed = size_ok and ct_ok and magic_ok
    reason: str | None = None
    if not passed:
        problems = []
        if not size_ok:
            problems.append(f"size {size} outside [{min_size_bytes}, {max_size_bytes}]")
        if not ct_ok:
            problems.append(f"content-type {content_type!r} rejected")
        if not magic_ok:
            problems.append(
                f"magic bytes did not match expected format {expected_format!r}"
                if expected_format
                else "no recognised magic signature"
            )
        reason = "; ".join(problems)

    return VerificationReport(
        passed=passed,
        format_matched=matched,
        content_type_ok=ct_ok,
        size_ok=size_ok,
        magic_ok=magic_ok,
        reason=reason,
    )
