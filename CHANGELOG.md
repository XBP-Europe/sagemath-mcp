# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security

- **Caller strings interpolated into trusted code no longer reach `sage_eval`.** Four
  tool parameters -- `graph_operation.graph`, `group_operation.group`,
  `coding_theory_operation.code_type` and `polynomial_ring_operation.base_ring` -- were
  embedded into generated Sage without validation. Generated code runs under a policy
  that re-permits `sage_eval` (every helper template is built on it), so a crafted
  parameter reached arbitrary execution: reading files, running shell commands and
  opening outbound connections were all demonstrated against a real SageMath runtime.
  All four now pass the same validation gate as every other expression, variable names
  must be plain identifiers, and a test fails the build if any future tool interpolates
  a caller string without a gate.
- **Forbidden names are rejected wherever they are read**, not only where they are
  called. `f = open` followed by `f("/etc/passwd")`, a `lambda` default, or a list
  literal all bypassed the previous check, through the specialized tools as well as
  `evaluate_sage`. The same applies to module names: `m = os` and
  `from sage.all import os as m` both returned the container uid.
- The worker namespace no longer contains `open`, `eval`, `exec`, `compile`, `input`,
  `breakpoint`, `globals`, `locals`, `vars`, `memoryview`, `help`, `exit` or `quit`, as a
  backstop for spellings the validator does not see.

### Changed

- **`interrupt_sage_session` no longer signals an idle worker.** When nothing is running
  it returns `No running computation in session '<name>'` instead of claiming state was
  preserved. Signalling an idle worker was not harmless: it is blocked reading its input,
  where the signal has no computation to abort, and a real Sage worker was left unable to
  answer the next request -- which then timed out and restarted it, destroying the
  namespace the interrupt exists to protect.
- The container runs with a read-only root filesystem, writable `tmpfs` for `/tmp` and
  Sage's own directory only. The Helm chart gained `readOnlyRootFilesystem`, matching
  `emptyDir` scratch, and default CPU and memory requests and limits.

### Internal

- `server.py` split from 2327 lines into `app.py` (the FastMCP object and lifecycle),
  `runtime.py` (settings and session manager), `codegen.py` (the code-building helpers)
  and a `tools/` package by domain. Tool names, schemas and descriptions are unchanged
  and held that way by a committed snapshot test; `from sagemath_mcp import server`
  still works.
- Coverage raised to 100% of statements and branches, enforced in CI.

### Added

- **`interrupt_sage_session`** stops a running computation while keeping every variable
  defined so far. The worker turns the signal into an `Interrupted` response rather than
  exiting, so the namespace survives. `cancel_sage_session` still restarts the worker and
  is now documented as the escape hatch for a wedged one, not the first resort. POSIX
  only.
- **Named workspaces.** `start_sage_session`, `list_sage_sessions` and
  `stop_sage_session`, plus an optional `session` argument on the tools that carry state.
  Workspaces have independent variables, so a long exploration and a scratch calculation
  no longer collide. Omitting `session` uses `default`, which behaves exactly as before,
  and the default workspace still keys on the bare client scope so persisted journals
  keep working.

## [0.4.0] - 2026-08-13

A correctness release. Several tools returned wrong values or did not work at all,
so **output changes for anything relying on the previous behaviour** — hence a minor
bump rather than a patch.

### Changed — output differs from 0.3.1

- **`distribution_operation`** now computes `mean` and `variance` analytically.
  `mean` previously evaluated `get_random_element()`, returning a random draw from
  the distribution — a different wrong answer on every call — and `variance` was
  hardcoded to `null`.
- **`distribution_operation`** now honours both parameters of the normal
  distribution. `mu` was ignored entirely and `sigma` was dropped unless exactly one
  parameter was passed, so `[0, 3]` silently computed with `sigma=1` and `[5, 2]` was
  centred on 0.
- **`matrix_operation([])`** is now rejected. It previously reported a determinant of
  `1.0`, because Sage reads `[]` as the 0×0 matrix whose determinant is 1 by
  convention — an obvious input mistake producing a plausible-looking number.
- **`geometry_operation("distance", ...)`** with fewer than two points is now
  rejected. It previously returned `{"result": null}`, presenting a missing answer as
  an answer.
- **Base image** moved to `sagemath/sagemath:10.9`. The `sage` account is **uid/gid
  1001** in 10.9, where it was 1000 in 10.5. Deployments pinning the old numeric UID
  must be updated; `docker-compose.yml` no longer hardcodes one, and the Helm chart
  now uses 1001.

