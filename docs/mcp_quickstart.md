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
- **Statistics (Python):** `statistics_summary` — uses Python's `statistics` module, no Sage required.
- **Probability (Sage):** `distribution_operation` (normal, exponential, Poisson, chi-squared, Student-t, etc.).
- **Visualization (Sage):** `plot_expression`, `plot3d_expression`, `plot_multi_expression` (base64 PNG).
- **Numeric Methods (Sage):** `find_root` (root-finding in an interval).
- **Vector Calculus (Sage):** `vector_calculus_operation` (gradient, divergence, curl, Laplacian).
- **Session Management:** `reset_sage_session`, `cancel_sage_session`.
- **Infrastructure:** `/health` endpoint (HTTP only).
- **Resources:** `resource://sagemath/session/all`, `resource://sagemath/monitoring/metrics`.
- **Deployment:** Local development via `uv run sagemath-mcp`, Docker Compose on `http://127.0.0.1:8314/mcp`,
  or the Helm chart (`charts/sagemath-mcp`) which exposes the MCP endpoint through a Kubernetes Service.

## Example Prompts

### Evaluate a Multi-Step Workflow

```json
{
  "tool": "evaluate_sage",
  "arguments": {
    "code": "var('x'); f = sin(x)**3; diff(f, x)"
  }
}
```

```
{
  "tool": "evaluate_sage",
  "arguments": {
    "code": "integral(diff(sin(x)**3, x), x)"
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
