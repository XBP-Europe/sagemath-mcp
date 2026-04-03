# Roadmap

This document tracks planned improvements to the SageMath MCP server, organized by priority and effort. The goal is to strengthen the server's position as a universal mathematics MCP server that enables LLMs to perform any symbolic or discrete mathematical operation.

**Current state (v0.2.0):** 18 dedicated MCP tools covering calculus, algebra, linear algebra, ODEs, number theory, statistics, and 2D plotting. The open-ended `evaluate_sage` tool provides access to all of SageMath via unrestricted `sage.*` imports. 150 unit tests at 99% branch coverage, plus 43 CLI integration tests.

---

## Phase 1 — High-Value Helper Tools

These tools address frequent use cases where LLMs struggle with raw Sage syntax. Structured input/output significantly improves reliability.

### `symbolic_sum` / `symbolic_product`

Compute symbolic summation and products. LLMs frequently need `sum(1/n^2, n, 1, oo)` but often get the Sage syntax wrong.

| Parameter | Type | Description |
|-----------|------|-------------|
| `expression` | string | The expression to sum/multiply (e.g. `"1/n^2"`) |
| `variable` | string | The index variable (e.g. `"n"`) |
| `lower` | string | Lower bound (e.g. `"1"`) |
| `upper` | string | Upper bound (e.g. `"oo"` for infinity) |

Returns: `{"result": "pi^2/6"}` or `{"result": "n!"}`.

