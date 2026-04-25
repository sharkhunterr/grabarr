# Release & Deployment Pipeline

Grabarr's release flow is ported from
[Ghostarr](https://github.com/sharkhunterr/ghostarr)'s `npm run release-full`
pattern, adapted to a Python / `uv` project. Same UX, same outcomes,
no Node toolchain required at release time.

## TL;DR

```bash
# 1. Curate the user-visible highlight in GITHUB_RELEASES.md (see below)
# 2. Run one of the make targets:

make release             # patch on GitLab only
make release-minor       # minor on GitLab only
make release-major       # major on GitLab only
make release-github      # patch on GitLab + GitHub
make release-deploy      # patch + Docker Hub publish via CI
make release-full        # patch + GitLab + GitHub + Docker Hub
make release-dry         # what would happen, no changes
```

Each `make release*` target invokes `scripts/release.py`, which:

1. Bumps the version in `pyproject.toml` AND `grabarr/__init__.py`
2. Regenerates `CHANGELOG.md` from conventional commits since the
   previous tag
3. Commits with `chore(release): vX.Y.Z`
4. Tags `vX.Y.Z`
5. Pushes the branch + tag to GitLab (`origin`)
6. **Optionally** appends `-o ci.variable=DEPLOY=true` to the push so
   the GitLab CI release pipeline runs the Docker Hub publish + GitHub
   mirror jobs

## Pipeline: tag-only

The CI workflow in `.gitlab-ci.yml` runs **only on `vX.Y.Z` tags**.
Branch pushes never trigger CI. The whole release flow is therefore
gated by `make release*` — no accidental builds on every commit.

```yaml
workflow:
  rules:
    - if: '$CI_COMMIT_TAG =~ /^v\d+\.\d+\.\d+$/'
```

## Stages

| Stage | Job | What it does |
|---|---|---|
| `validate` | `validate:lint` | `uv run ruff check` + `ruff format --check` |
| `test` | `test:backend` | `uv run pytest` + JUnit report |
| `build` | `build:docker` | `docker build` from `Dockerfile`, save to artifact |
| `publish` | `publish:gitlab-registry` | (off by default) push image to GitLab Container Registry |
| `deploy` | `deploy` | when `DEPLOY=true`: build + login + push to Docker Hub, mirror tag + default branch to GitHub |
| `release` | `release:gitlab` | always on tag: GitLab release with notes from `GITHUB_RELEASES.md` first block |
| `release` | `release:github` | when `DEPLOY=true`: GitHub release via API |
| `verify` | `verify` | when `DEPLOY=true`: HEAD probe Docker Hub + GitHub release URL |

## CI variables required

Set these in **GitLab → Settings → CI/CD → Variables** (mark each as
"masked" + "protected"):

| Variable | Used by | Notes |
|---|---|---|
| `DOCKER_HUB_USER` | `deploy` | Docker Hub username (also used as image namespace, e.g. `sharkhunterr`) |
| `DOCKER_HUB_TOKEN` | `deploy` | Docker Hub access token (Settings → Security → Access Tokens) |
| `GITHUB_TOKEN` | `deploy`, `release:github`, `verify` | GitHub PAT with `repo` scope |
| `GITHUB_REPO` | `deploy`, `release:github`, `verify` | `<owner>/<repo>`, e.g. `sharkhunterr/grabarr` |

The `DEPLOY` variable itself is **not** stored in CI/CD settings — it's
passed at push time by `scripts/release.py` when `--deploy` is set:

```bash
git push origin main --follow-tags -o ci.variable=DEPLOY=true
```

## Editing release notes

`GITHUB_RELEASES.md` is the human-curated highlight reel. Add a new
`# vX.Y.Z` block at the top BEFORE running a release. Both
`scripts/release.py` and the GitLab CI release jobs extract the first
`# vX.Y.Z` block as the release body.

If the file is missing or empty, the CI job falls back to the
auto-generated CHANGELOG.md entry for that version.

## Versioning rules

- `feat:` commits → minor bump
- `fix:` / `perf:` commits → patch bump
- `BREAKING CHANGE:` footer or `!` after type → major bump
- All other types (chore/docs/style/test/build/ci/refactor) hidden
  from CHANGELOG by default

`scripts/release.py` doesn't auto-detect the bump level today — pass
it on the CLI (`make release-minor`, `make release-major`).

## Adding the GitHub remote (one-shot setup)

```bash
git remote add github https://github.com/<owner>/grabarr.git
```

The CI deploy job uses an HTTPS URL with `GITHUB_TOKEN` instead of
this remote, so the remote is only required if you want to push from
your laptop (`make push-github` / `make push-all`).

## Files

```
scripts/
├── release.py          # main release flow (port of release.js)
├── docker_deploy.py    # local Docker Hub build/push (port of docker-deploy.js)
└── push.py             # multi-remote git push (port of push.js)

.gitlab-ci.yml          # tag-only CI pipeline
.versionrc.json         # documentation-only mirror of conventional-commit categories
GITHUB_RELEASES.md      # human-curated release notes (edit before each release)
CHANGELOG.md            # auto-generated full history
```

## Troubleshooting

### `working tree has uncommitted changes`
Commit or stash before releasing — `release.py` refuses dirty trees so
the version bump commit is reproducible.

### `glab CLI not found` / `gh CLI not found`
Optional. Without them, the LOCAL `make release` doesn't try to create
the release page itself; it just pushes the tag. The CI
`release:gitlab` / `release:github` jobs create them server-side.

### `DEPLOY` flag not picked up
Confirm the push went through with `-o ci.variable=DEPLOY=true`.
GitLab logs the variable on the pipeline page — if it's not there,
re-push the tag with `git push origin <tag> -o ci.variable=DEPLOY=true`.

### Docker Hub login failure
`DOCKER_HUB_TOKEN` is rejected → regenerate at
https://hub.docker.com/settings/security and update the GitLab CI
variable.

### GitHub mirror push rejected (`refusing to allow a Personal Access Token to update default branch`)
The PAT scope is too narrow — give it `repo` (not just `public_repo`)
and `workflow` if your GitHub repo has Actions defined.
