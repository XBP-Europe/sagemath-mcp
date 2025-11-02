# Testing Guide

## Overview
The test suite verifies Sage session management, MCP tooling, and HTTP-facing helpers.  
Primary goals:
- Validate stateful execution, reset/cancel semantics, and timeout handling (`tests/test_session.py`).
- Confirm MCP bindings emit progress, surface errors, and expose documentation resources (`tests/test_server.py`).

## Requirements
- Python 3.11+ and `uv`.  
- Development extras installed:  
  ```bash
  uv pip install -e .[dev]
  ```
- For pure unit tests no Sage install is required—the suite forces `SAGEMATH_MCP_PURE_PYTHON=1` and runs the worker in Python mode.

## Running Tests
```bash
uv run pytest            # execute entire suite
uv run pytest tests/test_session.py::test_session_stateful_evaluation  # single test
```
Pytest discovers modules inside the `tests/` directory. The configuration is defined in `pyproject.toml` (`asyncio_mode = "auto"`).

For integration coverage with a real Sage runtime, either start the helper container (`make sage-container`)
or bring up the compose stack:

```bash
docker compose up --build -d
uv run pytest tests/test_integration.py
```

CI runs `make all` (unit + integration targets) and captures logs in `integration-artifacts.tar.gz`.

## Key Fixtures & Patterns
- `python_settings` fixture in `tests/test_session.py`: injects `force_python_worker=True` to bypass Sage dependencies.
- `FakeContext` in `tests/test_server.py`: captures info/warning/progress events emitted via the MCP `Context` during tool execution.
- Async tests use `@pytest.mark.asyncio`; avoid direct `asyncio.run` in tests.
- `tests/test_config.py` exercises invalid environment overrides to guard the new non-root and timeout
  settings exposed through `SageSettings`.

## Coverage Focus
- Session lifecycle: `evaluate`, `reset`, `cancel`, idle culling, graceful shutdown.
- Stateful chat workflows: `tests/test_server.py::test_llm_stateful_average_workflow` and `test_llm_reuses_defined_function` mirror real LLM usage.
- Error translation & security: `SageEvaluationError` for security violations, metrics recording, and monitoring resource snapshots.
- Documentation/resource exposure: confirm `resource://sagemath/docs/all` and `resource://sagemath/monitoring/metrics` respond as expected.

## Maintaining Tests
- Mirror new modules with corresponding files under `tests/` to keep scope targeted.
- Prefer dependency injection (monkeypatching `SESSION_MANAGER.get/cancel`) over hitting live Sage for unit coverage.
- When adding features that depend on actual Sage behavior, extend `tests/test_integration.py` and run them inside the Sage container.
- Ensure new tests run cleanly with `uv run pytest` before submission; lint additional files with `uv run ruff check`.
- When touching container orchestration or Helm manifests, add smoke coverage by invoking the compose
  stack or port-forwarding a Helm release and re-running `scripts/exercise_mcp.py` against it.
