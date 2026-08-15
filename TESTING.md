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
| `test_generated_code_lint.py` | no | Static checks over the Sage code the package generates, and the guard that every caller string reaching a template passes a validation gate |
| `test_codegen.py` | no | The code-building helpers: distribution moments, matrix and integer guards, validation gates |
| `test_sage_worker.py` | no | Worker protocol, the streaming stdout buffer, interrupt and startup-failure paths |
| `test_security_bypass.py` | no | Every sandbox escape found so far, each one a regression test |
| `test_cache_isolation.py` | no | Two clients must not share cached tool responses |
| `test_tool_inventory.py` | no | The MCP contract: tool names, schemas and descriptions, against a committed snapshot |
| `test_readme_badges.py` | no | README badge claims against the files that decide them |
| `test_version_consistency.py` | no | Every declared version agrees, and the bump script updates them all |
| `test_math_suite.py` | no | Mathematical results the pure-Python worker can check |
| `test_cli_harness.py` | no | The extended CLI harness's own verdict logic, fed synthetic wire logs |
| `test_math_coverage.py` | **partly** | Mathematics that must *work*: binding forms and allowlist reachability without Sage, then truths Sage evaluates, equivalent spellings and preparser behaviour with it |
| `test_research_workflows.py` | **yes** | Multi-step sessions on open problems — Collatz, Goldbach, twin primes, odd perfect numbers, zeta zeros, BSD, Erdős–Straus, three cubes, abc. The realistic workload, and the strongest stress on the allowlist |
| `test_numerical_workflows.py` | **yes** | Floating point, where the remembered answer is wrong: cancellation, conditioning, Newton's rate, order of accuracy, CFL, stiffness, quadrature over the wrong domain |
| `test_physics_workflows.py` | **yes** | Physics sessions that end at a measured number — Wien and the Sun's temperature, Stefan–Boltzmann, Mercury's 43″/century, the oscillator ladder, anharmonic diagonalisation, phonons, Maxwell, the Bohr radius, a decay fit, the double pendulum |
| `test_sage_doctest_corpus.py` | **yes** | SageMath's own doctests — every `sage: ` example in the installed library — pushed through preparse + the validator, to measure what share of Sage's documented mathematics this server would refuse |
| `test_integration.py` | **yes** | Real Sage session lifecycle, monitoring, large payloads, and the drift checks that keep the allowlist and denylist honest against the installed Sage |
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
make allowlist                 # regenerate the caller allowlist from that Sage
```

`make allowlist` is the one to reach for when the integration suite reports that
the allowlist and the installed Sage disagree — after a Sage upgrade, or after
changing what the worker namespace contains. It writes through a temporary file
because the generator imports the module it replaces, and **every added name is
a name every caller can then use**, so read the diff rather than committing it.

`make sage-deps` is not optional. Sage bundles `pytest` but **not** `pytest-asyncio`, so
without it every async test errors with *"async def functions are not natively
supported"*. `make integration-test` depends on it, so running that target alone is
enough.

To point at a different container, set `SAGEMATH_MCP_DOCKER_CONTAINER`; both the Makefile
and `scripts/setup_sage_container.sh` honour it, and they must agree. They did not for a
long period, and because the command was piped to `tee`, the failure was masked by
`tee`'s exit status and CI reported success while running nothing.

## Client integration (Claude, Gemini, Codex)

These run nightly in CI (`.github/workflows/cli-nightly.yml`, 03:17 UTC) and on
demand via **Actions -> CLI integration (nightly) -> Run workflow**, which takes
a single-CLI option. They are not on the pull-request path: they need model
credentials and cost money per run.

Each CLI needs a repository secret -- `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`,
`OPENAI_API_KEY`. A CLI whose secret is missing is skipped with a notice rather
than failing, so the workflow is useful with one key configured. A failure opens
(or appends to) a single issue, because a nightly nobody watches is a nightly
nobody fixes.

Worth running before a release even if the nightly is green: they are the only
tests that exercise what a client actually does. They caught integers above 2^53
being silently corrupted by JSON-number parsing, which every other suite passed,
because the corruption happens in the client rather than the server.


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

The `numerics` and `physics` domains sharpen point 1. A question with no
memorable answer only tests whether the model *tried*; these have an answer that
is memorable and **wrong** — π²/6 for a sum truncated at 10⁶, `0.5` for a
discretised oscillator, 43″ for Mercury when four figures are 42.98. Recall
lands close enough to sound certain, so the expected values carry more
significant figures than anyone memorises, and the only route to them is the
server.

```bash
uv run python -m tests.cli_integration.run_extended --cli all --domain numerics,physics
```

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

**Test the session, not only the call.** `test_research_workflows.py` runs the
shape real work has — define a helper, sweep a range, find the extreme case,
check it against what is known — across one held session per problem. It is
where an allowlist regression surfaces as a refusal in the middle of ordinary
mathematics, and where state that silently fails to persist between calls shows
up as a `NameError` five steps in. Each test is a sitting at a genuinely open
problem, so the assertions are invariants ("every even number in this range is a
sum of two primes") rather than remembered constants wherever possible.

**End a physics test at a number the session did not choose.**
`test_physics_workflows.py` computes quantities with an external referee — the
CODATA constants, the Sun's effective temperature, Mercury's perihelion advance
— so a sign error, a dropped `c^2` or a solver that quietly returned its initial
condition all fail. "The code ran" is not an assertion. The same file is the
only place the idioms a physicist types are exercised end to end: `V(r) = -1/r`,
`function('theta')(t)`, `desolve_odeint` over `srange`, `units.*`. The first of
those was *refused* by the dunder rule until item 43, and nothing else in the
suite used it.

**Assert the failure mode, not just the success.** `test_numerical_workflows.py`
is built around the cases where a plausible answer is a wrong one: the naive
quadratic formula, a double-precision Hilbert solve whose residual looks fine,
an explicit step across the CFL limit, a quadrature error estimate that is
accurate about the wrong domain. Each test computes the naive result *and* the
trustworthy one and asserts they differ by what the theory predicts, because a
test that only checks the good path cannot tell a working numeric from a lucky
one.

**A suite of blocks needs a counterweight.** Every test in
`test_security_bypass.py` asserts something is *refused*, so a policy that
refused everything would pass all of them — the suite cannot tell "secure" from
"broken". `test_math_coverage.py` asserts the opposite direction and is why
three regressions were caught: `match` statements bound no variables, Sage's
`function('f')` bound nothing, and uniformly indented code was rejected for its
margin rather than its mathematics. Tighten the policy, then run that file.

**Prefer equivalence over expected values where possible.** `test_syntax_variants.py`
asserts that spellings meaning the same thing produce the same answer. That needs no
hardcoded expectation and catches silently-wrong results, not just errors.

**And when a hand-written table is the counterweight, borrow a bigger one.**
`test_math_coverage.py` covers roughly 19 preparser forms and 60 truths, which
is 19 and 60 things somebody thought to type — and the last two policy defects
were both forms nobody had. `test_sage_doctest_corpus.py` closes that by running
**SageMath's own doctests**: every `sage: ` example in the installed library,
432,878 of them, through `preparse` + `validate_module`, grouped by docstring so
names bound early in a block authorise reads later, exactly as a session does.
It takes 48 seconds and answers one question at scale — *would this server
refuse the mathematics SageMath itself documents?* Measured against 10.9: 97.81%
of in-scope examples accepted, every refusal attributable to a rule that is
named and capped in the file, and no allowlist gap in any mathematical name.

### The corpus is SageMath's, and is not in this repository

SageMath is Copyright (C) The Sage Development Team, licensed
**GPL-2.0-or-later**; this project is MIT. The corpus is therefore **read at run
time** from the SageMath installation the tests run against, held in memory, and
never copied into this tree, committed, or redistributed. Only counts reach the
assertions, which is why the baselines are numbers rather than lists of
snippets, and why a failure prints its examples instead of storing them. See
<https://www.sagemath.org/> and <https://github.com/sagemath/sage>.

Two consequences worth knowing. A Sage upgrade moves the baselines — a *drop* in
acceptance is the signal, and the numbers are refreshed by reading the report a
failing assertion prints. And the corpus reaches for capabilities this server
does not offer (imports, persistence, file paths, the external CAS interfaces,
`%` magics, network); those are classified and counted, never asserted over.
Whether blocking them costs anyone their mathematics is a separate question, and
`test_the_blocked_interfaces_do_not_block_the_mathematics` answers it directly:
Gröbner bases, character tables, class numbers, integration and distributions
are each computed through the native in-process path that the blocked interface
would have shelled out to.

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
