"""Vendor-compat: ``core/naming`` filename sanitization."""

from __future__ import annotations

import pytest

from grabarr.vendor.shelfmark.core import naming


@pytest.mark.parametrize(
    "dirty",
    [
        "simple.epub",
        "With Spaces.pdf",
        "émoji 📚 title.mobi",
        "../../../etc/passwd",
        "foo/bar\\baz.zip",
        "CON.txt",  # Windows reserved name
        "a" * 500 + ".pdf",
    ],
)
def test_sanitize_produces_safe_string(dirty: str) -> None:
    """Every sanitizer entrypoint the vendored cascade calls must survive."""
    # The sanitize function is exposed somewhere in the naming module;
    # look it up dynamically to be resilient to upstream renames.
    for fn_name in ("sanitize_filename", "clean_filename", "make_filename_safe"):
        fn = getattr(naming, fn_name, None)
        if callable(fn):
            out = fn(dirty)
            assert isinstance(out, str)
            # Flat-filename safety: no path separators. A literal ".." in
            # the flattened result is fine (it's not a traversal because
            # there are no separators).
            assert "/" not in out
            assert "\\" not in out
            return
    pytest.skip("no sanitize-style function found in vendored naming module")
