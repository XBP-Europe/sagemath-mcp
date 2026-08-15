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

# Regenerate the caller allowlist from the installed SageMath. Two steps on
# purpose: the generator imports src/sagemath_mcp/allowlist.py, so a single
# redirect would truncate its own input before it runs. Review the diff --
# every new name is a name callers can reach.
allowlist:
	docker exec sage-mcp bash -lc 'cd /workspace && sage -python scripts/generate_allowlist.py > /tmp/allowlist_new.py'
	docker exec sage-mcp cat /tmp/allowlist_new.py > src/sagemath_mcp/allowlist.py
	@git --no-pager diff --stat src/sagemath_mcp/allowlist.py

# No `docker compose up` here: the runner's ensure_docker_container() already
# starts the container when it is not running, and it uses `docker-compose`
# (v1). This target used the v2 spelling, so on a host with only v1 installed
# the target failed before running a single case -- while the suite itself
# worked fine when invoked directly.
cli-integration:
	uv run python -m tests.cli_integration.run_cli_tests --cli both

# Tool-forcing cases across Claude, Gemini and Codex. Unlike cli-integration,
# these assert from the proxy's wire log that a tool was actually called, so a
# model answering from memory fails instead of passing.
cli-extended:
	uv run python -m tests.cli_integration.run_extended --cli all

all: test integration-test

.PHONY: test sage-deps integration-test lint build sage-container allowlist cli-integration cli-extended all