**Priority:** High | **Effort:** Low (wrapper around Sage's `sum()` and `product()`)

### `combinatorics_operation`

Counting and enumeration problems are common in discrete math, CS theory, and interview prep. LLMs benefit from structured operation selection rather than constructing Sage iterator objects.

| Parameter | Type | Description |
|-----------|------|-------------|
| `operation` | string | One of: `"binomial"`, `"permutations"`, `"combinations"`, `"partitions"`, `"factorial"`, `"catalan"`, `"fibonacci"`, `"bell"` |
| `n` | int | Primary argument |
| `k` | int or null | Secondary argument (for binomial, combinations, permutations) |

Returns: `{"operation": "binomial", "result": 252}` or `{"operation": "partitions", "result": 7, "list": [[5], [4,1], [3,2], [3,1,1], [2,2,1], [2,1,1,1], [1,1,1,1,1]]}`.

**Priority:** High | **Effort:** Low

### `plot3d_expression`

Natural extension of the existing `plot_expression` tool to 3D surface plots. Useful for visualizing functions of two variables.

| Parameter | Type | Description |
|-----------|------|-------------|
| `expression` | string | The expression to plot (e.g. `"sin(x)*cos(y)"`) |
| `x_variable` | string | First variable (default `"x"`) |
| `y_variable` | string | Second variable (default `"y"`) |
| `x_range_min` / `x_range_max` | float | X-axis bounds (default -5 to 5) |
| `y_range_min` / `y_range_max` | float | Y-axis bounds (default -5 to 5) |

Returns: `{"image_base64": "...", "format": "png"}`.

**Priority:** High | **Effort:** Low (similar pattern to 2D tool, calls Sage's `plot3d()`)

---

## Phase 2 — Medium-Value Helper Tools

These tools address less frequent but still meaningful use cases where dedicated tools improve the LLM experience.

### `distribution_operation`

Probability distributions are common in statistics and data science workflows. A structured interface reduces boilerplate for common queries.

| Parameter | Type | Description |
|-----------|------|-------------|
| `distribution` | string | One of: `"normal"`, `"exponential"`, `"poisson"`, `"binomial_dist"`, `"chi_squared"`, `"student_t"`, `"uniform"`, `"beta"`, `"gamma"` |
| `parameters` | list[float] | Distribution parameters (e.g. `[0, 1]` for standard normal) |
| `operation` | string | One of: `"pdf"`, `"cdf"`, `"quantile"`, `"mean"`, `"variance"`, `"sample"` |
| `x` | float or null | Point for PDF/CDF/quantile evaluation |
| `n` | int or null | Number of samples (for `"sample"` operation) |

Returns: `{"distribution": "normal", "operation": "cdf", "result": 0.9772}`.

**Priority:** Medium | **Effort:** Medium

### `find_root`

Numeric root-finding for cases where `solve_equation` has no symbolic solution. Complements the symbolic solver.

| Parameter | Type | Description |
|-----------|------|-------------|
| `expression` | string | The expression to find roots of (e.g. `"x - cos(x)"`) |
| `variable` | string | The variable (default `"x"`) |
| `lower_bound` | float | Left bound of search interval |
| `upper_bound` | float | Right bound of search interval |

Returns: `{"root": 0.7390851332151607}`.

**Priority:** Medium | **Effort:** Low (wrapper around Sage's `find_root()`)

### Multi-expression plotting

Extend the existing `plot_expression` tool to overlay multiple functions in a single plot.

| Parameter | Type | Description |
|-----------|------|-------------|
| `expressions` | list[string] | List of expressions to plot (e.g. `["sin(x)", "cos(x)", "x^2/10"]`) |
| `variable` | string | The plot variable (default `"x"`) |
| `range_min` / `range_max` | float | Axis bounds |
| `legend` | bool | Whether to show a legend (default `true`) |

Returns: `{"image_base64": "...", "format": "png"}`.

**Priority:** Medium | **Effort:** Low (extension of existing tool)

### `vector_calculus_operation`

Vector calculus operations (gradient, divergence, curl, Laplacian) are standard in physics and engineering but tricky to express in Sage syntax.

| Parameter | Type | Description |
|-----------|------|-------------|
| `operation` | string | One of: `"gradient"`, `"divergence"`, `"curl"`, `"laplacian"` |
| `expression` | string or list[string] | Scalar field (for gradient/laplacian) or vector field components (for divergence/curl) |
| `variables` | list[string] | Variable names (e.g. `["x", "y", "z"]`) |

Returns: `{"operation": "gradient", "result": ["2*x", "2*y", "2*z"]}`.

**Priority:** Medium | **Effort:** Medium

---

## Phase 3 — Enrichment (As Needed)

These improvements do not require new tools but enhance the existing server's usability.

### Enrich `evaluate_sage` tool description

Add more domain-specific examples to the tool description that LLMs see. Currently documents 8 domains. Candidates for additional examples:

| Domain | Example |
|--------|---------|
| Symbolic summation | `sum(1/n^2, n, 1, oo)` |
| Vector calculus | `f = x^2 + y^2 + z^2; diff(f, x), diff(f, y), diff(f, z)` |
| Fourier transforms | `fourier_transform(exp(-x^2), x, s)` |
| Laplace transforms | `laplace(sin(t), t, s)` |
| Numeric root finding | `find_root(x - cos(x), 0, 1)` |
| Recurrence relations | `var('n'); f = function('f'); desolve_rsolve(f(n+2) - f(n+1) - f(n), f, [0, 1])` |
| Modular arithmetic | `Mod(17, 5)`, `power_mod(3, 100, 97)` |
| Lattice/poset operations | `Posets.BooleanLattice(3)` |

**Priority:** Medium | **Effort:** Very low (just updating a string)

### HTTP health check endpoint

Replace TCP socket-based Helm probes with an HTTP `/health` endpoint that returns 200 when the server is ready and the Sage worker is responsive.

**Priority:** Medium | **Effort:** Low

### Streaming partial output

For long-running computations, emit partial results (e.g., intermediate steps of a series expansion or iterative solver) as they become available, rather than waiting for the full result.

**Priority:** Low | **Effort:** High (requires changes to the worker protocol)

### Disk-backed session persistence

Optionally serialize session state to disk so sessions survive server restarts. Useful for long-running workloads or scheduled computations.

**Priority:** Low | **Effort:** High (requires serialization of Sage namespaces)

---

## Phase 4 — Niche Domains (Only if Requested)

These domains are fully accessible via `evaluate_sage` and documented in its tool description. Dedicated tools are unlikely to provide significant value over raw Sage code because the domains require specialized knowledge to use effectively.

| Domain | Current Access | Dedicated Tool Value |
|--------|---------------|---------------------|
| Graph theory | `graphs.PetersenGraph(); G.chromatic_number()` | Low — problems are too varied for a single tool interface |
| Group theory | `SymmetricGroup(5).order()` | Low — requires domain expertise |
| Elliptic curves | `EllipticCurve([0,0,1,-1,0]).rank()` | Low — highly specialized |
| Coding theory | `codes.HammingCode(GF(2), 3).minimum_distance()` | Low — niche |
| Tensor operations | Sage tensor module with index notation | Low — very specialized |
| Boolean algebra | `BooleanPolynomialRing` | Low — Sage is not strong here |
| Category theory | Limited Sage support | Very low — out of Sage's scope |
| Unit conversion | External `units` package | Low — domain-specific |
| Curve fitting | Limited in Sage (scipy is better) | Low — wrong tool for the job |

---

## Completed (v0.2.0)

All items from the initial evaluation and TODO have been implemented:

- [x] 18 MCP math tools (calculus, algebra, linear algebra, ODEs, number theory, statistics, plotting)
- [x] CLI integration test suite (43 cases, Claude + Gemini)
- [x] 150 unit tests at 99% branch coverage
- [x] FastMCP 3.x upgrade with full API migration
- [x] CI modernization (6 parallel jobs, matrix testing, uv caching, pip-audit, coverage)
- [x] Docker image pinned to SageMath 10.5
- [x] Helm chart health probes (liveness, readiness, startup)
- [x] Python 3.12+ minimum
- [x] All GitHub Actions on Node.js 24
- [x] Worker startup error propagation
- [x] MCP resource serialization fix
- [x] Security policy: base64/io imports for plot support
- [x] Comprehensive documentation across all markdown files
- [x] Project metadata, classifiers, URLs
- [x] MIT LICENSE file (was Apache 2.0)
- [x] Version synchronization across pyproject.toml, __init__.py, Helm chart
