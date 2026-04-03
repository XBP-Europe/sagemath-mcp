# Project Evaluation — SageMath MCP as Universal Math Server

**Date:** 2026-04-02

## Overall Verdict

The project has solid infrastructure (sessions, security, monitoring, CI/CD, Docker, Helm) but the actual math capabilities are thin for something claiming to be a universal math server. The heavy lifting is delegated to `evaluate_sage` (run arbitrary code), while the helper tools are limited wrappers.

## What Works Well

- **Stateful sessions** — persistent Sage worker per client, variables survive across calls
- **Security** — AST-based validation blocking dangerous operations, configurable policy
- **Infrastructure** — Docker, Helm, CI/CD, monitoring, progress heartbeats all solid
- **`evaluate_sage`** — the escape hatch that makes anything possible (if the LLM knows Sage syntax)

## Key Problems

### 1. Helper tools are too limited for "universal math"

The 6 math helpers are shallow wrappers with significant gaps:

| Tool | Limitation |
|------|-----------|
| `solve_equation` | Single variable only, no systems of equations, no inequalities |
| `differentiate_expression` | First-order only, no higher derivatives, no partial derivatives |
| `integrate_expression` | Indefinite only, no definite integrals (no bounds parameter) |
| `calculate_expression` | Only pre-declares `x, y, z, t` — other variables fail |
| `statistics_summary` | Uses Python `statistics` module, not Sage — purely numeric, no symbolic stats |
| `matrix_multiply` | Only multiplication — no determinant, eigenvalues, inverse, decomposition |

An LLM that doesn't know SageMath syntax is stuck with these limited helpers. One that does know Sage can bypass them entirely via `evaluate_sage`.

### 2. Missing math domains entirely

For a "universal" math server, there are no tools for:

- **Number theory** (primes, factoring, modular arithmetic)
- **Combinatorics** (permutations, combinations, graph theory)
- **Plotting/visualization** (Sage has excellent plotting)
- **Differential equations** (ODEs, PDEs)
- **Limits and series** (Taylor series, convergence)
- **Boolean algebra / logic**
- **Geometry** (distances, areas, transformations)
- **Probability distributions**

### 3. Bugs and code issues

- **`result_type` includes `"void"`** in the Pydantic model but the worker never produces it — type contract is broken
- **Race condition in session culling** — a session can be culled between checking staleness and popping it, even if it was just accessed
- **`_evaluate_structured` has no timeout** — if a helper tool hangs, there's no safety net (unlike `evaluate_sage` which has one)
- **Startup code failures are silent** — if Sage isn't installed or `from sage.all import *` fails, the worker appears alive but every evaluation will fail with confusing errors
- **Empty code input** — worker silently ignores it, sends no response, client hangs

### 4. Testing gaps

- **LaTeX output is never tested** despite being a promoted feature
- **No test validates real Sage output** in the default test suite (all unit tests use pure-Python stubs)
- **Statistics helper** computes 8 values but tests only check 2
- **`FakeContext`** is duplicated across test files instead of being a shared fixture

## Recommendations

### Short-term (make it actually useful)

1. Add bounds parameters to `integrate_expression` for definite integrals
2. Add `order` parameter to `differentiate_expression` for higher-order/partial derivatives
3. Add `solve_system` tool for systems of equations
4. Add `simplify_expression` and `expand_expression` tools
5. Add `limit_expression` and `series_expansion` tools
6. Fix the `_evaluate_structured` missing timeout
7. Fix the `"void"` result_type mismatch

### Medium-term (fill domain gaps)

8. Add `plot_expression` returning image data (Sage is great at this)
9. Add matrix tools beyond just multiplication (determinant, eigenvalues, inverse, rank)
10. Add `factor_integer` / `is_prime` / `next_prime` for number theory
11. Add `solve_ode` for differential equations
12. Enrich tool descriptions with examples so LLMs know how to use them effectively

### Design consideration

Rather than adding dozens of narrow tools, consider improving `evaluate_sage`'s tool description with rich examples and common patterns. LLMs are good at generating Sage code if guided — the current description is sparse. The helper tools then become convenience shortcuts, not the primary interface.
