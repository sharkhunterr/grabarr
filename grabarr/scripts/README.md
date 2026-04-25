# Release & Deployment Scripts — Grabarr

Ported verbatim from
[Ghostarr](https://github.com/sharkhunterr/ghostarr)/`scripts/`. Same
flow, same UX, same npm commands. Grabarr-specific differences:

- Bump targets are `pyproject.toml` + `grabarr/__init__.py`
  (mirrored to `package.json` for `standard-version`'s benefit).
- The Docker image namespace defaults to `sharkhunterr/grabarr`
  via `package.json :: config.dockerImage`.

## 📦 Release commands

### Standard release (GitLab only)
```bash
npm run release              # Patch (1.0.0 → 1.0.1)
npm run release:patch        # Same as above
npm run release:minor        # Minor (1.0.0 → 1.1.0)
npm run release:major        # Major (1.0.0 → 2.0.0)
```

**What it does:**
- ✅ Bump version in `package.json`, `pyproject.toml`, `grabarr/__init__.py`
- ✅ Generate / update `CHANGELOG.md` from conventional commits
- ✅ Create a `chore(release): vX.Y.Z` commit
- ✅ Create a `vX.Y.Z` git tag
- ✅ Push to GitLab (`origin`) with the tag
- ✅ Create the GitLab release with the first block of `GITHUB_RELEASES.md`

### Release to GitHub too
```bash
npm run release:github
```
**Adds:**
- ✅ GitLab CI mirrors branch + tag to GitHub (handled by the CI deploy job)
- ✅ GitHub release created via API (CI does this when `DEPLOY=true`)

**Prerequisites for the API release** (CI side, set in GitLab → CI/CD vars):
- `GITHUB_TOKEN`: a personal access token with `repo` scope
- `GITHUB_REPO`: e.g. `sharkhunterr/grabarr`

### Release with Docker Hub deploy
```bash
npm run release:deploy       # Release + Docker Hub publish via CI
npm run release:full         # Release + GitHub + Docker Hub
```

**What it adds on top of `release`:**
- ✅ Pushes with `-o ci.variable=DEPLOY=true` so GitLab CI runs the
  `deploy` stage (Docker Hub login + push) and the `release:github`
  stage.

### Dry run
```bash
npm run release:dry          # Simulate, no changes
```

## 🚀 Push commands
```bash
npm run push                 # → GitLab (origin)
npm run push:github          # → GitHub remote
npm run push:all             # → both
npm run push:tags            # tags only, both remotes
```

## 🐳 Docker commands
```bash
npm run docker:build         # local build
npm run docker:deploy        # build + push to Docker Hub (linux/amd64)
npm run docker:deploy:multi  # build + push (linux/amd64 + linux/arm64)
```

**Prereqs:**
- Docker daemon running
- `docker login` against Docker Hub
- For multi-arch: `docker buildx` available

## 📝 Full release workflow

### 1. Edit release notes
Open `GITHUB_RELEASES.md`, add a new block at the top:

```markdown
# v1.1.0

## 🚀 New ROM source: example.com

This release adds…

### ✨ Features
- New adapter: example.com (PSP catalogue)

### 🐛 Bug Fixes
- Vimm download race condition fixed

---
```

### 2. Run the release

**Option A — Local only (GitLab):**
```bash
npm run release
```

**Option B — Full release (GitLab + GitHub + Docker Hub):**
```bash
npm run release:full
```

**Option C — Custom (minor + GitHub, no Docker):**
```bash
node scripts/release.js minor --github
```

### 3. Verify
- GitLab releases : `<gitlab-host>/<project>/-/releases`
- GitHub releases : `https://github.com/sharkhunterr/grabarr/releases`
- Docker Hub : `https://hub.docker.com/r/sharkhunterr/grabarr`
- Pipeline status : `<gitlab-host>/<project>/-/pipelines`

## 🔧 One-shot setup

### Install Node deps
```bash
npm install
```
(Only needed once. Pulls `standard-version` into `node_modules/`.)

### Add the GitHub remote
```bash
git remote add github https://github.com/sharkhunterr/grabarr.git
```

### Optional CLI installs

**GitHub CLI** (for local releases):
```bash
brew install gh   # macOS
sudo apt install gh   # Debian/Ubuntu
gh auth login
```

**GitLab CLI** (for local releases):
```bash
brew install glab   # macOS
sudo apt install glab   # Debian/Ubuntu
glab auth login
```

Without these CLIs, the LOCAL `npm run release` skips the release-page
step; the GitLab CI handles it server-side from the tag.

## 🎯 Examples

### Hotfix (patch)
```bash
git add .
git commit -m "fix: emergency patch"
npm run release         # 1.0.0 → 1.0.1, GitLab only
```

### New feature (minor)
```bash
git add .
git commit -m "feat: new adapter"
# edit GITHUB_RELEASES.md
node scripts/release.js minor --github --deploy
```

### WIP push
```bash
npm run push            # → GitLab
npm run push:all        # → both
```

## 📄 Files

```
scripts/
├── release.js            # main release flow (bumps, commits, tags, pushes)
├── push.js               # multi-remote git push
├── docker-deploy.js      # build + push Docker image
├── pyproject-updater.js  # standard-version updater for pyproject.toml
├── version-updater.js    # standard-version updater for grabarr/__init__.py
└── README.md             # this file
```

## 🆘 Troubleshooting

### `glab not found` / `gh not found`
Optional CLIs. The LOCAL `npm run release` will skip GitLab/GitHub
release-page creation; the GitLab CI handles it from the tag.

### `remote not configured`
```bash
git remote add github https://github.com/sharkhunterr/grabarr.git
```

### `Working directory not clean`
```bash
git status
git add .
git commit -m "your message"
```

### Docker `not logged in`
```bash
docker login
```

### `npx standard-version` keeps redownloading
Run `npm install` once — it caches into `node_modules/` and subsequent
runs use the cached binary.
