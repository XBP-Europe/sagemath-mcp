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

Ruff with line-length 100, target Python 3.12. Rules: E, F, W, B, UP, ASYNC, RUF, I (import sorting). Run `make lint` before committing.

## Testing

- All async tests use `@pytest.mark.asyncio` (asyncio_mode is "auto")
- Tests mirror source modules: `test_server.py`, `test_session.py`, `test_security.py`, `test_config.py`, etc.
- `test_integration.py`, `test_use_cases.py` and most of `test_math_coverage.py` require the Sage container
- Key fixtures: `python_settings` (injects `force_python_worker=True`), `FakeContext` (captures MCP context messages)

## Architecture

**Source lives in `src/sagemath_mcp/`:**

- `server.py` - Entry point: the `/health` route, `main()`, and the imports that register the tools. Re-exports the tool functions, so `from sagemath_mcp import server` keeps working.
- `app.py` - The FastMCP object, instructions, lifespan and middleware. Owns `mcp` so tool modules can decorate against it without importing the module that imports them.
- `runtime.py` - `SETTINGS`, `SESSION_MANAGER` and `resolve_session()`. Read the manager through this module (never `from .runtime import SESSION_MANAGER`) so tests can swap it.
- `codegen.py` - Building the Sage snippets: prelude, literal encoding, the validation gates and the numeric guards. Any caller string reaching a template must pass a gate — generated code runs under `trusted_policy()`, which permits `sage_eval`.
- `tools/` - The 37 tools and 3 resources by domain: `session`, `core`, `calculus`, `algebra`, `discrete`, `stats`, `plotting`. A module missing from `tools/__init__.py` registers nothing.
- `session.py` - `SageSessionManager` (per-client session map with asyncio locks) and `SageSession` (spawns/manages `_sage_worker.py` subprocess via JSON stdin/stdout protocol).
- `_sage_worker.py` - Subprocess worker that executes code in a persistent namespace. Handles execute/reset/shutdown commands. Validates AST before compilation.
- `security.py` - AST validator enforcing `SecurityPolicy`. **Caller code is deny-by-default**: a name is refused unless the allowlist offers it or the caller's own code bound it. On top of that it blocks imports outright, `eval`/`exec`, dunder access, string-path attribute primitives (`attrgetter` and friends, which defeat every AST attribute rule), forbidden modules and known code-executing Sage helpers. Configurable via env vars.
- `allowlist.py` - **Generated, never hand-edited.** The names caller code may read, produced from the installed Sage by `scripts/generate_allowlist.py` (`make allowlist`, which writes through a temp file because the generator imports the module it replaces). An integration test and a weekly job fail when it and the installed Sage disagree.
- `symbols.py` - `PREDEFINED_SYMBOLS`, the one source of truth for `x, y, z, t`. Read by the worker, the generated prelude and the refusal message; a test asserts they agree, because them disagreeing is what made the tools and `evaluate_sage` accept different mathematics.
- `text.py` - Strings shared between the tool modules and the app. They are part of the tool contract, so they live where both can reach them without a cycle.
- `config.py` - `SageSettings` dataclass driven by `SAGEMATH_MCP_*` environment variables.
- `models.py` - Pydantic models for results (`EvaluateResult`, `SessionSnapshot`, `MonitoringSnapshot`).
- `monitoring.py` - Thread-safe `EvaluationMetrics` (counters, latency, error tracking).

**Invariants that bite.** These are enforced by tests, and each one exists because
it was violated:

- Coverage is gated at 100% (statements and branches). Unreachable branches get
  deleted, not exempted.
- Tool names, schemas and descriptions are snapshotted (`tests/test_tool_inventory.py`).
  Changing a tool means regenerating it deliberately: `python -m tests.test_tool_inventory --write`.
- Any caller string interpolated into generated Sage must pass `_encode_literal`,
  `_validated_expression` or `_validated_identifier`. Generated code runs under
  `trusted_policy()`, which permits `sage_eval`, so an ungated string is arbitrary
  execution. A structural test enforces this.
