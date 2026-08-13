# Testing Guide

## Overview

The suite has two halves. Unit tests stub the Sage worker and run anywhere; integration
tests evaluate real Sage code and only run where Sage is available.

That split matters, because the stubbed half cannot see the code the server *generates*.
Issue #12 was a tool rejecting the exact input its own documentation advertised, and it
was invisible to unit tests for precisely that reason. The suites below exist to close
that gap.

| File | Needs Sage | Covers |
|------|-----------|--------|
| `test_session.py` | no | Stateful execution, reset/cancel, timeouts, idle culling |
| `test_server.py` | no | MCP bindings, progress events, error surfacing, doc resources |
| `test_security.py` | no | AST policy: blocked imports, calls, attributes |
| `test_config.py` | no | Environment overrides and invalid values |
| `test_generated_code_lint.py` | no | Static checks over the code `server.py` generates |
| `test_integration.py` | **yes** | Real Sage session lifecycle, monitoring, large payloads |
| `test_math_examples.py` | **yes** | Every tool against the examples in its own documentation |
| `test_syntax_variants.py` | **yes** | The input spellings each tool must accept or reject |
| `test_use_cases.py` | **yes** | End-to-end workflows mirroring real LLM usage |

## Requirements

- Python 3.12+ and `uv`
- Development extras: `uv pip install -e .[dev]`
- Unit tests need no Sage; they force `SAGEMATH_MCP_PURE_PYTHON=1` and run the worker in
  Python mode

## Running

```bash
make test                      # unit suite, no Sage required
make lint                      # ruff
uv run pytest tests/test_session.py -k test_session_stateful_evaluation   # one test
```

Integration tests need a Sage container with the repository mounted at `/workspace`:

```bash
make sage-container            # start it (reads the image from the Dockerfile)
make sage-deps                 # install the dev extras into Sage's own Python
make integration-test          # run the suite inside the container
```

`make sage-deps` is not optional. Sage bundles `pytest` but **not** `pytest-asyncio`, so
without it every async test errors with *"async def functions are not natively
supported"*. `make integration-test` depends on it, so running that target alone is
enough.

To point at a different container, set `SAGEMATH_MCP_DOCKER_CONTAINER`; both the Makefile
and `scripts/setup_sage_container.sh` honour it, and they must agree. They did not for a
long period, and because the command was piped to `tee`, the failure was masked by
`tee`'s exit status and CI reported success while running nothing.

## Client integration (Claude, Gemini, Codex)

Two suites drive real CLIs against a real server. Both are opt-in: they consume
API quota and take minutes, so neither runs in CI.

```bash
make cli-integration     # 44 breadth cases, Claude and Gemini
make cli-extended        # tool-forcing cases across all three CLIs
uv run python -m tests.cli_integration.run_extended --cli codex --case ext-comb-bell
```

`cli-extended` exists because grepping a CLI's answer cannot tell a working MCP
integration from a model answering out of its own memory. Asked to differentiate
`x^3 + 2x`, every model replies `3x^2 + 2` without touching any tool — and a
substring check passes.

It closes that in two ways:

1. **Questions that force the tool.** `next_prime(10^30)`, Bell(25), the number
   of partitions of 120, a 5×5 determinant. A model that skips the server gets
   them wrong.
2. **Evidence from the wire.** `mcp_proxy.py` sits between the CLI and the
   server, forwarding frames verbatim while recording every `tools/call` and
   whether it returned an error. A case fails as `NO_TOOL_CALL` when the answer
   is right but nothing was called.

That second check is the one that matters, and it is worth confirming it can
fail: feed the validator a correct answer with an empty log and it reports
`NO_TOOL_CALL`, not `PASS`.

Two cases are stateful on purpose. They define a variable in one call and read
it in a second, which no model can fake, so they prove session state survives
between separate MCP invocations.

Each CLI needs its own flag to use tools non-interactively: Claude
`--allowedTools`, Gemini `--yolo`, Codex `exec --skip-git-repo-check`. Without
them the model silently declines every call and the run looks like a server
failure.

## Writing tests

**Assert a value, not the absence of an exception.** `distribution_operation` returned a
random sample as the distribution's mean and `null` as its variance. Both would pass a
check that only confirmed no exception was raised.

**Prove a regression test fails without its fix.** Stash the change, run the test, confirm
it fails with the expected error, restore. A test that has never failed is not known to
test anything.

**Document a spelling and it becomes required.** `test_generated_code_lint.py` extracts
every example from the tools' `Field(description=...)` text and asserts each appears in a
test. Adding an example to a docstring without a matching test fails the unit suite.

**Prefer equivalence over expected values where possible.** `test_syntax_variants.py`
asserts that spellings meaning the same thing produce the same answer. That needs no
hardcoded expectation and catches silently-wrong results, not just errors.

## Key fixtures

- `FakeContext` (`tests/conftest.py`) — captures info/warning/progress events emitted
  through the MCP `Context`
- `python_settings` (`tests/test_session.py`) — injects `force_python_worker=True`
- `requires_sage` — skips when no `sage` executable is on PATH
- Async tests use `asyncio_mode = "auto"`; do not call `asyncio.run` directly

## CI

Seven jobs, all required by branch protection on `main`: `lint`, `test (3.12)`,
`test (3.13)`, `security`, `helm`, `integration`, `smoke`.

- `integration` starts the Sage container itself and reads the image from the Dockerfile,
  so the Sage version has a single source of truth
- `security` runs `pip-audit` and is **blocking**; a new upstream advisory turns CI red
  with no repository change
- `smoke` brings up the compose stack and runs `scripts/exercise_mcp.py` plus the
  monitoring resource check

Renaming a CI job means updating the required-checks list in branch protection too.
Otherwise the old name stays required and every pull request waits forever on a check
that will never report.
