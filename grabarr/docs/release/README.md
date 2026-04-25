# Release & Deployment Pipeline

Grabarr's release flow is **structurally identical** to Ghostarr's
(`sharkhunterr/ghostarr`). The npm scripts are copy-paste from there
with grabarr-specific paths in the bumpFiles. **`npm run release:full`
is the canonical entry point.**

## TL;DR

```bash
# One-shot setup (only needed once per checkout):
npm install
git remote add github https://github.com/sharkhunterr/grabarr.git

# 1. Curate user-visible highlights in GITHUB_RELEASES.md
# 2. Run one of:
npm run release             # patch on GitLab
npm run release:minor       # minor on GitLab
npm run release:major       # major on GitLab
npm run release:github      # patch on GitLab + GitHub
npm run release:deploy      # patch + Docker Hub via CI
npm run release:full        # patch + GitLab + GitHub + Docker Hub
npm run release:dry         # what would happen, no changes
```

`make release-*` targets exist as thin wrappers around the same npm
commands for muscle-memory; both work identically.

## What `npm run release:full` does

1. **`npx standard-version`**
   - Bumps the version in `package.json`, `pyproject.toml`, and
     `grabarr/__init__.py` (per the `bumpFiles` in `.versionrc.json`).
   - Regenerates `CHANGELOG.md` from conventional commits since the
     previous tag.
   - Creates a `chore(release): vX.Y.Z` commit.
   - Creates a `vX.Y.Z` git tag.
2. **Push to GitLab** (`origin`) with `--follow-tags` and
   `-o ci.variable=DEPLOY=true`.
3. **GitLab release** created via `glab` CLI if installed (otherwise
   the CI `release:gitlab` job picks it up from the tag).
4. **GitHub release** created via `gh` CLI if installed AND a
   `GITHUB_TOKEN` is in env (otherwise the CI `release:github` job
   handles it via API).
5. **CI** picks up the tag and runs `validate → test → build →
   deploy → release → verify`. The `deploy` stage logs in to Docker
   Hub, pushes `<user>/grabarr:vX.Y.Z` and `:latest`, and mirrors the
   tag + default branch to GitHub.

## Pipeline: tag-only

`.gitlab-ci.yml` runs **only when a tag matching `vX.Y.Z` is pushed**:

```yaml
workflow:
  rules:
    - if: '$CI_COMMIT_TAG =~ /^v\d+\.\d+\.\d+$/'
```

Branch pushes never trigger CI. The whole release flow is gated by
`npm run release*` — no accidental builds.

## Stages

| Stage | Job | What it does |
|---|---|---|
| `validate` | `validate:lint` | `uv run ruff check` + `format --check` |
| `test` | `test:backend` | `uv run pytest` + JUnit |
| `build` | `build:docker` | `docker build` + image artifact |
| `publish` | `publish:gitlab-registry` | (off by default) push image to GitLab Registry |
| `deploy` | `deploy` | Docker Hub login + push, GitHub mirror |
| `release` | `release:gitlab` | always: GitLab release with notes from `GITHUB_RELEASES.md` |
| `release` | `release:github` | when `DEPLOY=true`: GitHub release via API |
| `verify` | `verify` | when `DEPLOY=true`: HEAD probe Docker Hub + GitHub release |

## Required GitLab CI variables

Set in **GitLab → Settings → CI/CD → Variables** (mark each "masked"
+ "protected"):

| Variable | Used by | Notes |
|---|---|---|
| `DOCKER_HUB_USER` | `deploy` | e.g. `sharkhunterr` |
| `DOCKER_HUB_TOKEN` | `deploy` | hub.docker.com → Settings → Security → Access Tokens |
| `GITHUB_TOKEN` | `deploy`, `release:github`, `verify` | PAT with `repo` scope |
| `GITHUB_REPO` | `deploy`, `release:github`, `verify` | e.g. `sharkhunterr/grabarr` |

`DEPLOY=true` is **not** stored — it's added at push time by
`scripts/release.js` when `--deploy` is passed:

```bash
git push origin main --follow-tags -o ci.variable="DEPLOY=true"
```

## Editing release notes

`GITHUB_RELEASES.md` is the human-curated highlight reel. Add a new
`# vX.Y.Z` block at the top **before** running a release. Both
`scripts/release.js` and the GitLab CI release jobs extract the first
`# vX.Y.Z` block as the release body (CHANGELOG.md is the fallback).

## Versioning

`standard-version` follows conventional-commit conventions:

- `feat:` → minor bump
- `fix:` / `perf:` → patch bump
- `BREAKING CHANGE:` footer or `!` after type → major bump
- Other types (`chore:`, `docs:`, `style:`, `test:`, `build:`, `ci:`,
  `refactor:`) hidden from CHANGELOG by default (see `.versionrc.json`)

Pass `npm run release:minor` / `:major` to override the auto-detection.

## Bump targets

`standard-version` updates three files in lockstep (per
`.versionrc.json`):

- `package.json` (canonical for `standard-version` itself)
- `pyproject.toml` (top-level `version = "..."`)
- `grabarr/__init__.py` (`__version__ = "..."`)

Custom updaters live in `scripts/pyproject-updater.js` and
`scripts/version-updater.js`.

## Files

```
package.json                # npm scripts entry point
.versionrc.json             # standard-version config (bumpFiles, types)
.nvmrc                      # Node 22 pin
.env.example                # local dev env vars
.gitlab-ci.yml              # tag-only CI pipeline
GITHUB_RELEASES.md          # human-curated release notes
CHANGELOG.md                # auto-generated full history

scripts/
├── release.js              # main release flow (Ghostarr port)
├── push.js                 # multi-remote git push
├── docker-deploy.js        # Docker Hub build/push
├── pyproject-updater.js    # standard-version updater for pyproject.toml
├── version-updater.js      # standard-version updater for grabarr/__init__.py
└── README.md               # full per-command reference
```

## Troubleshooting

### `standard-version: command not found`
Run `npm install` once. `npx standard-version` will auto-fetch on
first run, but installing populates `node_modules/` and avoids the
network round-trip.

### `glab CLI not found` / `gh CLI not found`
Optional. Without them, the LOCAL `npm run release` skips the
release-page creation — the CI `release:gitlab` / `release:github`
jobs handle it server-side from the tag.

### `Working directory not clean`
Commit or stash before releasing — `release.js` refuses dirty trees
so the version bump commit is reproducible.

### `DEPLOY` flag not picked up by CI
Confirm the push went through with `-o ci.variable=DEPLOY=true`. The
GitLab pipeline page lists the CI variables — if `DEPLOY` is absent,
re-push the tag with `git push origin <tag> -o ci.variable=DEPLOY=true`.

### Docker Hub login failure
`DOCKER_HUB_TOKEN` rejected → regenerate at
https://hub.docker.com/settings/security and update the GitLab CI
variable.

### GitHub mirror push rejected
PAT scope too narrow — give it `repo` (not just `public_repo`).