### Fixed

- **`solve_ode`** rejected the spelling its own documentation advertised. `diff(y(x),
  x)` failed with *"Substitution using function-call syntax and unnamed arguments has
  been removed"*, because the dependent name was bound to the applied expression, so
  `y(x)` became `(y(x))(x)`. Both `diff(y(x), x)` and `diff(y, x)` now work and give
  identical results. ([#12](https://github.com/XBP-Europe/sagemath-mcp/issues/12))
- **All three plot tools** were non-functional. They passed a `BytesIO` to Sage's
  `save()`, which requires a filesystem path. 2D plots now render through the
  matplotlib figure; 3D surfaces are sampled and drawn through matplotlib's 3D axes,
  since `Graphics3d` has no in-memory export.
- **Results larger than 64 KiB** failed with `LimitOverrunError`. A response is read
  with a single `readline()`, and asyncio's default stream limit is 64 KiB; a
  base64-encoded 3D plot is around 100 KiB. Raised to 8 MiB. This affected any large
  result, not only plots.
- **`geometry_operation("distance", ...)`** computed `sqrt(-3)` for a 3-4-5 triangle.
  The generated code used `(a-b)^2`, and `^` is XOR in Python, not exponentiation.
- **`boolean_algebra_operation`** rejected the documented `x*y + x*z + y*z` with
  *"name 'x' is not defined"*, because the ring generators are `x0, x1, x2`. Both
  spellings now parse.
- **`coding_theory_operation`** documented `ReedSolomonCode(GF(7),3,5)`, which is not
  a valid constructor in current Sage. The documented example is now
  `GeneralizedReedSolomonCode(GF(7).list()[:6],3)`.
- **`graph_operation`** rejected every parameterised constructor. `CompleteGraph(4)`
  failed with *"name 'CompleteGraph' is not defined"*, which covered most of Sage's
  catalogue. Bare names, explicit calls, parameterised constructors and adjacency
  dicts all work.
- **Symbolic bounds** are accepted by `integrate_expression`, `limit_expression`,
  `series_expansion` and `symbolic_sum`. Integrating to `a` or summing to `n`
  previously raised `NameError`. Note that `n` and `N` are `numerical_approx` in
  Sage's namespace; short names are now treated as free symbols, while `e`, `i` and
  `I` keep their meaning as constants.
- **Newlines in expressions** no longer raise a syntax error. These tools evaluate a
  single expression, so whitespace is folded before evaluation. `evaluate_sage` is
  unaffected and keeps its newlines.
- **`matrix_multiply`** reports the offending shapes instead of Sage's *"unsupported
  operand parent(s) for \*"*.
- **`statistics_summary([])`** reports what it needs instead of *"list index out of
  range"*.
- **Operation names** tolerate surrounding whitespace across all twelve tools that
  take one.

### Added

- `tests/test_math_examples.py` — every Sage-backed tool is exercised with the
  examples from its own parameter documentation, against a real Sage runtime.
- `tests/test_syntax_variants.py` — the input spellings each tool must accept,
  organised by parameter kind. Equivalent spellings must produce equal results, and
  invalid input must fail cleanly rather than return a wrong value.
- `tests/test_generated_code_lint.py` — static checks needing no Sage: `^` in
  generated Python, `save()` to a buffer, and **any documented example that no test
  exercises**, which is the guard that makes issue #12 structurally impossible.

### Infrastructure

- **Integration tests now actually run.** The Makefile exec'd `sage-mcp` while CI
  named the container `sage-mcp-ci`, so every run failed with *"No such container"* —
  and because the command was piped to `tee`, the exit status was `tee`'s and the job
  reported success. Every previous green integration result was meaningless.
- **`pip-audit` is blocking.** It was `continue-on-error`, which is why an authlib
  advisory (PYSEC-2026-1201) sat in green builds. Transitive dependencies were
  upgraded to clear 32 findings.
- GitHub Actions upgraded across the board; dependency floors raised to match the
  versions actually resolved.
- Added `.dockerignore`. Without it `COPY . /workspace` ingested the local `.venv`
  and `.git`, baking a host-built virtualenv into the image.
- `scripts/bump_version.py` now updates `charts/sagemath-mcp/Chart.yaml`, which had
  been left behind at every previous release.
- `version-bump.yml` opens a pull request instead of pushing to `main`, which is now
  a protected branch.

[0.4.0]: https://github.com/XBP-Europe/sagemath-mcp/releases/tag/v0.4.0
