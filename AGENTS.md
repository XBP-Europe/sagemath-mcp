# Repository Guidelines

## Project Structure & Module Organization
- `src/sagemath_mcp/`: production code for the SageMath MCP server (`server.py`, `session.py`, `_sage_worker.py`, config/models).
- `scripts/`: operational helpers (e.g., `exercise_mcp.py` for HTTP workflow validation).
- `tests/`: automated test suites; mirrors the layout of `src/` where practical.
- `pyproject.toml`: dependency, tooling, and packaging configuration.

## Build, Test, and Development Commands
- `uv pip install -e .[dev]`: install project plus development extras.
- `make test`: run the local pytest suite (pure-Python worker).
- `make integration-test`: execute the Docker-backed Sage suite.
- `make lint`: run Ruff on the codebase.
- `make build`: produce sdist/wheel artifacts (`scripts/build_release.py`).
- `sage -python scripts/exercise_mcp.py`: smoke test against a running HTTP server.

## Coding Style & Naming Conventions
- Python code targets 3.11+ with Ruff enforced; keep line length ≤100 characters.
- Prefer `snake_case` for variables/functions, `PascalCase` for classes, and module-level constants in `UPPER_SNAKE`.
- When adding environment-driven settings, expose them through `SageSettings` in `config.py` rather than hard-coding.

## Testing Guidelines
- Tests use `pytest` (async support via `pytest-asyncio`). Place new suites under `tests/` and mirror source modules (e.g., `tests/test_session.py`).
- Name async tests with `@pytest.mark.asyncio`; cover stateful session behavior, security policy failures, and monitoring counters.
- Run `uv run pytest` before submitting changes.
- For live Sage coverage, run integration targets inside the container (`docker exec sage-mcp bash -lc 'cd /workspace && sage -python -m pytest'`).
- LLM-style conversational workflows live in `tests/test_server.py`—add similar end-to-end cases when introducing new tools.

## Commit & Pull Request Guidelines
- Write concise commit subjects in the imperative mood (e.g., “Add HTTP driver script”), followed by detailed body text when needed.
- Pull requests should describe the change, reference related issues, and note testing performed (commands + results). Include screenshots or logs for UX/CLI-visible changes when relevant.
- Keep PRs focused; split major features into reviewable chunks and ensure `ruff` + tests are green prior to request.

## Agent-Specific Tips
- When running inside the Sage Docker image, prefer `sage -python -m uv ...` so the MCP server inherits Sage’s runtime paths.
- For long computations, rely on `cancel_sage_session` to reset state instead of interrupting the container.***
