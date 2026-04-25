#!/usr/bin/env python3
"""Flexible release script for Grabarr.

Ported from Ghostarr's `scripts/release.js` (Node) and adapted for a
Python / uv project. Same UX as `npm run release-full` — bumps the
version, rewrites CHANGELOG, commits, tags, pushes to GitLab (origin),
and optionally creates GitLab + GitHub releases plus a Docker Hub
deploy.

Usage::

    make release                # Patch release, GitLab only
    make release-minor          # Minor release, GitLab only
    make release-major          # Major release, GitLab only
    make release-github         # Release on GitLab + GitHub
    make release-deploy         # Release + trigger Docker Hub deploy
    make release-full           # Release on both + Docker Hub deploy

    # Direct CLI:
    python scripts/release.py [patch|minor|major] [--github] [--deploy] [--dry-run]
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
INIT_FILE = ROOT / "grabarr" / "__init__.py"
CHANGELOG = ROOT / "CHANGELOG.md"
RELEASE_NOTES_FILE = ROOT / "GITHUB_RELEASES.md"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def run(
    cmd: list[str] | str,
    *,
    check: bool = True,
    capture: bool = True,
    cwd: Path | None = None,
) -> str:
    """Wrap subprocess with a uniform interface."""
    if isinstance(cmd, str):
        shell = True
        display = cmd
    else:
        shell = False
        display = " ".join(cmd)
    if VERBOSE:
        print(f"  $ {display}")
    result = subprocess.run(
        cmd,
        check=False,
        shell=shell,
        text=True,
        capture_output=capture,
        cwd=cwd or ROOT,
    )
    if check and result.returncode != 0:
        sys.stderr.write(
            f"\n❌ Command failed (exit {result.returncode}): {display}\n"
        )
        if result.stdout:
            sys.stderr.write(f"stdout:\n{result.stdout}\n")
        if result.stderr:
            sys.stderr.write(f"stderr:\n{result.stderr}\n")
        sys.exit(result.returncode)
    return (result.stdout or "").strip()


def step(message: str) -> None:
    print(f"\n📦 {message}...")


def warn(message: str) -> None:
    print(f"⚠️  {message}")


VERBOSE = False


# ---------------------------------------------------------------------------
# Version operations
# ---------------------------------------------------------------------------


_PYPROJECT_VERSION = re.compile(
    r'^version\s*=\s*"([^"]+)"\s*$', re.MULTILINE
)
_INIT_VERSION = re.compile(
    r'^__version__\s*=\s*"([^"]+)"\s*$', re.MULTILINE
)


def read_version() -> str:
    src = PYPROJECT.read_text(encoding="utf-8")
    m = _PYPROJECT_VERSION.search(src)
    if not m:
        sys.exit("❌ could not find `version = ...` in pyproject.toml")
    return m.group(1)


def write_version(new: str) -> None:
    """Write the new version to pyproject.toml AND grabarr/__init__.py."""
    pj = PYPROJECT.read_text(encoding="utf-8")
    new_pj, n = _PYPROJECT_VERSION.subn(f'version = "{new}"', pj, count=1)
    if n != 1:
        sys.exit("❌ failed to substitute version in pyproject.toml")
    PYPROJECT.write_text(new_pj, encoding="utf-8")

    init = INIT_FILE.read_text(encoding="utf-8")
    new_init, n = _INIT_VERSION.subn(f'__version__ = "{new}"', init, count=1)
    if n != 1:
        sys.exit("❌ failed to substitute __version__ in grabarr/__init__.py")
    INIT_FILE.write_text(new_init, encoding="utf-8")


def bump_version(current: str, level: str) -> str:
    parts = current.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        sys.exit(f"❌ unsupported version format {current!r} (expected MAJOR.MINOR.PATCH)")
    major, minor, patch = (int(p) for p in parts)
    if level == "major":
        return f"{major + 1}.0.0"
    if level == "minor":
        return f"{major}.{minor + 1}.0"
    if level == "patch":
        return f"{major}.{minor}.{patch + 1}"
    sys.exit(f"❌ invalid bump level {level!r}")


# ---------------------------------------------------------------------------
# CHANGELOG generation
# ---------------------------------------------------------------------------


_CONVENTIONAL = re.compile(
    r"^(?P<type>feat|fix|perf|refactor|docs|chore|test|build|ci|style|revert)"
    r"(?:\((?P<scope>[^)]+)\))?(?P<bang>!)?:\s*(?P<subject>.+)$"
)
_SECTION_TITLES = {
    "feat": "✨ Features",
    "fix": "🐛 Bug Fixes",
    "perf": "🚀 Performance",
    "refactor": "♻️  Refactoring",
    "revert": "⏪ Reverts",
}


def collect_commits_since(prev_tag: str | None) -> dict[str, list[str]]:
    """Group ``feat:`` / ``fix:`` etc. commits by section title.

    Hides chore/docs/style/test/build/ci by default (matches Ghostarr's
    `.versionrc.json`).
    """
    range_arg = f"{prev_tag}..HEAD" if prev_tag else "HEAD"
    log = run(
        ["git", "log", range_arg, "--pretty=%h\t%s"],
        capture=True,
    )
    sections: dict[str, list[str]] = {}
    for line in log.splitlines():
        try:
            sha, subject = line.split("\t", 1)
        except ValueError:
            continue
        m = _CONVENTIONAL.match(subject.strip())
        if not m:
            continue
        ctype = m.group("type")
        bang = m.group("bang") or ""
        title = _SECTION_TITLES.get(ctype)
        if title is None:
            continue
        scope = m.group("scope")
        prefix = f"**{scope}**: " if scope else ""
        line_md = f"- {prefix}{m.group('subject')} ({sha})"
        if bang:
            line_md = "- 💥 **BREAKING** " + line_md[2:]
        sections.setdefault(title, []).append(line_md)
    return sections


def write_changelog_entry(new_version: str, prev_tag: str | None) -> str:
    """Prepend a new ``## [{ver}] - YYYY-MM-DD`` block to CHANGELOG.md.

    Returns the new entry's body (used as default release notes when
    GITHUB_RELEASES.md is empty).
    """
    sections = collect_commits_since(prev_tag)
    today = date.today().isoformat()
    body_lines = [f"## [{new_version}] - {today}"]
    if not sections:
        body_lines.append("")
        body_lines.append("_No conventional-commit changes detected._")
    else:
        for title, items in sections.items():
            body_lines.append("")
            body_lines.append(f"### {title}")
            body_lines.append("")
            body_lines.extend(items)
    body_lines.append("")
    new_body = "\n".join(body_lines)

    if CHANGELOG.exists():
        existing = CHANGELOG.read_text(encoding="utf-8")
        # Anchor on the first '## ' or end-of-header.
        if existing.startswith("# "):
            head, _, rest = existing.partition("\n")
            CHANGELOG.write_text(
                head + "\n\n" + new_body + "\n" + rest.lstrip("\n"),
                encoding="utf-8",
            )
        else:
            CHANGELOG.write_text(new_body + "\n" + existing, encoding="utf-8")
    else:
        CHANGELOG.write_text(
            "# Changelog\n\n" + new_body + "\n", encoding="utf-8"
        )
    return new_body


# ---------------------------------------------------------------------------
# Release notes (GITHUB_RELEASES.md preferred, CHANGELOG fallback)
# ---------------------------------------------------------------------------


def latest_release_notes(new_version: str, fallback_body: str) -> str:
    """Return the release-notes blob.

    Preference order:
      1. First ``# v{X.Y.Z}`` block in GITHUB_RELEASES.md (manually
         curated, matches Ghostarr's pattern).
      2. The CHANGELOG entry just generated.
    """
    if RELEASE_NOTES_FILE.exists():
        text = RELEASE_NOTES_FILE.read_text(encoding="utf-8")
        # First block is between the first `# v...` header and the next
        # `# v...` header (or EOF).
        m = re.search(
            r"^#\s+v[\d.]+[^\n]*\n(?P<body>[\s\S]*?)(?=^#\s+v[\d.]+|\Z)",
            text,
            re.MULTILINE,
        )
        if m and m.group("body").strip():
            return m.group("body").strip()
        warn(
            "GITHUB_RELEASES.md exists but has no `# vX.Y.Z` block — "
            "falling back to CHANGELOG entry."
        )
    return fallback_body


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Grabarr release helper")
    p.add_argument(
        "level",
        nargs="?",
        choices=("patch", "minor", "major"),
        default="patch",
        help="Semver bump level (default: patch).",
    )
    p.add_argument(
        "--github",
        action="store_true",
        help="Also create a GitHub release (needs `gh` CLI or GITHUB_TOKEN).",
    )
    p.add_argument(
        "--deploy",
        action="store_true",
        help="Push with -o ci.variable=DEPLOY=true so the GitLab CI "
        "pipeline runs the docker-hub publish + GitHub mirror jobs.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would happen without modifying anything.",
    )
    p.add_argument("--skip-push", action="store_true")
    p.add_argument("--skip-release", action="store_true")
    p.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Print every shell command before running it.",
    )
    return p.parse_args()


def ensure_clean_tree(dry_run: bool) -> None:
    status = run(["git", "status", "--porcelain"])
    if status and not dry_run:
        sys.exit(
            "❌ working tree has uncommitted changes; commit or stash them first.\n"
            f"  {status.splitlines()[0]} ..."
        )


def previous_tag() -> str | None:
    out = run(["git", "tag", "--list", "v*", "--sort=-v:refname"])
    return out.splitlines()[0] if out else None


def main() -> None:
    global VERBOSE
    args = parse_args()
    VERBOSE = args.verbose

    print("🚀 Grabarr Release\n")
    print(f"Options: {vars(args)}\n")

    ensure_clean_tree(args.dry_run)
    branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    print(f"📌 Branch: {branch}")

    cur = read_version()
    new = bump_version(cur, args.level)
    tag = f"v{new}"
    print(f"✨ {cur} → {new}  ({tag})")

    if args.dry_run:
        prev = previous_tag()
        sections = collect_commits_since(prev)
        print(f"\n[dry-run] CHANGELOG would contain {sum(len(v) for v in sections.values())} entries:")
        for title, items in sections.items():
            print(f"  ## {title}")
            for it in items[:3]:
                print(f"    {it}")
            if len(items) > 3:
                print(f"    ... +{len(items)-3} more")
        print("\n[dry-run] would tag → push → optionally release. No changes made.")
        return

    step("Bumping version in pyproject.toml + grabarr/__init__.py")
    write_version(new)

    step("Generating CHANGELOG entry from conventional commits")
    prev = previous_tag()
    body = write_changelog_entry(new, prev)

    step("Committing release + tagging")
    run(["git", "add", str(PYPROJECT), str(INIT_FILE), str(CHANGELOG)])
    run(["git", "commit", "-m", f"chore(release): {tag}"])
    run(["git", "tag", "-a", tag, "-m", f"Release {tag}"])

    if args.skip_push:
        print(f"\n⏸  --skip-push: branch + tag created locally; not pushed.")
        return

    step(f"Pushing branch + tag to GitLab (origin)")
    push_args = ["git", "push", "origin", branch, "--follow-tags"]
    if args.deploy:
        push_args += ["-o", "ci.variable=DEPLOY=true"]
    run(push_args, capture=False)

    if args.skip_release:
        return

    notes = latest_release_notes(new, body)
    notes_file = ROOT / ".release-notes.tmp.md"
    notes_file.write_text(notes, encoding="utf-8")

    if shutil.which("glab"):
        step("Creating GitLab release via glab CLI")
        run(
            [
                "glab", "release", "create", tag,
                "--name", f"Release {tag}",
                "--notes-file", str(notes_file),
            ],
            capture=False,
        )
    else:
        warn("glab CLI not found — GitLab release will be created by CI (release:gitlab job)")

    if args.github:
        if shutil.which("gh"):
            step("Creating GitHub release via gh CLI")
            env = dict(os.environ)
            if "GITHUB_TOKEN" in env and "GH_TOKEN" not in env:
                env["GH_TOKEN"] = env["GITHUB_TOKEN"]
            cmd = [
                "gh", "release", "create", tag,
                "--title", f"Release {tag}",
                "--notes-file", str(notes_file),
            ]
            repo = env.get("GITHUB_REPO")
            if repo:
                cmd += ["--repo", repo]
            try:
                subprocess.run(cmd, check=True, env=env)
            except subprocess.CalledProcessError as exc:
                warn(f"gh release failed (exit {exc.returncode}); CI will retry")
        else:
            warn("gh CLI not found — GitHub release will be created by CI (release:github job)")

    notes_file.unlink(missing_ok=True)

    print(f"\n✅ Release {tag} done.")
    if args.deploy:
        print("🐳 Docker Hub deploy + GitHub mirror triggered via GitLab CI (DEPLOY=true).")


if __name__ == "__main__":
    main()
