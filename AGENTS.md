# Agent Playbook

## Environment & Setup
- `uv pip install -e .[dev]` primes the venv with runtime+dev extras; prefer `sage -python -m uv ...` inside the Docker image.
- `make sage-container` (script: `scripts/setup_sage_container.sh`) ensures the Sage runtime is available for integration work.
- Keep `TODO.md` in sync with outstanding initiatives; the unchecked items at the bottom reflect the current priority queue.
- `docker-compose.yml` spins up the Sage-backed MCP server locally; the Helm chart under `charts/sagemath-mcp` mirrors the deployment knobs for Kubernetes and enforces the non-root `sage` user (UID/GID 1001 on SageMath 10.9).
- Release workflow publishes signed images to `ghcr.io/xbp-europe/sagemath-mcp`; verify with Cosign if you consume the container directly.
- Configure Git hooks after cloning: `git config core.hooksPath .githooks` (pre-push runs `uv run ruff check`).
- Use `scripts/run_ci_simulation.sh` to approximate `.github/workflows/ci.yml` locally (requires Docker, Helm, uv).

## Fast Commands
- `make lint` → `uv run ruff check`
- `make test` → pure-Python pytest suite (`uv run pytest`)
- `make integration-test` → runs pytest inside the Sage container and captures logs (`integration.log`, `integration-artifacts.tar.gz`)
- `make build` → `uv run python scripts/build_release.py` (sdist/wheel; respects prerequisite guardrails)
- `make all` → convenience alias (`make test` + `make integration-test`); keep targets separate when adding CI steps.

## Where Code Goes
- A new tool belongs in the matching `src/sagemath_mcp/tools/` module (`core`, `calculus`,
  `algebra`, `discrete`, `stats`, `plotting`, `session`) and must be listed in
  `tools/__init__.py` -- a module missing from that list registers nothing.
- Decorate against `mcp` imported from `..app`. Never use FastMCP's `mount`/`import_server`
  to compose them: it prefixes tool names, renaming every tool a client has configured.
- Resolve workers through `runtime.resolve_session(...)`, never a module-level import of
  `SESSION_MANAGER`, which binds the manager that existed at import time.
- Any caller string interpolated into generated code must pass `_encode_literal`,
  `_validated_expression` or `_validated_identifier`. Generated code runs under
  `trusted_policy()`, which permits `sage_eval`, so an ungated string is arbitrary
  execution -- there is a test that fails if one appears.
- Adding a tool changes the MCP contract, so refresh the snapshot deliberately:
  `python -m tests.test_tool_inventory --write`.

## Testing Expectations
- Add new tests under `tests/`, mirroring the module under `src/`; mark async cases with `@pytest.mark.asyncio`.
- Exercise both `make test` and `make integration-test` before landing changes; the latter requires the Sage container.
- Cover MCP helper tools in `tests/test_server.py` and the code-building helpers (`_evaluate_structured`, the prelude, the validation gates) in `tests/test_codegen.py`; use `tests/test_use_cases.py` for Sage-manual scenarios.
- CI enforces `--cov-fail-under=100`, so a new branch needs a test that reaches it.
- When introducing monitoring/security changes, ensure corresponding metrics assertions or timeout/cancellation cases land in integration tests.

## Documentation & Release Hygiene
- Update `README.md`, `USAGE.md`, and the monitoring docs whenever you touch CLI flags, security toggles, or observability outputs.
- Surface new automation (e.g., build pipeline steps, artifact locations) in `AGENTS.md` and `TODO.md` so follow-on work is visible.
- Keep distribution guidance current (`INSTALLATION.md`, `DISTRIBUTION.md`) and maintain cross-platform notes (Windows/macOS).
- Kick off the **Bump Version** workflow ahead of a release to increment the package version and push the matching `vX.Y.Z` tag.

## Completed Focus Areas (from `TODO.md`)

All items from the original TODO are complete. See `TODO.md` for the full checklist.

## Extra Tips
- Use `cancel_sage_session` instead of force-stopping long Sage computations.
- Keep comments concise; explain non-obvious security or monitoring decisions inline.
- Capture and attach integration artifacts/logs when debugging or updating CI.
- Containerized workflows expect writable volumes for UID/GID 1001 (the `sage` user in SageMath 10.9); adjust permissions when mounting host paths.
