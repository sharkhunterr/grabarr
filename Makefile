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
# Release pipeline — thin wrappers around the npm scripts ported from
# Ghostarr (sharkhunterr/ghostarr). The canonical entry point is
# `npm run release:full`; these targets are kept for muscle memory and
# accept the same suffixes. Full doc: scripts/README.md.
# ---------------------------------------------------------------------------

release:  ## Patch release on GitLab only (X.Y.Z → X.Y.Z+1)
	npm run release

release-minor:  ## Minor release on GitLab only (X.Y.Z → X.Y+1.0)
	npm run release:minor

release-major:  ## Major release on GitLab only (X.Y.Z → X+1.0.0)
	npm run release:major

release-github:  ## Patch release on GitLab + GitHub (no Docker Hub)
	npm run release:github

release-deploy:  ## Patch release + trigger Docker Hub publish via CI
	npm run release:deploy

release-full:  ## Patch release + GitLab + GitHub + Docker Hub
	npm run release:full

release-dry:  ## Dry-run a release (prints what would happen)
	npm run release:dry

push:  ## Push branch + tags to GitLab (origin)
	npm run push

push-github:  ## Push branch + tags to GitHub remote
	npm run push:github

push-all:  ## Push branch + tags to both remotes
	npm run push:all

push-tags:  ## Push only tags to both remotes
	npm run push:tags

docker-build:  ## Build the Docker image locally (no push)
	npm run docker:build

docker-deploy:  ## Build + push Docker image to Docker Hub (linux/amd64)
	npm run docker:deploy

docker-deploy-multi:  ## Build + push multi-arch (amd64 + arm64) to Docker Hub
	npm run docker:deploy:multi