- `evaluate_sage` preparses caller code (Sage semantics: `2^3` is 8; `x`, `y`, `z`, `t` predefined). Shared indentation is stripped first, so a snippet pasted out of a markdown block is accepted.
  Generated templates are **not** preparsed and must not use `^` — a lint enforces that.
- The worker strips Sage helpers that execute, compile, fetch or pickle, plus every
  external CAS interface, from a baked-in list; an integration test re-derives it
  from the installed Sage so a version bump cannot reopen the hole.
- The allowlist is generated, not written. Regenerate with `make allowlist` and
  **review every added name** -- a new helper that compiles, spawns or writes
  belongs in `_DANGEROUS_BARE_NAMES` instead. A provenance entry in
  `_DANGEROUS_SAGE_MODULES` that matches no names fails an integration test:
  `sage.libs.pari.all` was added once and removed nothing, because that
  derivation only takes names *defined* in the module.
- `tests/test_math_coverage.py` is the counterweight to the security suite.
  Every security test asserts something is blocked, so a policy that refused
  everything would pass all of them; that file asserts mathematics still works,
  in binding forms, truths Sage evaluates, equivalent spellings and preparser
  behaviour.
- Security fixes are written test-first, verified against **real Sage**, and recorded
  in `REVIEW_ACTIONS.md`.

**Request flow:** MCP client -> a tool in `tools/` -> `SageSessionManager.get_or_create()` -> `SageSession.evaluate()` -> JSON request to `_sage_worker.py` subprocess -> AST validation -> exec in persistent namespace -> JSON response back.

**MCP tools (37, 31 Sage-backed):** `evaluate_sage` (core), `evaluate_sage_streaming`, `reset_sage_session`, `cancel_sage_session`, `interrupt_sage_session` (stops a computation but keeps variables -- prefer it over cancelling), and the named-workspace trio `start_sage_session`, `list_sage_sessions`, `stop_sage_session`, plus 29 math/domain helpers: `calculate_expression`, `solve_equation`, `differentiate_expression`, `integrate_expression`, `simplify_expression`, `expand_expression`, `factor_expression`, `limit_expression`, `series_expansion`, `symbolic_sum`, `matrix_multiply`, `matrix_operation`, `solve_ode`, `number_theory_operation`, `combinatorics_operation`, `statistics_summary`, `distribution_operation`, `plot_expression`, `plot3d_expression`, `plot_multi_expression`, `find_root`, `vector_calculus_operation`, `graph_operation`, `group_operation`, `elliptic_curve_operation`, `coding_theory_operation`, `boolean_algebra_operation`, `polynomial_ring_operation`, `geometry_operation`. Plus HTTP `/health` endpoint.

**MCP resources:** `sagemath/session/{scope}` (session snapshots), `sagemath/monitoring/{scope}` (metrics), `sagemath/docs/{scope}` (doc links).

## Deployment

- **stdio** (default, for Claude Desktop): `uv run sagemath-mcp`
- **HTTP**: `uv run sagemath-mcp --transport streamable-http --host 127.0.0.1 --port 8314`
- **Docker Compose**: `docker compose up --build` (port 8314)
- **Kubernetes**: Helm chart in `charts/sagemath-mcp/`; enforces non-root user (UID/GID 1001, matching `sage` in SageMath 10.9)

## CI/CD

- **ci.yml**: lint, unit tests, integration tests (Sage Docker service), Docker Compose smoke test, build artifacts. Runs on push to main and PRs.
- **release.yml**: triggered by `vX.Y.Z` tags. Tests on Python 3.12/3.13, builds wheel/sdist, pushes signed Docker image to GHCR, publishes to PyPI.
- **version-bump.yml**: manual workflow to bump version in pyproject.toml and create tag.

## Key Conventions

- Configure Git hooks after cloning: `git config core.hooksPath .githooks` (pre-push runs ruff).
- Update `README.md`, `USAGE.md`, and monitoring docs when changing CLI flags, security toggles, or observability.
- Use `interrupt_sage_session` to stop a long computation -- it keeps the session's variables. `cancel_sage_session` restarts the worker and discards them.
- Containerized workflows expect writable volumes for UID/GID 1001 (the `sage` user in SageMath 10.9).
