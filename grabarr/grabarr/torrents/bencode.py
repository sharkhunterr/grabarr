"""Minimal bencode implementation (BEP-3).

Pure-Python; zero third-party deps. Used by :mod:`grabarr.torrents.webseed`
to emit ``.torrent`` files without libtorrent.

Bencode supports four types:
  - byte-strings: ``b"spam"`` → ``b"4:spam"``
  - integers:     ``42``      → ``b"i42e"``
  - lists:        ``[...]``    → ``b"l...e"``
  - dictionaries: ``{...}``    → ``b"d...e"`` (keys MUST be byte-strings,
                                              sorted lexicographically)
"""

from __future__ import annotations

from typing import Any


class BencodeError(ValueError):
    """Raised for malformed input or un-encodable values."""


def encode(value: Any) -> bytes:
    """Encode a Python value to bencoded bytes."""
    out: list[bytes] = []
    _encode(value, out)
    return b"".join(out)


def _encode(value: Any, out: list[bytes]) -> None:
    if isinstance(value, bool):
        # bool is int in Python; reject to avoid accidental True→1 surprises.
        raise BencodeError("bencode does not support bool")
    if isinstance(value, int):
        out.append(b"i")
        out.append(str(value).encode("ascii"))
        out.append(b"e")
        return
    if isinstance(value, (bytes, bytearray)):
        b = bytes(value)
        out.append(str(len(b)).encode("ascii"))
        out.append(b":")
        out.append(b)
        return
    if isinstance(value, str):
        b = value.encode("utf-8")
        out.append(str(len(b)).encode("ascii"))
        out.append(b":")
        out.append(b)
        return
    if isinstance(value, list):
        out.append(b"l")
        for item in value:
            _encode(item, out)
        out.append(b"e")
        return
    if isinstance(value, dict):
        out.append(b"d")
        # Keys must be byte-strings and sorted.
        pairs: list[tuple[bytes, Any]] = []
        for k, v in value.items():
            if isinstance(k, str):
                pairs.append((k.encode("utf-8"), v))
            elif isinstance(k, (bytes, bytearray)):
                pairs.append((bytes(k), v))
            else:
                raise BencodeError(f"dict key must be str or bytes, got {type(k).__name__}")
        pairs.sort(key=lambda p: p[0])
        for k, v in pairs:
            _encode(k, out)
            _encode(v, out)
        out.append(b"e")
        return
    raise BencodeError(f"cannot encode {type(value).__name__}: {value!r}")


def decode(data: bytes) -> Any:
    """Decode bencoded bytes to a Python value."""
    value, idx = _decode(data, 0)
    if idx != len(data):
        raise BencodeError(f"trailing data at offset {idx}")
    return value


def _decode(data: bytes, idx: int) -> tuple[Any, int]:
    if idx >= len(data):
        raise BencodeError("unexpected end of input")
    c = data[idx : idx + 1]
    if c == b"i":
        end = data.index(b"e", idx)
        return int(data[idx + 1 : end].decode("ascii")), end + 1
    if c == b"l":
        idx += 1
        out: list[Any] = []
        while data[idx : idx + 1] != b"e":
            val, idx = _decode(data, idx)
            out.append(val)
        return out, idx + 1
    if c == b"d":
        idx += 1
        result: dict[bytes, Any] = {}
        while data[idx : idx + 1] != b"e":
            key, idx = _decode(data, idx)
            if not isinstance(key, bytes):
                raise BencodeError("dict key must be bytes")
            val, idx = _decode(data, idx)
            result[key] = val
        return result, idx + 1
    if c.isdigit():
        colon = data.index(b":", idx)
        length = int(data[idx:colon].decode("ascii"))
        start = colon + 1
        end = start + length
        return data[start:end], end
    raise BencodeError(f"unexpected byte {c!r} at offset {idx}")
