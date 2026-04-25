#!/usr/bin/env python3
"""Flexible git push for Grabarr.

Ported from Ghostarr's `scripts/push.js`. Usage::

    python scripts/push.py             # branch + tags → origin (GitLab)
    python scripts/push.py --github    # branch + tags → github
    python scripts/push.py --all       # both remotes
    python scripts/push.py --tags-only
    python scripts/push.py --no-tags
    python scripts/push.py --force
    python scripts/push.py --dry-run
"""

from __future__ import annotations

import argparse
import subprocess
import sys


def remote_url(remote: str) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "remote", "get-url", remote],
            text=True,
        ).strip()
    except subprocess.CalledProcessError:
        return None


def run(cmd: list[str], dry: bool, label: str) -> None:
    print(f"\n📤 {label}...")
    if dry:
        print(f"   [dry-run] {' '.join(cmd)}")
        return
    try:
        subprocess.run(cmd, check=True)
        print("   ✅ done")
    except subprocess.CalledProcessError as exc:
        sys.exit(f"❌ {label} failed (exit {exc.returncode})")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--gitlab", action="store_true", help="Push to origin (GitLab)")
    p.add_argument("--github", action="store_true", help="Push to github remote")
    p.add_argument("--all", action="store_true", help="Push to both remotes")
    p.add_argument("--tags-only", action="store_true")
    p.add_argument("--no-tags", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    if args.all:
        args.gitlab = True
        args.github = True
    if not (args.gitlab or args.github):
        # Default: GitLab only.
        args.gitlab = True

    branch = subprocess.check_output(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], text=True
    ).strip()
    print(f"📌 branch: {branch}")

    gitlab_url = remote_url("origin")
    github_url = remote_url("github")
    print(f"🔗 origin (GitLab): {gitlab_url or '(none)'}")
    print(f"🔗 github:          {github_url or '(none)'}")

    if args.gitlab and not gitlab_url:
        sys.exit("❌ origin remote is not configured")
    if args.github and not github_url:
        sys.exit(
            "❌ github remote is not configured.\n"
            "   git remote add github https://github.com/<user>/grabarr.git"
        )

    extra = []
    if args.force:
        extra.append("--force")

    if args.tags_only:
        if args.gitlab:
            run(
                ["git", "push", "origin", "--tags", *extra],
                args.dry_run, "push tags → origin",
            )
        if args.github:
            run(
                ["git", "push", "github", "--tags", *extra],
                args.dry_run, "push tags → github",
            )
        return

    push_extra = list(extra)
    if not args.no_tags:
        push_extra.append("--follow-tags")

    if args.gitlab:
        run(
            ["git", "push", "origin", branch, *push_extra],
            args.dry_run, "push → origin",
        )
    if args.github:
        run(
            ["git", "push", "github", branch, *push_extra],
            args.dry_run, "push → github",
        )

    print("\n✅ done.")


if __name__ == "__main__":
    main()
