# MCP Quickstart & Prompt Cookbook

This guide offers ready-to-use snippets for LLM-driven clients.

## Connection Summary

All tools use **SageMath** as the computation backend unless noted.

- **Core (Sage):** `evaluate_sage`, `evaluate_sage_streaming` (line-by-line progress).
- **Calculus (Sage):** `differentiate_expression`, `integrate_expression`, `limit_expression`, `series_expansion`, `symbolic_sum`.
- **Algebra (Sage):** `solve_equation`, `simplify_expression`, `expand_expression`, `factor_expression`, `calculate_expression`.
- **Linear Algebra (Sage):** `matrix_multiply`, `matrix_operation` (determinant, inverse, eigenvalues, rank, RREF, transpose).
- **Differential Equations (Sage):** `solve_ode`.
- **Number Theory (Sage):** `number_theory_operation` (is_prime, factor_integer, next_prime, gcd, lcm).
- **Combinatorics (Sage):** `combinatorics_operation` (binomial, permutations, combinations, partitions, factorial, Catalan, Fibonacci, Bell).
- **Graph Theory (Sage):** `graph_operation` (chromatic number, connectivity, planarity, diameter, shortest path).
- **Group Theory (Sage):** `group_operation` (order, abelian/cyclic test, center, exponent).
- **Elliptic Curves (Sage):** `elliptic_curve_operation` (rank, torsion, discriminant, j-invariant, conductor).
- **Coding Theory (Sage):** `coding_theory_operation` (length, dimension, minimum distance, rate).
- **Boolean Algebra (Sage):** `boolean_algebra_operation` (evaluate, variables, degree).
- **Polynomial Rings (Sage):** `polynomial_ring_operation` (Groebner bases, ideal dimension/variety).
- **Geometry (Sage):** `geometry_operation` (distance, area, volume, convex hull via Polyhedron).
- **Statistics (Sage):** `statistics_summary` — mean, median, variance, std dev, min, max.
- **Probability (Sage):** `distribution_operation` (normal, exponential, Poisson, chi-squared, Student-t, etc.).
- **Visualization (Sage):** `plot_expression`, `plot3d_expression`, `plot_multi_expression` (base64 PNG).
- **Numeric Methods (Sage):** `find_root` (root-finding in an interval).
- **Vector Calculus (Sage):** `vector_calculus_operation` (gradient, divergence, curl, Laplacian).
- **Session Management:** `start_sage_session`, `list_sage_sessions`, `stop_sage_session`,
  `reset_sage_session`, `interrupt_sage_session` (stops the computation, keeps the variables),
  `cancel_sage_session` (restarts the worker, discards them).
- **Infrastructure:** `/health` endpoint (HTTP only).
- **Resources:** `resource://sagemath/session/{scope}`, `resource://sagemath/monitoring/{scope}`,
  `resource://sagemath/docs/{scope}`.
- **Deployment:** Local development via `uv run sagemath-mcp`, Docker Compose on `http://127.0.0.1:8314/mcp`,
  or the Helm chart (`charts/sagemath-mcp`) which exposes the MCP endpoint through a Kubernetes Service.

## What the server does that a caller should know

**It runs Sage, not Python.** Code is preparsed exactly as Sage's own REPL does:
`2^3` is 8, not 1; integer literals are Sage `Integer`s; `K.<a> = NumberField(x^3 - 2)`
parses; and `x`, `y`, `z` and `t` are already defined. Any other symbol needs
`var('w')` first, and the error message says so. Use `^^` if you actually want XOR.
Code indented as a whole -- pasted out of a markdown block, say -- is accepted:
the shared margin is stripped before parsing.

**Large integers travel as decimal strings.** Above 2^53 a JSON number is no
longer exact and a JavaScript-based client will round it before the server ever
sees it, so those parameters take strings and those results come back as strings:

```json
{"tool": "combinatorics_operation", "arguments": {"operation": "bell", "n": 30}}
-> {"operation": "bell", "result": "846749014511809332450147"}
```

**Workspaces are independent.** Every stateful tool takes an optional `session`;
omit it for `default`. A long exploration and a scratch calculation do not have to
collide.

**You get an allowlist, not a blocklist.** A name works if SageMath preloads it
for mathematics, if it is a safe builtin, or if your own code defined it —
including earlier in the same session. Anything else is refused, so the question
to ask is "is this offered" rather than "is this forbidden".

The refusals worth knowing before you hit them:

- **No imports.** The names are already there; drop the line.
- **No `eval`, `exec`, `getattr`, `attrgetter`, `methodcaller`** or anything else
  that reaches a name indirectly.
- **No other CAS.** `gp`, `maxima`, `singular`, `pari` each spawn the real
  program, and those have shell escapes — `pari('system("id")')` ran one.
- **No `show()`, `view()`, `latex()`, `html()` or `animate()`.** This is the one
  that catches people, because `show(plot(...))` is how you would do it in a
  notebook. Over MCP you want **`plot_expression`** and its siblings, which
  return a base64 PNG the client can actually display; `show` would write a file
  on the server and try to open a viewer nobody is looking at.
- **No file or network access** — `save`, `dump`, `export`, `load`, `attach`,
  `oeis`, `get_remote_file`.

If you hit one, the answer is a Sage primitive or the matching specialised tool,
not a way around it: every name on that list executed code, ran a shell, wrote a
file or reached the network during testing.

## Example Prompts

### Evaluate a Multi-Step Workflow

```json
{
  "tool": "evaluate_sage",
  "arguments": {
    "code": "f = sin(x)^3; diff(f, x)"
  }
}
```

```
{
  "tool": "evaluate_sage",
  "arguments": {
    "code": "integral(diff(sin(x)^3, x), x)"
  }
}
```

### Equation Solving Helper

```json
{
  "tool": "solve_equation",
  "arguments": {
    "equation": "x^2 - 5*x + 6 = 0",
    "variable": "x"
  }
}
```

### Matrix Multiplication

```json
{
  "tool": "matrix_multiply",
  "arguments": {
    "matrix_a": [[1, 2], [3, 4]],
    "matrix_b": [[5, 6], [7, 8]]
  }
}
```

### Statistics Summary

```json
{
  "tool": "statistics_summary",
  "arguments": {
    "data": [1, 2, 3, 4, 5]
  }
}
```

### Monitoring Snapshot

```json
{
  "resource": "resource://sagemath/monitoring/metrics"
}
```

## Usage Tips

- Reuse the same MCP session for cumulative calculations; Sage state persists until `reset_sage_session`.
- Prefer Sage primitives (`var`, `matrix`, polynomial rings) over raw imports.
- Disable `capture_stdout` in `evaluate_sage` for loops unless you need console output.
- Use the helper tools where possible—they return clean JSON structures.
- Reach for `interrupt_sage_session` before `cancel_sage_session`: interrupting
  abandons the computation and keeps every variable, cancelling restarts the
  worker and loses them.
- Name a workspace (`"session": "curves"`) when a line of work should not be
  disturbed by unrelated calculations.
- Ask for a plot only when you want the image: it comes back as base64 PNG and is
  large compared with everything else here.
