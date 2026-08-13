# pipefail requires bash; with the default /bin/sh (dash on Debian/Ubuntu) the
# exit status of `docker exec ... | tee` would be tee's, masking test failures.
SHELL := /bin/bash

# Must match the container created by scripts/setup_sage_container.sh, which
# honours the same variable.
SAGEMATH_MCP_DOCKER_CONTAINER ?= sage-mcp

test:
	uv run pytest

# Sage bundles pytest but not pytest-asyncio, so the async suite cannot run
# until the dev extras are installed into Sage's own Python.
sage-deps:
	docker exec $(SAGEMATH_MCP_DOCKER_CONTAINER) bash -lc "cd /workspace && sage -python -m pip install --quiet -e '.[dev]'"

integration-test: sage-deps
	set -o pipefail; docker exec $(SAGEMATH_MCP_DOCKER_CONTAINER) bash -lc "cd /workspace && sage -python -m pytest" | tee integration.log
	tar -czf integration-artifacts.tar.gz integration.log || true

lint:
	uv run ruff check

build:
	uv run python scripts/build_release.py

sage-container:
	./scripts/setup_sage_container.sh

cli-integration:
	docker compose up -d
	uv run python -m tests.cli_integration.run_cli_tests --cli both

all: test integration-test

.PHONY: test sage-deps integration-test lint build sage-container cli-integration all
