# Plan — split `server.py` (review item 4)

> **Done, 2026-08-14 (PR #38).** Kept as the record of what was decided and why.
> Two things went differently from the plan, both worth knowing:
>
> - The 37 `monkeypatch.setattr(server, "SESSION_MANAGER")` sites were retargeted
>   to `runtime` rather than converted to the shared fixture below. Several depend
>   on their own settings, which one fixture would have flattened into an untested
>   default. The fixture exists for new tests.
> - Step 5 was load-bearing, not housekeeping. The generated-code lint resolved
>   `server.py` by path, so after the move it would have passed while inspecting a
>   file with no tools in it. The discovery floor caught that (`assert 0 >= 30`).
>
> Outcome: 2327 lines to 162, contract byte-identical by snapshot test, coverage
> raised to 100% rather than deferred as planned.

`src/sagemath_mcp/server.py` is 2327 lines and carries 37 tools, 3 resources, the
FastMCP application, the runtime state, the code-generation helpers, the health
route and the CLI entry point. It is the last open item from the 2026-08-13
review that is ours to close (item 7's remainder needs account access).

**Goal:** no module over ~350 lines, each with one job, with the public surface —
tool names, schemas, descriptions, the console script and `python -m
sagemath_mcp.server` — provably unchanged.

**Non-goal:** behaviour. This is a move. If a test needs editing, it must be
because a name moved, never because a result changed.

## Decisions taken

| Question | Decision |
|---|---|
| Split shape | Domain packages under `tools/`, with shared helpers extracted |
| Runtime state | Moves to `runtime.py`; the 37 monkeypatch sites become one fixture |
| Coverage | Out of scope — behaviour-identical move, ~88% before and after |
| Delivery | One PR off current `main`, no stack |

Coverage gets its own follow-up: the uncovered clusters are the per-distribution
mean/variance branches, the `_check_matrix`/`_exact_int` rejection paths, the
`_validated_expression` fallbacks and two geometry error paths.

## Target layout

```
src/sagemath_mcp/
  app.py         ~40   the FastMCP object and MCP_INSTRUCTIONS
  runtime.py     ~60   SETTINGS, SESSION_MANAGER, get_session_manager()
  codegen.py    ~300   prelude/encoding/validation/number helpers
  server.py     ~250   lifespan, cull loop, health route, main(), imports for registration
  tools/
    __init__.py   ~20  imports every module so decorators run
    session.py   ~180  6 session tools + 3 resources
    core.py      ~230  evaluate_sage, evaluate_sage_streaming, calculate_expression,
                       simplify_expression, expand_expression, factor_expression, find_root
    calculus.py  ~260  differentiate_expression, integrate_expression, limit_expression,
                       series_expansion, solve_ode, symbolic_sum, vector_calculus_operation
    algebra.py   ~280  solve_equation, matrix_operation, matrix_multiply,
                       polynomial_ring_operation, boolean_algebra_operation
    discrete.py  ~330  number_theory_operation, combinatorics_operation, graph_operation,
                       group_operation, elliptic_curve_operation, coding_theory_operation
    stats.py     ~220  statistics_summary, distribution_operation
    plotting.py  ~250  plot_expression, plot3d_expression, plot_multi_expression,
                       geometry_operation
```

37 tools: 6 + 7 + 7 + 5 + 6 + 2 + 4. Counted against `mcp.list_tools()`, not by eye.

## The three things that can go wrong

### 1. Circular imports

Tool modules need the `mcp` object to decorate against; `server.py` needs the tool
modules to exist so registration happens. If `mcp` stays in `server.py`, that is a
cycle.

`app.py` owns `mcp` and imports nothing from the package. Tool modules import
`from .app import mcp`. `server.py` imports `from . import tools` for the
side effect. The dependency graph stays a DAG: `app` → (nothing), `tools/*` →
`app`, `runtime`, `codegen`; `server` → `tools`, `app`, `runtime`.

**Not** `mcp.mount()` / `import_server()`: FastMCP's composition prefixes tool
names, so `integrate_expression` would become `calculus_integrate_expression`.
That is a breaking change for every configured client, to solve a problem that
plain imports already solve.

### 2. The tests that reach into `server`

`monkeypatch.setattr(server, "SESSION_MANAGER", ...)` appears 37 times. Once a
tool lives in `tools/calculus.py` and reads `runtime.SESSION_MANAGER`, patching
`server.SESSION_MANAGER` silently does nothing — the test would run against the
real manager and still pass in pure-Python mode, which is the worst outcome.

Mitigation: move the state, then convert all 37 to a `sage_manager` fixture in
`conftest.py` in the same commit. Also patched: `DEFAULT_SETTINGS` (1) and
`_CULL_TASK` (2) — `_CULL_TASK` stays in `server.py` with the lifespan.

To prove the fixture actually reaches the tools, add one test that patches the
manager and asserts a *specialized* tool used it (not just `evaluate_sage`).

### 3. `test_generated_code_lint.py` parses `server.py` by path

```python
SERVER_PATH = Path(...) / "src" / "sagemath_mcp" / "server.py"
```

It AST-parses that file for the caret lint, the `save(_buf)` lint and the
documented-example coverage check. After the move, that file holds no tool code,
so all three checks would pass while inspecting nothing — the same silent-pass
failure as the integration job that never ran.

Fix in the same change: scan every module under `src/sagemath_mcp/`, and assert a
floor (`>= 30` tool functions discovered, `>= 25` generated-code templates) so the
check cannot quietly degrade to zero again.

## Sequence

Each step ends green; the branch is never left broken.

1. **Guard first.** Add `tests/test_tool_inventory.py`: snapshot all 37 tool names,
   their full JSON input schemas and their description text, plus the 3 resource
   templates, from `await mcp.list_tools()`. Commit the snapshot as a JSON fixture.
   This is the contract the refactor must not change — write it *before* touching
   any source, and confirm it passes on unmodified `main`.
2. **Extract `app.py` and `runtime.py`.** Move `mcp`, `MCP_INSTRUCTIONS`,
   `SETTINGS`, `SESSION_MANAGER`. Convert the 37 patch sites to the fixture.
   Verify: full unit suite, and the inventory snapshot unchanged.
3. **Extract `codegen.py`.** `_sage_prelude`, `_encode_literal`,
   `_declare_free_symbols`, `_validated_expression`, `_screen_unparseable_fragment`,
   `_exact_int`, `_reject_if_inexact`, `_check_matrix`, `_normalize_source`,
   `_truncate_stdout`, the distribution mean/variance helpers and the four module
   regexes. Update the two `from sagemath_mcp.server import _validated_expression`
   imports in `test_security_bypass.py`.
4. **Move the tools**, one module per commit, in the order session → core →
   calculus → algebra → discrete → stats → plotting. Descriptions move verbatim:
   they were tuned so Codex picks the specialized tools over `evaluate_sage`, and
   the snapshot from step 1 will catch any drift.
5. **Retarget the lint** to scan the package with a discovery floor.
6. **Docs**: `README.md` architecture section, `ROADMAP.md`, `TODO.md`,
   `REVIEW_ACTIONS.md` item 4, and `CLAUDE.md` if it names `server.py`.

## Verification

- `mcp.list_tools()` snapshot identical — names, schemas, descriptions.
- 347 unit tests pass, count unchanged except the new inventory test.
- 423 integration tests pass against real SageMath 10.9.
- `sagemath-mcp --help` and `python -m sagemath_mcp.server --help` both work.
- The three CLI integration configs still launch (`tests/cli_integration/`).
- `git diff --stat` reads as moves: near-equal insertions and deletions, no net
  logic change in the tool bodies.
- Coverage stays at ~88% overall; a drop means a body changed, not just its home.

## Definition of done

`server.py` under 300 lines, no module over 350, tool inventory byte-identical,
both entry points working, all suites green, docs updated, item 4 closed in
`REVIEW_ACTIONS.md` and `TODO.md`.
