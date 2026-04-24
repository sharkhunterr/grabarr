#!/usr/bin/env bash
# One-shot installer for native binaries Grabarr leans on.
#
# Python deps go through `uv sync --extra internal-bypasser`. This
# script handles what `uv` can't install: system packages (chromium,
# xvfb, ffmpeg) that seleniumbase's cdp_driver expects when
# bypass.mode=internal. Safe to re-run.
#
# Usage:
#   sudo ./install-deps.sh

set -e

if [ "$EUID" -ne 0 ]; then
    echo "[deps] need root. Re-run with: sudo $0" >&2
    exit 1
fi

say() { printf '[deps] %s\n' "$1"; }

# Detect whether a binary is already on PATH.
need() { ! command -v "$1" >/dev/null 2>&1; }

missing=()
need chromium && missing+=(chromium)
need Xvfb     && missing+=(xvfb)
need ffmpeg   && missing+=(ffmpeg)

if [ "${#missing[@]}" -eq 0 ]; then
    say "all native deps present — nothing to do"
    exit 0
fi

say "installing: ${missing[*]}"
apt update -q
apt install -y "${missing[@]}"

say "verifying:"
for b in chromium Xvfb ffmpeg; do
    if command -v "$b" >/dev/null 2>&1; then
        version=$("$b" --version 2>&1 | head -1 || echo '?')
        printf '  %-10s %s\n' "$b" "$version"
    else
        printf '  %-10s MISSING\n' "$b"
    fi
done

say "done. For Python deps: uv sync --extra internal-bypasser"
