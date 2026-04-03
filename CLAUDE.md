# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

SageMath MCP is a Model Context Protocol server exposing stateful SageMath computations to LLM clients via FastMCP. Each MCP session gets a dedicated Sage worker subprocess with persistent variable state across tool calls.

## Commands

```bash
uv pip install -e .[dev]          # Install with dev extras
make lint                          # uv run ruff check
make test                          # uv run pytest (pure Python, no Sage needed)
make integration-test              # pytest inside Sage Docker container
make build                         # Build wheel + sdist via scripts/build_release.py
make sage-container                # Bootstrap the Sage Docker container
uv run pytest tests/test_server.py -k "test_name"  # Run a single test
```

Unit tests run with `SAGEMATH_MCP_PURE_PYTHON=1` (uses Python `math` stdlib instead of Sage). Integration tests require `docker exec sage-mcp` and real Sage runtime.

## Linting

Ruff with line-length 100, target Python 3.11. Rules: E, F, W, B, UP, ASYNC, RUF, I (import sorting). Run `make lint` before committing.

## Testing

- All async tests use `@pytest.mark.asyncio` (asyncio_mode is "auto")
- Tests mirror source modules: `test_server.py`, `test_session.py`, `test_security.py`, `test_config.py`, etc.
- `test_integration.py` and `test_use_cases.py` require the Sage container
- Key fixtures: `python_settings` (injects `force_python_worker=True`), `FakeContext` (captures MCP context messages)

## Architecture

**Source lives in `src/sagemath_mcp/`:**

- `server.py` - FastMCP app, all MCP tool/resource definitions, progress heartbeats. Entry point: `main()`.
- `session.py` - `SageSessionManager` (per-client session map with asyncio locks) and `SageSession` (spawns/manages `_sage_worker.py` subprocess via JSON stdin/stdout protocol).
- `_sage_worker.py` - Subprocess worker that executes code in a persistent namespace. Handles execute/reset/shutdown commands. Validates AST before compilation.
- `security.py` - AST validator enforcing `SecurityPolicy`: blocks dangerous imports, eval/exec, filesystem/process APIs. Configurable via env vars.
- `config.py` - `SageSettings` dataclass driven by `SAGEMATH_MCP_*` environment variables.
- `models.py` - Pydantic models for results (`EvaluateResult`, `SessionSnapshot`, `MonitoringSnapshot`).
- `monitoring.py` - Thread-safe `EvaluationMetrics` (counters, latency, error tracking).

**Request flow:** MCP client -> `server.py` tool -> `SageSessionManager.get_or_create()` -> `SageSession.evaluate()` -> JSON request to `_sage_worker.py` subprocess -> AST validation -> exec in persistent namespace -> JSON response back.

**MCP tools:** `evaluate_sage` (core), `reset_sage_session`, `cancel_sage_session`, plus math helpers (`solve_equation`, `differentiate_expression`, `integrate_expression`, `calculate_expression`, `statistics_summary`, `matrix_multiply`).

**MCP resources:** `sagemath/session/{scope}` (session snapshots), `sagemath/monitoring/{scope}` (metrics), `sagemath/docs/{scope}` (doc links).

## Deployment

- **stdio** (default, for Claude Desktop): `uv run sagemath-mcp`
- **HTTP**: `uv run sagemath-mcp -- --transport streamable-http --host 127.0.0.1 --port 8314`
- **Docker Compose**: `docker compose up --build` (port 8314)
- **Kubernetes**: Helm chart in `charts/sagemath-mcp/`; enforces non-root user (UID/GID 1000)

## CI/CD

- **ci.yml**: lint, unit tests, integration tests (Sage Docker service), Docker Compose smoke test, build artifacts. Runs on push to main and PRs.
- **release.yml**: triggered by `vX.Y.Z` tags. Tests on Python 3.11/3.12/3.13, builds wheel/sdist, pushes signed Docker image to GHCR, publishes to PyPI.
- **version-bump.yml**: manual workflow to bump version in pyproject.toml and create tag.

## Key Conventions

- Configure Git hooks after cloning: `git config core.hooksPath .githooks` (pre-push runs ruff).
- Update `README.md`, `USAGE.md`, and monitoring docs when changing CLI flags, security toggles, or observability.
- Use `cancel_sage_session` instead of force-stopping long computations.
- Containerized workflows expect writable volumes for UID/GID 1000.
