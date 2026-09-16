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

# The corpus sweep in tests/test_sage_doctest_corpus.py is the most important
# functional test of the security guardrails; it writes its statistics inside
# the container (where /workspace is read-only) and they are copied out here.
integration-test: sage-deps
	set -o pipefail; docker exec -e SAGEMATH_MCP_DOCTEST_STATS_FILE=/tmp/doctest-corpus-stats.md \
		$(SAGEMATH_MCP_DOCKER_CONTAINER) bash -lc "cd /workspace && sage -python -m pytest" | tee integration.log
	docker exec $(SAGEMATH_MCP_DOCKER_CONTAINER) cat /tmp/doctest-corpus-stats.md > doctest-corpus-stats.md
	tar -czf integration-artifacts.tar.gz integration.log doctest-corpus-stats.md || true

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
# Regenerate the baked denylist from _DANGEROUS_SAGE_MODULES. Adding a module to
# that tuple does nothing until this runs -- the worker strips by the baked list,
# not by re-deriving at startup, because deriving resolves Sage's lazy imports
# and cost 1.8s inside the caller's first evaluation.
denylist:
	docker exec sage-mcp bash -lc 'cd /workspace && PYTHONPATH=/workspace/src sage -python scripts/generate_denylist.py --emit' > /tmp/sagemath-mcp-denylist.txt
	python3 scripts/generate_denylist.py --apply /tmp/sagemath-mcp-denylist.txt
	@git --no-pager diff --stat src/sagemath_mcp/_sage_worker.py

allowlist:
	docker exec sage-mcp bash -lc 'cd /workspace && sage -python scripts/generate_allowlist.py > /tmp/allowlist_new.py'
	docker exec sage-mcp cat /tmp/allowlist_new.py > src/sagemath_mcp/allowlist.py
	@git --no-pager diff --stat src/sagemath_mcp/allowlist.py

# The passagemath artifact set (allowlist + star-exports). No Docker: an isolated
# `uv run --with` builds a passagemath env from the pinned wheel and runs the
# same generators, so this pollutes neither the project venv (installing
# passagemath there would flip _artifacts to the passagemath set for the whole
# unit suite) nor the container. Write through /tmp: the generator imports the
# file it replaces. Regenerate the allowlist AFTER any denylist change, never
# before -- the allowlist is the namespace minus the strip.
PASSAGEMATH_PIN ?= passagemath-standard==10.8.11
allowlist-passagemath:
	PYTHONPATH=src uv run --no-project --python 3.12 --with "$(PASSAGEMATH_PIN)" python scripts/generate_allowlist.py > /tmp/allowlist_passagemath_new.py
	mv /tmp/allowlist_passagemath_new.py src/sagemath_mcp/allowlist_passagemath.py
	@git --no-pager diff --stat src/sagemath_mcp/allowlist_passagemath.py

star-exports-passagemath:
	PYTHONPATH=src uv run --no-project --python 3.12 --with "$(PASSAGEMATH_PIN)" python scripts/generate_star_exports.py > /tmp/star_exports_passagemath_new.py
	mv /tmp/star_exports_passagemath_new.py src/sagemath_mcp/star_exports_passagemath.py
	@git --no-pager diff --stat src/sagemath_mcp/star_exports_passagemath.py

# The hash-locked requirements Dockerfile.passagemath installs with
# `pip install --require-hashes`, exported from uv.lock (every wheel and sdist
# hash the lock knows, so both architectures resolve). Regenerate after ANY
# change to uv.lock -- a pin bump, a Dependabot update, `uv lock --upgrade` --
# or tests/test_passagemath_lock.py fails, which is the point: the image must
# install exactly what the lock says, never a resolution of its own.
passagemath-lock:
	uv export --frozen --extra passagemath --no-dev --no-emit-project --format requirements.txt --output-file requirements-passagemath.txt
	@git --no-pager diff --stat requirements-passagemath.txt

# No `docker compose up` here: the runner's ensure_docker_container() already
# starts the container when it is not running, and it uses `docker-compose`
# (v1). This target used the v2 spelling, so on a host with only v1 installed
# the target failed before running a single case -- while the suite itself
# worked fine when invoked directly.
cli-integration:
	uv run python -m tests.cli_integration.run_cli_tests --cli both

# SageMath's own doctests, executed and compared against the output they
# document. Opt-in and sampled: 26 examples a second, so the whole corpus is
# about three and a half hours. Widen it with SAGEMATH_MCP_DOCTEST_BLOCKS and
# SAGEMATH_MCP_DOCTEST_STRIDE.
doctest-execution:
	docker exec -e SAGEMATH_MCP_DOCTEST_EXECUTION=1 \
		-e SAGEMATH_MCP_DOCTEST_BLOCKS=$${BLOCKS:-60} \
		-e SAGEMATH_MCP_DOCTEST_STRIDE=$${STRIDE:-40} \
		$(SAGEMATH_MCP_DOCKER_CONTAINER) bash -lc \
		"cd /workspace && sage -python -m pytest tests/test_sage_doctest_execution.py -q"

# Tool-forcing cases across Claude, Gemini and Codex. Unlike cli-integration,
# these assert from the proxy's wire log that a tool was actually called, so a
# model answering from memory fails instead of passing.
cli-extended:
	uv run python -m tests.cli_integration.run_extended --cli all

# The tool-surface measurement: the same cases in three arms (no server, core
# tools only, full catalogue) for every CLI, then tool-surface-stats.md. Runs
# the CLIs in parallel (each registers its own MCP server config) and the arms
# sequentially within a CLI. Needs the three CLIs authenticated locally and the
# sage-mcp container running; ~1 hour. Never CI-gated.
TOOL_SURFACE_CLIS ?= claude gemini codex
# Both tiers by default: the standard one is the historical baseline and the
# hard one is what can still separate the arms. `TOOL_SURFACE_TIER=hard` runs
# only the new cases, which is the quick way to re-measure.
TOOL_SURFACE_TIER ?= all
tool-surface:
	@mkdir -p tests/cli_integration/results
	@for cli in $(TOOL_SURFACE_CLIS); do ( \
	  for arm in none core full; do \
	    uv run python -m tests.cli_integration.run_extended --cli $$cli --tools $$arm \
	      --tier $(TOOL_SURFACE_TIER) \
	      --json-out tests/cli_integration/results/tool_surface_$${cli}_$${arm}.json \
	      > tests/cli_integration/results/tool_surface_$${cli}_$${arm}.log 2>&1 || true; \
	  done ) & done; wait
	uv run python -m tests.cli_integration.tool_surface_report tests/cli_integration/results/tool_surface_*.json

# The one-click desktop bundle (packaging/mcpb). `mcpb pack` validates the
# manifest against the published schema as it packs, so this is also the check;
# tests/test_mcpb_bundle.py covers the parts a schema cannot express.
mcpb:
	@mkdir -p dist
	npx --yes @anthropic-ai/mcpb@latest pack packaging/mcpb dist/sagemath-mcp-$(shell grep -m1 '^version' pyproject.toml | cut -d'"' -f2).mcpb

all: test integration-test

# Mutation-test the security policy (slow; never CI-gated -- the number
# measures test quality, not pass/fail). Writes mutation-stats.md.
mutation:
	uv run python scripts/run_mutation_tests.py

.PHONY: test sage-deps integration-test lint build mutation sage-container allowlist allowlist-passagemath star-exports-passagemath denylist doctest-execution cli-integration cli-extended tool-surface mcpb all
