# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security

- **String-path attribute access is refused.** Every attribute rule in this
  server is enforced on the AST, and `operator.attrgetter` takes its path as a
  runtime string the AST never sees — so
  `operator.attrgetter("misc.persist.unpickle_global")(sage)` returned the real
  function, which is arbitrary code execution, and
  `operator.attrgetter("__builtins__")(warnings)` returned the builtins dict.
  Sage binds 22 module objects including `sage` itself, so one such primitive
  reaches the whole tree; `getattr`, `setattr` and `vars` were already refused,
  which left `operator` as the only way in. `attrgetter`, `methodcaller` and
  `itemgetter` are now forbidden calls and `operator` a forbidden attribute
  parent.
- **A dangerous-module entry that removed nothing.** `sage.libs.pari.all` was
  listed after `pari` was found to run a shell, and contributed zero names: the
  derivation takes only names *defined* in a module, and PARI's are defined in
  `cypari2`. The removal that worked was the explicit one. An integration test
  now fails on any provenance entry matching no names, so an entry that looks
  like protection and is not cannot be added silently.
- **`pari` executed shell commands.** `pari('system("id > /tmp/x")')` wrote a
  file as the container user. The scrub that removed `gp` and `maxima` works
  from `sage.interfaces.all`, and the PARI *library* interface comes from
  `sage.libs.pari`, so it was never covered.
- **`oeis` reached the network**, and `install_doc`, `show`, `view`, `animate`,
  `html` and `latex` each wrote to disk or read the installation. All are
  removed from the caller namespace. Plotting and LaTeX output are unaffected:
  the plot tools render through `.savefig(BytesIO)`, and `latex` is imported
  from `sage.all` inside the worker rather than read from that namespace.


- **Caller code is checked against an allowlist.** A name may be read only if
  this server offers it: the mathematical names SageMath preloads, the safe
  builtins, and whatever the caller defines itself -- including names created
  earlier in the same session, which the worker reports so stateful use keeps
  working. Everything else is refused. Seven bypasses in two days were each a
  name nobody had forbidden, and this changes the default for the next one: a
  helper a future SageMath adds is denied until someone reviews it. An
  integration test, plus a weekly scheduled job, fails when the allowlist and the
  installed Sage disagree.

  Tool *parameters* keep the previous rules and are not allowlisted -- they name
  things valid in a template's context (`HammingCode` inside `codes.`), and the
  denylist, import ban and persistence rules all still apply to them.

- **A caller binding can no longer authorize a dunder.** Names the caller's own
  code binds are trusted without consulting the allowlist, and binding is judged
  statically — `if False: __builtins__ = 1` counts, as does `except ValueError as
  __builtins__`, which never names the object. Every name live in the worker
  namespace is allowlisted except nine dunders, and `__builtins__['__import__']
  ('os')` is a shell. Reading a dunder was already blocked by its own rule, so
  this was the second lock rather than the first; bindings now drop dunders so
  the allowlist does not depend on a rule enforced elsewhere. The drift test
  checks the shape of the gap rather than filtering it out of the comparison.
- **Caller code can no longer import anything.** `sage.*` was allowlisted for the
  generated prelude, and callers used it to re-import every helper the worker
  namespace scrub had removed: `from sage.misc.cython import compile_and_load`
  compiled and loaded a module, `from sage.interfaces.gp import Gp` spawned GP,
  and `unpickle_global('os', 'system')('id')` ran a shell command. The allowlist
  now belongs to the generated templates alone. **Breaking for callers who
  imported** — `import math`, `from sage.all import factorial` — but the names are
  already in the namespace without them.
- **Caller code cannot write files.** `.save()` was blocked; `.dump()`,
  `.save_image()` and `.export_jmol()` were not, and each wrote a real file.
  Persistence is matched by prefix (`save*`, `dump*`, `export*`) for callers; the
  plot templates keep `.savefig(BytesIO)`.
