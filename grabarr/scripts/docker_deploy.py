#!/usr/bin/env python3
"""Docker Hub deployment for Grabarr.

Ported from Ghostarr's `scripts/docker-deploy.js`. Usage::

    python scripts/docker_deploy.py            # local build only
    python scripts/docker_deploy.py --push     # build + push to Docker Hub
    python scripts/docker_deploy.py --push --multi-platform   # amd64 + arm64
    python scripts/docker_deploy.py --dry-run

The image name + Docker Hub user come from environment variables
``DOCKER_HUB_USER`` (default: ``sharkhunterr``) and ``DOCKER_IMAGE``
(default: ``grabarr``). The version is read from pyproject.toml so
the same value lands as the ``X.Y.Z`` and ``vX.Y.Z`` tags. The
``latest`` tag is always pushed unless ``--no-latest`` is set.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
DOCKERFILE = ROOT / "Dockerfile"


def read_version() -> str:
    src = PYPROJECT.read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', src, re.MULTILINE)
    if not m:
        sys.exit("❌ no version in pyproject.toml")
    return m.group(1)


def run(cmd: list[str], *, dry: bool, label: str) -> None:
    print(f"\n🐳 {label}...")
    if dry:
        print(f"   [dry-run] {' '.join(cmd)}")
        return
    try:
        subprocess.run(cmd, check=True)
        print("   ✅ done")
    except subprocess.CalledProcessError as exc:
        sys.exit(f"❌ {label} failed (exit {exc.returncode})")


def main() -> None:
    p = argparse.ArgumentParser(description="Build / push Grabarr Docker image")
    p.add_argument("--push", action="store_true", help="Push to Docker Hub")
    p.add_argument(
        "--multi-platform",
        action="store_true",
        help="Use buildx for linux/amd64 + linux/arm64",
    )
    p.add_argument(
        "--no-latest",
        action="store_true",
        help="Don't tag/push :latest",
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--build-only",
        action="store_true",
        help="Build but don't push (legacy alias for no --push)",
    )
    args = p.parse_args()

    if not DOCKERFILE.exists():
        sys.exit(f"❌ {DOCKERFILE} not found")

    if not shutil.which("docker"):
        sys.exit("❌ docker CLI not found in PATH")
    try:
        subprocess.run(
            ["docker", "info"], check=True, stdout=subprocess.DEVNULL
        )
    except subprocess.CalledProcessError:
        sys.exit("❌ Docker daemon is not running")

    version = read_version()
    user = os.environ.get("DOCKER_HUB_USER", "sharkhunterr")
    name = os.environ.get("DOCKER_IMAGE", "grabarr")
    image = f"{user}/{name}"
    tags = [f"{image}:{version}", f"{image}:v{version}"]
    if not args.no_latest:
        tags.append(f"{image}:latest")

    print(f"📦 version: {version}")
    print(f"🐋 image:   {image}")
    print(f"🏷️  tags:    {', '.join(tags)}")

    push = args.push and not args.build_only

    if args.multi_platform:
        # buildx multi-arch
        run(
            ["docker", "buildx", "inspect", "grabarr-builder"],
            dry=args.dry_run,
            label="Probing buildx builder",
        )
        run(
            [
                "docker", "buildx", "create", "--use",
                "--name", "grabarr-builder",
            ],
            dry=args.dry_run,
            label="Creating buildx builder (idempotent)",
        )
        cmd = [
            "docker", "buildx", "build",
            "--platform", "linux/amd64,linux/arm64",
        ]
        for t in tags:
            cmd += ["-t", t]
        cmd += ["--push" if push else "--load", "-f", str(DOCKERFILE), "."]
        run(cmd, dry=args.dry_run, label="buildx build (multi-arch)")
    else:
        cmd = ["docker", "build"]
        for t in tags:
            cmd += ["-t", t]
        cmd += ["-f", str(DOCKERFILE), "."]
        run(cmd, dry=args.dry_run, label="docker build")
        if push:
            for t in tags:
                run(
                    ["docker", "push", t],
                    dry=args.dry_run,
                    label=f"docker push {t}",
                )

    if push:
        print(f"\n🔗 https://hub.docker.com/r/{image}")
        print(f"📥 docker pull {image}:{version}")
    else:
        print("\n💡 add --push to publish to Docker Hub.")


if __name__ == "__main__":
    main()
