.PHONY: help dev test test-unit test-integration test-vendor-compat lint format \
        tailwind-build tailwind-watch vendor-shelfmark clean \
        release release-minor release-major release-github release-deploy release-full release-dry \
        push push-github push-all push-tags \
        docker-build docker-deploy docker-deploy-multi

TAILWIND_VERSION := v3.4.14
TAILWIND_PLATFORM := $(shell uname -s | tr '[:upper:]' '[:lower:]')-$(shell uname -m | sed 's/x86_64/x64/;s/aarch64/arm64/')
TAILWIND_BIN := ./tailwindcss

help:  ## List available targets
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

dev:  ## Run uvicorn with reload + Tailwind watcher (foreground)
	uv run uvicorn grabarr.api.app:app --host 0.0.0.0 --port 8080 --reload

test:  ## Run every test suite
	uv run pytest -q

test-unit:  ## Unit tests only
	uv run pytest tests/unit -q

test-integration:  ## Integration tests only
	uv run pytest tests/integration -q

test-vendor-compat:  ## Vendored Shelfmark compatibility tests (FR-040)
	uv run pytest tests/vendor_compat -q

lint:  ## Ruff + mypy
	uv run ruff check grabarr/ tests/
	uv run ruff format --check grabarr/ tests/
	uv run mypy grabarr/

format:  ## Apply ruff formatting
	uv run ruff format grabarr/ tests/
	uv run ruff check --fix grabarr/ tests/

$(TAILWIND_BIN):  ## Download the standalone Tailwind binary
	curl -sSL -o $(TAILWIND_BIN) \
	    "https://github.com/tailwindlabs/tailwindcss/releases/download/$(TAILWIND_VERSION)/tailwindcss-$(TAILWIND_PLATFORM)"
	chmod +x $(TAILWIND_BIN)

tailwind-build: $(TAILWIND_BIN)  ## Compile Tailwind CSS once
	$(TAILWIND_BIN) --input grabarr/web/static/css/tailwind.input.css \
	                --output grabarr/web/static/css/tailwind.build.css \
	                --minify

tailwind-watch: $(TAILWIND_BIN)  ## Recompile Tailwind on change
	$(TAILWIND_BIN) --input grabarr/web/static/css/tailwind.input.css \
	                --output grabarr/web/static/css/tailwind.build.css \
	                --watch

vendor-shelfmark:  ## Re-pull Shelfmark and re-vendor into grabarr/vendor/shelfmark/
	uv run python -m grabarr.cli.vendor_refresh

clean:  ## Remove build/cache artefacts
	rm -rf build/ dist/ *.egg-info .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} +

# ---------------------------------------------------------------------------
# Release pipeline (ports Ghostarr's npm-run-release-full UX). All commands
# run scripts/release.py which bumps the version, regenerates CHANGELOG.md,
# tags + pushes. The release pipeline in .gitlab-ci.yml is TAG-ONLY, so the
# only way to trigger CI is via these targets.
# ---------------------------------------------------------------------------

release:  ## Patch release on GitLab only (X.Y.Z → X.Y.Z+1)
	uv run python scripts/release.py patch

release-minor:  ## Minor release on GitLab only (X.Y.Z → X.Y+1.0)
	uv run python scripts/release.py minor

release-major:  ## Major release on GitLab only (X.Y.Z → X+1.0.0)
	uv run python scripts/release.py major

release-github:  ## Patch release on GitLab + GitHub (no Docker Hub)
	uv run python scripts/release.py patch --github

release-deploy:  ## Patch release + trigger Docker Hub publish via CI
	uv run python scripts/release.py patch --deploy

release-full:  ## Patch release + GitLab + GitHub + Docker Hub
	uv run python scripts/release.py patch --github --deploy

release-dry:  ## Dry-run a release (prints what would happen)
	uv run python scripts/release.py patch --dry-run

push:  ## Push branch + tags to GitLab (origin)
	uv run python scripts/push.py

push-github:  ## Push branch + tags to GitHub remote
	uv run python scripts/push.py --github

push-all:  ## Push branch + tags to both remotes
	uv run python scripts/push.py --all

push-tags:  ## Push only tags to both remotes
	uv run python scripts/push.py --all --tags-only

docker-build:  ## Build the Docker image locally (no push)
	uv run python scripts/docker_deploy.py

docker-deploy:  ## Build + push Docker image to Docker Hub (linux/amd64)
	uv run python scripts/docker_deploy.py --push

docker-deploy-multi:  ## Build + push multi-arch (amd64 + arm64) to Docker Hub
	uv run python scripts/docker_deploy.py --push --multi-platform