- **Sage's external CAS interfaces are no longer reachable.** `gp` and `maxima`
  both executed shell commands through their own `system` escapes --
  `gp('system("id > /tmp/x")')` wrote a file as the container user. Everything
  `sage.interfaces.all` exports is removed from the worker namespace, so a
  future Sage release adding an interface is covered without anyone updating a
  list. The libraries are untouched: Gröbner bases still go through libsingular
  and factoring through PARI, in-process.
- **Sage helpers that execute, compile, fetch or write are removed by
  provenance.** `cython(get_remote_file(url))` was download, compile and execute
  in one expression; `sh()` runs a shell; `loads` is code execution from bytes.
  Names from fifteen modules are stripped at worker startup, which covers the
  helper nobody has thought of yet. Doing this by walking the namespace instead
  forced every lazy import to resolve and put 1.8s into the first evaluation, so
  it resolves only those modules.
- **Forbidden functions are blocked through attribute chains.**
  `sage.misc.sage_eval.sage_eval("__import__('os').getuid()")` returned the
  container uid: the name checks looked at bare names and call targets, and
  `sage` is an allowed import root, so the same function was reachable one dot
  further along. The final name is what is checked now, however it is spelled.
- **`load()` and `attach()` are forbidden for callers.** They execute whatever
  path they are given and `load()` accepts a URL, so this was remote code
  execution from a name no rule mentioned.
- **`docker compose up` no longer publishes on every interface.** The port
  mapping was `8314:8314`, which binds all interfaces on the host; the server
  evaluates code and authenticates nobody, so following the quickstart put an
  unauthenticated Sage evaluator on the local network. It now publishes to
  `127.0.0.1:8314`, and a test fails if that widens again. Every other default
  was already loopback (stdio transport, `--host 127.0.0.1`, `ClusterIP`
  service), which is what made the compose mapping stand out.
- `USAGE.md` showed `--host 0.0.0.0` without qualification. It is correct inside
  a container, where the published port decides reachability, and wrong on a
  host; that distinction is now stated where the command appears.

### Added

- **A suite for mathematics that must work** (`tests/test_math_coverage.py`).
  The security suite asserts things are blocked, so a policy that refused
  everything would pass all of it. This covers the opposite failure, in six
  layers: 34 binding forms, the same forms across calls, 72 mathematical truths
  Sage itself evaluates, 19 groups of equivalent spellings that must agree, 17
  preparser forms, and allowlist reachability by area with a size floor. Layers
  that need no Sage run in the fast job, because that is where allowlist
  regressions come from.

### Changed

- **`x`, `y`, `z` and `t` are now predefined for caller code.** Sage's REPL
  predefines `x` alone, but the specialised tools have always declared four in
  their prelude, so `differentiate_expression("x^2*y^3")` worked while the same
  mathematics through `evaluate_sage` failed. Both paths now read one constant
  (`symbols.PREDEFINED_SYMBOLS`), with a test asserting they agree. Four and no
  more: `y`, `z` and `t` are unbound in a fresh Sage namespace, whereas `n` and
  `i` are numerical approximation and the Gaussian imaginary unit. A mistyped
  `y` now becomes a symbolic variable rather than an error, which is already
  true of `x` in Sage.

- **`evaluate_sage` now runs SageMath, not Python.** Caller code goes through
  Sage's preparser, as the Sage REPL does, so `2^3` is 8 rather than 1, integer
  literals are Sage `Integer`s, generator syntax like `K.<a> = NumberField(...)`
  parses, and `x` is predefined. The tool advertised "SageMath code" and executed
  plain Python; five of the seven examples in its own description could not run.
  The specialised tools have always preparsed via `sage_eval`, so the two halves
  of the server disagreed about which language they accepted.

  **This changes results for anyone relying on `^` meaning XOR.** Use `^^` for
  XOR, as in Sage. Server-generated templates are deliberately not preparsed.

  Validation reads the preparsed source, so the sandbox is unaffected: payloads
  hidden behind preparser-only syntax are rejected like any other.

### Fixed

