# Agent Playbook

## Environment & Setup
- `uv pip install -e .[dev]` primes the venv with runtime+dev extras; prefer `sage -python -m uv ...` inside the Docker image.
- `make sage-container` (script: `scripts/setup_sage_container.sh`) ensures the Sage runtime is available for integration work.
- Keep `TODO.md` in sync with outstanding initiatives; the unchecked items at the bottom reflect the current priority queue.
- `docker-compose.yml` spins up the Sage-backed MCP server locally; the Helm chart under `charts/sagemath-mcp` mirrors the deployment knobs for Kubernetes and enforces the non-root `sage` user (UID/GID 1000).

## Fast Commands
- `make lint` → `uv run ruff check`
- `make test` → pure-Python pytest suite (`uv run pytest`)
- `make integration-test` → runs pytest inside the Sage container and captures logs (`integration.log`, `integration-artifacts.tar.gz`)
- `make build` → `uv run python scripts/build_release.py` (sdist/wheel; respects prerequisite guardrails)
- `make all` → convenience alias (`make test` + `make integration-test`); keep targets separate when adding CI steps.

## Testing Expectations
- Add new tests under `tests/`, mirroring the module under `src/`; mark async cases with `@pytest.mark.asyncio`.
- Exercise both `make test` and `make integration-test` before landing changes; the latter requires the Sage container.
- Cover MCP helper tools and `_evaluate_structured` flows in `tests/test_server.py`; use `tests/test_use_cases.py` for Sage-manual scenarios.
- When introducing monitoring/security changes, ensure corresponding metrics assertions or timeout/cancellation cases land in integration tests.

## Documentation & Release Hygiene
- Update `README.md`, `USAGE.md`, and the monitoring docs whenever you touch CLI flags, security toggles, or observability outputs.
- Surface new automation (e.g., build pipeline steps, artifact locations) in `AGENTS.md` and `TODO.md` so follow-on work is visible.
- Keep distribution guidance current (`INSTALLATION.md`, `DISTRIBUTION.md`) and maintain cross-platform notes (Windows/macOS).

## Pending Focus Areas (from `TODO.md`)
- Extend CI release flow to publish a Docker image (ghcr.io) alongside PyPI artifacts.
- Document CLI arguments/help output in the primary docs.
- Add an integration test that validates monitoring metrics during timeout/cancellation scenarios using real Sage.
- Update Helm image defaults once the GHCR publication workflow is live.

## Extra Tips
- Use `cancel_sage_session` instead of force-stopping long Sage computations.
- Keep comments concise; explain non-obvious security or monitoring decisions inline.
- Capture and attach integration artifacts/logs when debugging or updating CI.
- Containerized workflows expect writable volumes for UID/GID 1000; adjust permissions when mounting host paths.