- **`match` statements and `function('f')` created unusable variables.** The
  allowlist trusts names the caller's own code binds, and binding was detected
  from `Name` nodes alone: `match` patterns bind through their own node types,
  and Sage's `function('f')` injects a name exactly as `var()` does. Every
  variable in a match statement, and every bare `function()` declaration, read
  as undefined for the rest of the session.
- **Uniformly indented code is no longer refused.** A snippet lifted out of a
  markdown block arrives with four spaces on every line, and was rejected for
  its margin rather than its mathematics. Caller code is dedented before
  validation and before execution; a valid program cannot be changed by it,
  since valid module-level code has no common indent to remove.
- **A refusal now names a fix the caller can perform.** SageMath predefines only
  `x`, so `diff(x^2*y^3, x, y)` needs `var('y')` — but the allowlist answered
  that the name "needs to be added to the allowlist", which is true and useless
  to a model that will simply retry. Short lowercase names are now told to
  declare the symbol.

- `evaluate_sage_streaming` had no error handling at all: a timeout, a security
  violation or a dead worker propagated raw and none were recorded, while
  `evaluate_sage` reported each properly.
- A failed journal write destroyed the previous journal. The superseded file was
  deleted before the new one was written, so a full disk left the session with no
  journal and a stray temporary file. The new file is put in place first now.
- A timed-out evaluation propagated as a bare `TimeoutError`: monitoring recorded
  nothing and the client saw an unstructured error. Both `evaluate_sage` and the
  specialised tools now report it as a tool error carrying the deadline.
- Three examples in the `evaluate_sage` description were wrong under any
  execution model: the Laplace pair needed its symbols declared (Sage's REPL
  predefines only `x`), `desolve_rsolve` does not exist, and
  `continued_fraction` has no `nterms` keyword.

## [0.5.0] - 2026-08-14

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

- **Integer results at or above 2^53 are returned as decimal strings**, and the same parameters accept them on the way in (`combinatorics_operation`, `elliptic_curve_operation`, `graph_operation` vertices joined `number_theory_operation`). They were
  returned as JSON numbers, and JavaScript-based MCP clients parse those as IEEE
  doubles, so exact values were silently corrupted: `bell(30)` reached one CLI as
  `846749014511809388871680` rather than `846749014511809332450147`. Integers
  below the boundary keep their numeric type, so ordinary results are unchanged.
  This mirrors the input side, which has required decimal strings for the same
  values since 0.4.0.
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

## [0.3.1] - 2026-04-03

Patch release fixing the release pipeline; no code changes from 0.3.0.

### Fixed

- Cosign image signing lowercases the GHCR reference, which failed on the
  uppercase in `XBP-Europe`.
- The release build installs `build` before running `python -m build`.
- PyPI trusted publishing configured through a `pypi` GitHub environment.

## [0.3.0] - 2026-04-03

Grew the toolset from 18 to 33, all Sage-backed.

### Added

- `symbolic_sum` (finite and infinite series, products), `combinatorics_operation`
  (binomial, permutations, combinations, partitions, factorial, Catalan,
  Fibonacci, Bell), `plot3d_expression` (surfaces as base64 PNG),
  `distribution_operation` (normal, exponential, Poisson, chi-squared, Student-t,
  uniform, beta, gamma with PDF/CDF/quantile/sampling), `find_root`,
  `plot_multi_expression` and `vector_calculus_operation`.

## [0.2.0] - 2026-04-03

### Added

- 18 MCP tools covering calculus, algebra, linear algebra, ODEs, number theory,
  statistics and plotting.
- CLI integration suite across Claude and Gemini.
- FastMCP 3.x migration, CI modernisation, Docker pinned to SageMath 10.9, Helm
  health probes, Python 3.12 minimum.

## [0.1.2] - 2025-11-02

### Fixed

- Default MCP HTTP port aligned to 8314 across code, docs and deployment
  artifacts.
- Package published to GitHub Packages during release; release workflow creates
  its uv virtual environment.

