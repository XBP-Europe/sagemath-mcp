# SageMath MCP Server

[![CI](https://github.com/XBP-Europe/sagemath-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/XBP-Europe/sagemath-mcp/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/XBP-Europe/sagemath-mcp.svg)](https://github.com/XBP-Europe/sagemath-mcp/releases/latest)
[![PyPI](https://img.shields.io/pypi/v/sagemath-mcp.svg)](https://pypi.org/project/sagemath-mcp/)
[![GHCR](https://img.shields.io/badge/GHCR-sagemath--mcp-blue?logo=github)](https://github.com/XBP-Europe/sagemath-mcp/pkgs/container/sagemath-mcp)
[![License](https://img.shields.io/github/license/XBP-Europe/sagemath-mcp.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/MCP-Model%20Context%20Protocol-purple)](https://modelcontextprotocol.io/)
[![FastMCP](https://img.shields.io/badge/FastMCP-3.2-green.svg)](https://gofastmcp.com/)
[![SageMath](https://img.shields.io/badge/SageMath-10.5-orange)](https://www.sagemath.org/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://docs.astral.sh/ruff/)
[![Typed](https://img.shields.io/badge/type--checked-py.typed-blue)](https://peps.python.org/pep-0561/)

A universal mathematics [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) server that gives LLM clients full access to [SageMath](https://www.sagemath.org/) --- one of the most comprehensive open-source mathematics systems available. Built on [FastMCP 3.x](https://gofastmcp.com/), the server maintains a dedicated SageMath process for each MCP session so variables, functions, and assumptions persist across tool calls.

Whether the task is symbolic calculus, number theory, linear algebra, differential equations, plotting, combinatorics, graph theory, group theory, or basic arithmetic, the server provides **33 MCP tools** --- 30 backed by the full SageMath engine, plus `statistics_summary` (pure Python `statistics` module), `evaluate_sage_streaming` (streaming wrapper), and an HTTP `/health` endpoint.

---

## Table of Contents

- [Features at a Glance](#features-at-a-glance)
- [Architecture Overview](#architecture-overview)
- [Quick Start](#quick-start)
- [Detailed Tool Reference](#detailed-tool-reference)
  - [evaluate_sage --- Open-Ended Execution](#evaluate_sage----open-ended-sagemath-execution)
  - [Calculus Tools](#calculus-tools)
  - [Algebra & Simplification Tools](#algebra--simplification-tools)
  - [Linear Algebra Tools](#linear-algebra-tools)
  - [Differential Equations](#differential-equations)
  - [Number Theory](#number-theory)
  - [Statistics](#statistics)
  - [Visualization](#visualization)
  - [Session Management & Observability](#session-management--observability)
- [Security Sandbox](#security-sandbox)
- [LLM Client Configuration](#llm-client-configuration)
- [Deployment](#deployment)
- [Configuration Reference](#configuration-reference)
- [CLI Reference](#cli-reference)
- [Development](#development)
- [CLI Integration Testing](#cli-integration-testing)
- [Project Layout](#project-layout)
- [Technology Stack](#technology-stack)
- [Changelog](#changelog)
- [Roadmap](#roadmap)
- [Contributing](#contributing)

---

## Features at a Glance

| Category | Tools | Backend | Capabilities |
|----------|-------|---------|-------------|
| **Core execution** | `evaluate_sage`, `evaluate_sage_streaming` | Sage | Run any SageMath code with persistent state, LaTeX output, stdout capture, progress heartbeats, per-call timeouts, and line-by-line streaming |
| **Calculus** | `differentiate_expression`, `integrate_expression`, `limit_expression`, `series_expansion` | Sage | Derivatives of any order, indefinite & definite integrals, one-sided limits, Taylor/Laurent series |
| **Algebra** | `solve_equation`, `simplify_expression`, `expand_expression`, `factor_expression`, `calculate_expression` | Sage | Single equations & systems, symbolic simplification, expansion, factoring, numeric evaluation |
| **Symbolic sums** | `symbolic_sum` | Sage | Symbolic summation and products (finite and infinite series) |
| **Linear algebra** | `matrix_multiply`, `matrix_operation` | Sage | Matrix products, determinants, inverses, eigenvalues, rank, RREF, transpose |
| **Differential equations** | `solve_ode` | Sage | First- and higher-order ODEs via Sage's `desolve()` |
| **Number theory** | `number_theory_operation` | Sage | Primality testing, integer factorization, next prime, GCD, LCM |
| **Combinatorics** | `combinatorics_operation` | Sage | Binomial, permutations, combinations, partitions, factorial, Catalan, Fibonacci, Bell numbers |
| **Graph theory** | `graph_operation` | Sage | Named graphs and adjacency dicts; chromatic number, connectivity, planarity, diameter, shortest path |
| **Group theory** | `group_operation` | Sage | Symmetric, dihedral, cyclic, alternating groups; order, abelian/cyclic test, center, exponent |
| **Elliptic curves** | `elliptic_curve_operation` | Sage | Rank, torsion, discriminant, j-invariant, conductor, generators |
| **Coding theory** | `coding_theory_operation` | Sage | Hamming, Reed-Solomon codes; length, dimension, minimum distance, generator matrix, rate |
| **Polynomial rings** | `polynomial_ring_operation` | Sage | Groebner bases, ideal dimension/variety, reduction, Groebner test |
| **Boolean algebra** | `boolean_algebra_operation` | Sage | Boolean polynomial ring; evaluate, variables, degree, zero/one test |
| **Geometry** | `geometry_operation` | Sage | Distance, polygon area, polytope volume, convex hull, compactness via `Polyhedron` |
| **Statistics** | `statistics_summary` | Python | Mean, median, population & sample variance/std dev, min, max (uses Python `statistics` module, no Sage required) |
| **Probability** | `distribution_operation` | Sage | Normal, exponential, Poisson, chi-squared, Student-t, uniform, beta, gamma; PDF, CDF, quantile, sampling |
| **Visualization** | `plot_expression`, `plot3d_expression`, `plot_multi_expression` | Sage | 2D plots, 3D surface plots, multi-function overlays as base64-encoded PNG |
| **Numeric methods** | `find_root` | Sage | Numeric root-finding in an interval via Sage's `find_root()` |
| **Vector calculus** | `vector_calculus_operation` | Sage | Gradient, divergence, curl, Laplacian on scalar/vector fields |
| **Session control** | `reset_sage_session`, `cancel_sage_session` | Worker | Clear state or abort long-running computations |
| **Infrastructure** | `/health` endpoint, 3 MCP resources | Server | Health check, session snapshots, aggregated metrics, documentation links |

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────┐
│  MCP Client (Claude Desktop, Gemini CLI, Codex CLI, etc.)       │
└──────────────────────┬───────────────────────────────────────────┘
                       │  MCP protocol (stdio or HTTP)
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│  server.py --- FastMCP 3.x Application                          │
│                                                                  │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────────┐  │
│  │ 18 MCP Tools│  │ 3 Resources  │  │ Middleware              │  │
│  │ (evaluate,  │  │ (session,    │  │ - Request logging       │  │
│  │  solve,     │  │  monitoring, │  │ - Response caching      │  │
│  │  diff, ...)│  │  docs)       │  │ - Progress heartbeats   │  │
│  └──────┬──────┘  └──────────────┘  └────────────────────────┘  │
│         │                                                        │
│  ┌──────▼──────────────────────────────────────────────────────┐ │
│  │ session.py --- SageSessionManager                           │ │
│  │  Per-client session map with asyncio locks, idle culling    │ │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │ │
│  │  │ Session A   │  │ Session B   │  │ Session C   │  ...   │ │
│  │  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘        │ │
│  └─────────┼───────────────┼───────────────┼──────────────────┘ │
└────────────┼───────────────┼───────────────┼────────────────────┘
             │               │               │
             ▼               ▼               ▼
     ┌───────────────────────────────────────────────┐
     │  _sage_worker.py --- Subprocess Workers       │
     │  JSON stdin/stdout protocol                    │
     │                                                │
     │  ┌────────────┐   ┌──────────────────────┐    │
     │  │ security.py│──▶│ AST validation       │    │
     │  │            │   │ before every exec()   │    │
     │  └────────────┘   └──────────────────────┘    │
     │                                                │
     │  Persistent namespace: vars, functions,        │
     │  classes survive across calls                   │
     └────────────────────────────────────────────────┘
```

**Request flow:** MCP client → `server.py` tool → `SageSessionManager.get_or_create()` → `SageSession.evaluate()` → JSON request to `_sage_worker.py` subprocess → AST validation → `exec()` in persistent namespace → JSON response back.

**Key design decisions:**

- **Process isolation:** Each session runs SageMath in a separate subprocess. A crash or timeout in one session cannot affect others.
- **Stateful sessions:** Variables, functions, and assumptions persist across tool calls within the same MCP session, enabling multi-step mathematical workflows.
- **Security by default:** Every code snippet passes through an AST-based validator before execution, blocking dangerous operations regardless of the tool used.
- **Progress heartbeats:** Long-running computations emit periodic progress events (~1.5s) so clients can display activity indicators and detect stalls.

---

## Quick Start

### Install from PyPI

```bash
pip install sagemath-mcp

# Run the server over stdio (default)
sagemath-mcp

# Or expose an HTTP endpoint
sagemath-mcp --transport streamable-http --host 127.0.0.1 --port 8314
```

If the command is not on your `PATH`, run `python -m sagemath_mcp.server --help`.

### Develop from source

```bash
git clone https://github.com/XBP-Europe/sagemath-mcp.git
cd sagemath-mcp

# Install dependencies (use uv or pip)
uv pip install -e .[dev]

# Run the server over stdio (default)
uv run sagemath-mcp

# Run with streaming-friendly HTTP transport
uv run sagemath-mcp --transport streamable-http --host 127.0.0.1 --port 8314
```

### Optional: start a Sage container automatically

If you'd like a ready-to-use Sage runtime without installing it locally, run:

```bash
make sage-container  # or ./scripts/setup_sage_container.sh
```

On Windows PowerShell:

```powershell
pwsh -File scripts/setup_sage_container.ps1
```

### Docker Image

Build a ready-to-run container with the MCP server baked in:

```bash
docker build -t sagemath-mcp:latest .
docker run -p 8314:8314 sagemath-mcp:latest --transport streamable-http
```

Released images are published to `ghcr.io/xbp-europe/sagemath-mcp` and signed with Cosign.
Verify a downloaded artifact with:

```bash
cosign verify ghcr.io/xbp-europe/sagemath-mcp:latest \
  --certificate-identity "https://github.com/XBP-Europe/sagemath-mcp/.github/workflows/release.yml@refs/tags/vX.Y.Z" \
  --certificate-oidc-issuer "https://token.actions.githubusercontent.com"
```

### Docker Compose

```bash
docker compose up --build
```

The compose service exposes port `8314` on both host and container and mounts the repository at `/workspace`. Containers run as the non-root `sage` user (UID/GID 1000) to match the base image. Tweak runtime settings by editing the environment block (for example, increase `SAGEMATH_MCP_EVAL_TIMEOUT` or adjust `SAGEMATH_MCP_MAX_STDOUT`) before launch.

---

## Detailed Tool Reference

### `evaluate_sage` --- Open-Ended SageMath Execution

The primary tool. Executes arbitrary SageMath code inside a persistent worker process. Variables, functions, classes, and assumptions defined in one call survive into subsequent calls within the same MCP session.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `code` | `string` | *required* | SageMath code to execute. Multi-line strings are supported. |
| `want_latex` | `bool` | `false` | When `true`, the server generates a LaTeX representation of the final expression result (if one exists) via Sage's `latex()` function. Returned in the `latex` field. |
| `capture_stdout` | `bool` | `true` | When `true`, any output from `print()` statements is captured and returned in the `stdout` field. Set to `false` for faster execution when stdout is not needed. |
| `timeout` | `float` | `null` | Override the per-evaluation timeout in seconds. If omitted, the global default (`SAGEMATH_MCP_EVAL_TIMEOUT`, 30 s) applies. Must be > 0. |

**Returns** an `EvaluateResult` object:

| Field | Type | Description |
|-------|------|-------------|
| `result_type` | `"expression"` or `"statement"` | `"expression"` when the code ends with an expression whose value is captured; `"statement"` when it ends with an assignment or side effect. |
| `result` | `string` or `null` | The `repr()` of the final expression value, or `null` for statement-type code. |
| `latex` | `string` or `null` | LaTeX representation of the result (only when `want_latex=true` and the result is non-null). |
| `stdout` | `string` | Captured stdout output (empty string if nothing was printed or `capture_stdout=false`). Truncated to `SAGEMATH_MCP_MAX_STDOUT` characters. |
| `elapsed_ms` | `float` | Wall-clock execution time in milliseconds. |

**Behavior details:**

- While code is running, the server emits **progress heartbeats** roughly every 1.5 seconds so clients can display activity indicators.
- If the evaluation exceeds the timeout, the worker process is restarted and a `TimeoutError` is raised. All session state from prior calls is lost.
- If the startup code (`from sage.all import *` by default) failed when the worker launched, every subsequent `evaluate_sage` call returns a clear `StartupError` instead of a confusing NameError.
- The AST security validator runs on every code snippet before execution (see [Security Sandbox](#security-sandbox)).

**Domain-specific examples** (these are included in the tool description LLMs see):

| Domain | Example Sage code |
|--------|------------------|
| Combinatorics | `binomial(10, 3)`, `Permutations(4).cardinality()`, `Combinations([1,2,3,4], 2).list()` |
| Graph theory | `G = graphs.PetersenGraph(); G.chromatic_number()` |
| Number theory | `prime_range(100)`, `euler_phi(60)`, `continued_fraction(pi, nterms=10)` |
| Geometry | `polytopes.cube().volume()`, `EllipticCurve([0,0,1,-1,0]).rank()` |
| Probability | `RealDistribution('gaussian', 1).cum_distribution_function(1.96)` |
| Group theory | `SymmetricGroup(5).order()`, `AlternatingGroup(4).is_abelian()` |
| Polynomial rings | `R.<a,b> = PolynomialRing(QQ); (a+b)^3` |
| Coding theory | `codes.HammingCode(GF(2), 3).minimum_distance()` |

**Stateful multi-step workflow:**

```
> evaluate_sage(code="var('a'); f = (a + 1)^5")
  result_type: "statement", result: null

> evaluate_sage(code="expand(f)")
  result_type: "expression", result: "a^5 + 5*a^4 + 10*a^3 + 10*a^2 + 5*a + 1"

> evaluate_sage(code="diff(f, a, 2)")
  result_type: "expression", result: "20*(a + 1)^3"
```

---

### Calculus Tools

#### `differentiate_expression`

Compute the symbolic derivative of an expression. Calls Sage's `diff(expr, var, order)` internally.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `expression` | `string` | *required* | The expression to differentiate (e.g. `"sin(x)*e^x"`, `"x^3 + 2*x"`). |
| `variable` | `string` | `"x"` | The variable to differentiate with respect to. |
| `order` | `int` (>= 1) | `1` | Differentiation order. `1` = first derivative, `2` = second derivative, etc. |

**Returns:** `{"derivative": "...", "order": N}`

```
> differentiate_expression(expression="x^5", variable="x", order=3)
  {"derivative": "60*x^2", "order": 3}

> differentiate_expression(expression="sin(x)*cos(x)")
  {"derivative": "cos(x)^2 - sin(x)^2", "order": 1}
```

#### `integrate_expression`

Compute indefinite or definite integrals. Calls Sage's `integrate()` function.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `expression` | `string` | *required* | The expression to integrate. |
| `variable` | `string` | `"x"` | The integration variable. |
| `lower_bound` | `string` or `null` | `null` | Lower bound for definite integrals. Accepts symbolic values like `"0"`, `"-oo"` (negative infinity), or expressions like `"-pi"`. |
| `upper_bound` | `string` or `null` | `null` | Upper bound for definite integrals. Accepts `"1"`, `"oo"` (infinity), `"pi/2"`, etc. |

Both `lower_bound` and `upper_bound` must be provided together for a definite integral, or both omitted for an indefinite integral. Providing only one raises an error.

**Returns:** `{"integral": "...", "definite": true/false}`

```
> integrate_expression(expression="x^2")
  {"integral": "1/3*x^3", "definite": false}

> integrate_expression(expression="x^2", lower_bound="0", upper_bound="1")
  {"integral": "1/3", "definite": true}

> integrate_expression(expression="e^(-x^2)", lower_bound="-oo", upper_bound="oo")
  {"integral": "sqrt(pi)", "definite": true}
```

#### `limit_expression`

Compute the limit of an expression as a variable approaches a point. Calls Sage's `limit()` function.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `expression` | `string` | *required* | The expression to take the limit of. |
| `variable` | `string` | `"x"` | The variable approaching the point. |
| `point` | `string` | `"0"` | The point to approach. Use `"oo"` for positive infinity, `"-oo"` for negative infinity, or any symbolic expression. |
| `direction` | `string` or `null` | `null` | One-sided limit direction: `"plus"` (approach from the right, x -> a+), `"minus"` (approach from the left, x -> a-), or `null` for both sides. |

**Returns:** `{"limit": "..."}`

```
> limit_expression(expression="sin(x)/x", point="0")
  {"limit": "1"}

> limit_expression(expression="1/x", point="0", direction="plus")
  {"limit": "+Infinity"}

> limit_expression(expression="(1 + 1/n)^n", variable="n", point="oo")
  {"limit": "e"}
```

#### `series_expansion`

Compute a Taylor or Laurent series expansion around a point. Calls Sage's `.series()` method.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `expression` | `string` | *required* | The expression to expand. |
| `variable` | `string` | `"x"` | The expansion variable. |
| `point` | `string` | `"0"` | Center of the expansion (Maclaurin series when `"0"`). |
| `order` | `int` (>= 1) | `6` | Number of terms in the expansion. |

**Returns:** `{"series": "...", "point": "...", "order": N}`

```
> series_expansion(expression="e^x", order=5)
  {"series": "1 + x + 1/2*x^2 + 1/6*x^3 + 1/24*x^4 + O(x^5)", "point": "0", "order": 5}

> series_expansion(expression="1/(1-x)", point="0", order=4)
  {"series": "1 + x + x^2 + x^3 + O(x^4)", "point": "0", "order": 4}
```

---

### Algebra & Simplification Tools

#### `solve_equation`

Solve a single equation or a system of simultaneous equations. Calls Sage's `solve()` function. Equations are parsed by splitting on `=`: the string `"x^2 - 1 = 0"` becomes the Sage equation `x^2 - 1 == 0`.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `equation` | `string` or `list[string]` | *required* | A single equation string (e.g. `"x^2 - 1 = 0"`) or a list of equations for systems (e.g. `["x + y = 3", "x - y = 1"]`). If no `=` is present, the expression is solved as `expr = 0`. |
| `variable` | `string` or `list[string]` | `"x"` | Variable(s) to solve for. Use a list for systems (e.g. `["x", "y"]`). |

**Returns:** `{"solutions": [...]}`

```
> solve_equation(equation="x^2 - 5*x + 6 = 0")
  {"solutions": ["x == 2", "x == 3"]}

> solve_equation(equation=["x + y = 10", "x - y = 2"], variable=["x", "y"])
  {"solutions": [[x == 6, y == 4]]}

> solve_equation(equation="sin(x) = 1/2", variable="x")
  {"solutions": ["x == 1/6*pi"]}
```

#### `simplify_expression`

Apply Sage's `simplify()` function to reduce a symbolic expression to a simpler form.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `expression` | `string` | *required* | The expression to simplify. |

**Returns:** `{"simplified": "..."}`

```
> simplify_expression(expression="(x^2 - 1)/(x - 1)")
  {"simplified": "x + 1"}

> simplify_expression(expression="sin(x)^2 + cos(x)^2")
  {"simplified": "1"}
```

#### `expand_expression`

Expand products, powers, and trigonometric/logarithmic identities using Sage's `expand()`.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `expression` | `string` | *required* | The expression to expand. |

**Returns:** `{"expanded": "..."}`

```
> expand_expression(expression="(x + 1)^3")
  {"expanded": "x^3 + 3*x^2 + 3*x + 1"}

> expand_expression(expression="(a + b)*(a - b)")
  {"expanded": "a^2 - b^2"}
```

#### `factor_expression`

Factor a symbolic expression or integer using Sage's `factor()`.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `expression` | `string` | *required* | The expression to factor. Can be a polynomial (e.g. `"x^2 - 1"`) or an integer (e.g. `"60"`). |

**Returns:** `{"factored": "..."}`

```
> factor_expression(expression="x^3 - 1")
  {"factored": "(x - 1)*(x^2 + x + 1)"}

> factor_expression(expression="60")
  {"factored": "2^2 * 3 * 5"}
```

#### `calculate_expression`

Evaluate a symbolic expression and return both its string representation and numeric value (when possible). Uses Sage's `sage_eval()` internally with pre-declared variables `x, y, z, t`.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `expression` | `string` | *required* | The expression to evaluate. |

**Returns:** `{"string": "...", "numeric": float}` --- the `numeric` field is omitted when the expression cannot be converted to a float.

```
> calculate_expression(expression="factorial(10)")
  {"string": "3628800", "numeric": 3628800.0}

> calculate_expression(expression="sqrt(2)")
  {"string": "sqrt(2)", "numeric": 1.4142135623730951}

> calculate_expression(expression="pi")
  {"string": "pi", "numeric": 3.141592653589793}
```

---

### Linear Algebra Tools

#### `matrix_multiply`

Multiply two matrices over the Symbolic Ring (`SR`). Input matrices are nested lists of numbers.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `matrix_a` | `list[list[float]]` | *required* | Left matrix (rows of numbers). |
| `matrix_b` | `list[list[float]]` | *required* | Right matrix (rows of numbers). |

**Returns:** `{"product": [[...], ...]}` --- entries are floats when real, strings otherwise.

```
> matrix_multiply(matrix_a=[[1, 2], [3, 4]], matrix_b=[[5, 6], [7, 8]])
  {"product": [[19.0, 22.0], [43.0, 50.0]]}
```

#### `matrix_operation`

Perform a single matrix operation. Supports six operations on matrices over the Symbolic Ring.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `matrix` | `list[list[float]]` | *required* | Input matrix as nested list of numbers. |
| `operation` | `string` | *required* | One of: `"determinant"`, `"inverse"`, `"eigenvalues"`, `"rank"`, `"rref"`, `"transpose"`. |

**Returns:** `{"operation": "...", "result": ...}` --- result type varies by operation:

| Operation | Result type | Description |
|-----------|------------|-------------|
| `determinant` | `float` or `string` | Scalar determinant value. |
| `inverse` | `list[list[float]]` | The inverse matrix (error if singular). |
| `eigenvalues` | `list[float]` | List of eigenvalues (with multiplicity). |
| `rank` | `int` | Matrix rank. |
| `rref` | `list[list[float]]` | Reduced row echelon form. |
| `transpose` | `list[list[float]]` | Transposed matrix. |

```
> matrix_operation(matrix=[[1, 2], [3, 4]], operation="determinant")
  {"operation": "determinant", "result": -2.0}

> matrix_operation(matrix=[[2, 1], [1, 2]], operation="eigenvalues")
  {"operation": "eigenvalues", "result": [3.0, 1.0]}

> matrix_operation(matrix=[[1, 2, 3], [0, 1, 4], [5, 6, 0]], operation="inverse")
  {"operation": "inverse", "result": [[-24.0, 18.0, 5.0], [20.0, -15.0, -4.0], [-5.0, 4.0, 1.0]]}

> matrix_operation(matrix=[[1, 2], [3, 6]], operation="rank")
  {"operation": "rank", "result": 1}
```

---

### Differential Equations

#### `solve_ode`

Solve an ordinary differential equation using Sage's `desolve()`. The equation is specified as a string using Sage's `diff()` notation. The solver returns a general solution with arbitrary constants (`_C`, `_K1`, `_K2`, etc.).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `equation` | `string` | *required* | The ODE as a string. Use `diff(y(x),x)` for y', `diff(y(x),x,x)` for y'', etc. Include `= 0` or `= rhs` to specify the equation. |
| `function` | `string` | `"y"` | Name of the dependent function being solved for. |
| `variable` | `string` | `"x"` | Name of the independent variable. |

**Returns:** `{"solution": "..."}`

```
> solve_ode(equation="diff(y(x),x) + y(x) = 0")
  {"solution": "_C*e^(-x)"}

> solve_ode(equation="diff(y(x),x,x) - y(x) = 0")
  {"solution": "_K1*e^(-x) + _K2*e^x"}

> solve_ode(equation="diff(y(x),x) = x*y(x)")
  {"solution": "_C*e^(1/2*x^2)"}

> solve_ode(equation="diff(y(t),t) + 2*y(t) = sin(t)", function="y", variable="t")
  {"solution": "..."}
```

---

### Number Theory

#### `number_theory_operation`

Perform common number-theoretic operations using Sage's built-in functions.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `operation` | `string` | *required* | One of: `"is_prime"`, `"factor_integer"`, `"next_prime"`, `"gcd"`, `"lcm"`. |
| `a` | `int` | *required* | Primary integer argument. |
| `b` | `int` or `null` | `null` | Second integer. **Required** for `gcd` and `lcm`; ignored otherwise. |

**Returns:** `{"operation": "...", "result": ...}` --- result type varies:

| Operation | Result type | Sage function called | Description |
|-----------|------------|---------------------|-------------|
| `is_prime` | `bool` | `is_prime(a)` | Whether `a` is a prime number. |
| `factor_integer` | `string` | `factor(a)` | Prime factorization as a human-readable string (e.g. `"2^3 * 3 * 5"`). |
| `next_prime` | `int` | `next_prime(a)` | The smallest prime greater than `a`. |
| `gcd` | `int` | `gcd(a, b)` | Greatest common divisor of `a` and `b`. |
| `lcm` | `int` | `lcm(a, b)` | Least common multiple of `a` and `b`. |

```
> number_theory_operation(operation="is_prime", a=997)
  {"operation": "is_prime", "result": true}

> number_theory_operation(operation="factor_integer", a=2520)
  {"operation": "factor_integer", "result": "2^3 * 3^2 * 5 * 7"}

> number_theory_operation(operation="next_prime", a=100)
  {"operation": "next_prime", "result": 101}

> number_theory_operation(operation="gcd", a=48, b=180)
  {"operation": "gcd", "result": 12}

> number_theory_operation(operation="lcm", a=12, b=18)
  {"operation": "lcm", "result": 36}
```

---

### Statistics

#### `statistics_summary`

Compute descriptive statistics for a numeric dataset. Uses Python's `statistics` module internally.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `data` | `list[float]` | *required* | List of numeric values. Must contain at least 2 elements for variance/std dev. |

**Returns:** a dictionary with all of:

| Field | Description |
|-------|-------------|
| `mean` | Arithmetic mean. |
| `median` | Median value. |
| `population_variance` | Population variance (divides by N). |
| `sample_variance` | Sample variance (divides by N-1). |
| `population_std_dev` | Population standard deviation. |
| `sample_std_dev` | Sample standard deviation. |
| `min` | Minimum value. |
| `max` | Maximum value. |

```
> statistics_summary(data=[2, 4, 4, 4, 5, 5, 7, 9])
  {"mean": 5.0, "median": 4.5, "population_variance": 4.0, "sample_variance": 4.571..., ...}
```

---

### Visualization

#### `plot_expression`

Render a 2D plot of an expression and return it as a base64-encoded PNG image. Calls Sage's `plot()` function and serializes the result to an in-memory PNG buffer.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `expression` | `string` | *required* | The expression to plot. |
| `variable` | `string` | `"x"` | The plot variable. |
| `range_min` | `float` | `-10.0` | Lower bound of the plot range. |
| `range_max` | `float` | `10.0` | Upper bound of the plot range. |

**Returns:** `{"image_base64": "...", "format": "png"}`

The returned base64 string can be rendered directly in any client that supports inline images (e.g., via an `<img>` tag or Markdown `![](data:image/png;base64,...)`).

```
> plot_expression(expression="sin(x)*e^(-x/5)", range_min=-5, range_max=20)
  {"image_base64": "iVBORw0KGgo...", "format": "png"}

> plot_expression(expression="x^3 - 3*x", range_min=-3, range_max=3)
  {"image_base64": "...", "format": "png"}
```

---

### Session Management & Observability

#### `reset_sage_session`

Clear all variables, functions, and definitions in the current session. The underlying worker process continues running (fast). Equivalent to restarting a fresh Sage shell.

**Returns:** `{"message": "Session cleared"}`

#### `cancel_sage_session`

Abort any in-flight computation by killing the worker process and starting a new one. Use this when a computation is stuck or taking too long. All session state is lost.

**Returns:** `{"message": "Session cancelled and restarted"}`

#### MCP Resources

| Resource URI | Scope values | Description |
|-------------|-------------|-------------|
| `resource://sagemath/session/{scope}` | `all`, or a specific session ID | Returns JSON with: `session_id`, `live` (bool), `started_at`, `last_used_at`, `idle_seconds`. |
| `resource://sagemath/monitoring/{scope}` | `metrics`, `all` | Returns JSON with: `attempts`, `successes`, `failures`, `security_failures`, `avg_elapsed_ms`, `max_elapsed_ms`, `last_run_at`, `last_error`, `last_security_violation`, `last_error_details`. |
| `resource://sagemath/docs/{scope}` | `all`, `reference`, `tutorial` | Returns documentation link objects with URLs to SageMath documentation. |

---

## Security Sandbox

All code --- whether from `evaluate_sage` or generated internally by helper tools --- passes through an AST-based security validator before execution.

**What is blocked:**

| Category | Details |
|----------|---------|
| Dangerous builtins | `eval()`, `exec()`, `compile()`, `__import__()`, `open()`, `input()`, `globals()`, `locals()`, `vars()` |
| Filesystem/process ops | `os.system`, `os.popen`, `os.remove`, `os.fork`, `subprocess.*`, `shutil.rmtree`, `pathlib.*`, `socket.*` |
| Unauthorized imports | All imports except those in the allowlist (see below) |
| Scope manipulation | `global` and `nonlocal` statements (configurable) |

**What is allowed:**

| Import | Reason |
|--------|--------|
| `math`, `cmath` | Standard math functions |
| `statistics` | Used by `statistics_summary` |
| `base64`, `io` | Used by `plot_expression` for in-memory PNG encoding |
| `sage`, `sage.all`, `sage.*` | Full SageMath library |

**Enforced limits:**

| Limit | Default | Env var |
|-------|---------|---------|
| Max source code length | 8,000 chars | `SAGEMATH_MCP_SECURITY_MAX_SOURCE` |
| Max AST node count | 2,500 | `SAGEMATH_MCP_SECURITY_MAX_AST_NODES` |
| Max AST nesting depth | 75 | `SAGEMATH_MCP_SECURITY_MAX_AST_DEPTH` |

**Error handling:** When code violates the security policy, the server returns a clear error message identifying the violation (e.g., "Call to forbidden function 'eval' is blocked") and logs a warning. The session remains alive --- subsequent calls can succeed.

---

## LLM Client Configuration

Clients connecting through MCP receive the following guidance automatically:

- **Stateful sessions** --- every conversation owns a dedicated Sage worker. Define symbols once
  (e.g., `var('x')`, `f = ...`) and reuse them across subsequent tool calls.
- **Use the right tool** --- reach for specialized helpers (`solve_equation`, `differentiate_expression`, etc.) for structured JSON output. Fall back to `evaluate_sage` for anything else.
- **Chain computations** --- assign results in one call and reference them in the next. All state persists within the session.
- **Timeouts** --- long computations emit heartbeat progress events. Adjust per-call timeouts via the `timeout` parameter.
- **Security** --- the AST validator blocks arbitrary imports, `eval`/`exec`, and filesystem/process calls. Prefer Sage primitives; if a violation occurs, rewrite the workflow using supported APIs.

### Client-Specific Setup

**Claude Desktop** --- add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "sagemath": {
      "command": "uv",
      "args": ["run", "sagemath-mcp"]
    }
  }
}
```

**Claude Code** --- add to `.mcp.json` in the project root:

```json
{
  "mcpServers": {
    "sagemath": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "sagemath-mcp"]
    }
  }
}
```

**Codex CLI:**

```bash
codex mcp add sagemath --command uv --args "run" "sagemath-mcp"
```

**Gemini CLI:**

```bash
gemini mcp add sagemath --transport stdio --command uv --arg run --arg sagemath-mcp
```

For HTTP transport, expose the endpoint first (`sagemath-mcp --transport streamable-http --host 0.0.0.0 --port 8314`) and point the client at `http://HOST:8314/mcp`.

---

## Deployment

### stdio (default)

```bash
uv run sagemath-mcp
```

Best for local LLM clients (Claude Desktop, Claude Code, Codex CLI). The client spawns the server as a subprocess and communicates over stdin/stdout.

### HTTP / Streamable HTTP

```bash
uv run sagemath-mcp --transport streamable-http --host 127.0.0.1 --port 8314
```

Best for remote clients, browser-based tools, or shared environments. Supports streaming responses and cancellation.

### Docker Compose

```bash
docker compose up --build
```

Exposes `http://127.0.0.1:8314/mcp`. Runs as non-root `sage` user (UID/GID 1000). The compose file mounts the repository at `/workspace` and accepts environment variable overrides for all `SAGEMATH_MCP_*` settings.

### Kubernetes (Helm)

```bash
helm install sagemath charts/sagemath-mcp \
  --set image.repository=ghcr.io/xbp-europe/sagemath-mcp \
  --set image.tag=latest
```

Key values: `service.port`, `env` (map of environment overrides), `args` (CLI arguments), `ingress.*`. The chart enforces non-root execution (`runAsUser`/`runAsGroup` 1000). Review `values.yaml` for the full set of configurable knobs. The release workflow validates the chart with `helm lint` and `helm template` before publishing.

---

## Configuration Reference

All configuration is done via environment variables. No config files are needed.

### Runtime Settings

| Variable | Description | Default |
| --- | --- | --- |
| `SAGEMATH_MCP_SAGE_BINARY` | Path to the `sage` executable. | `sage` |
| `SAGEMATH_MCP_STARTUP` | Sage code executed during session bootstrap. | `from sage.all import *` |
| `SAGEMATH_MCP_IDLE_TTL` | Seconds of inactivity before a session is culled. | `900` |
| `SAGEMATH_MCP_EVAL_TIMEOUT` | Per-evaluation timeout in seconds. | `30` |
| `SAGEMATH_MCP_MAX_STDOUT` | Maximum characters of `stdout` returned per call. | `100000` |
| `SAGEMATH_MCP_SHUTDOWN_GRACE` | Grace period before a stuck worker is terminated. | `2` |
| `SAGEMATH_MCP_FORCE_PYTHON_WORKER` | Use the pure-Python worker (helpful for tests/CI). | `false` |
| `SAGEMATH_MCP_PURE_PYTHON` | When set to `1`, load math stdlib instead of Sage modules. | unset |

### Security Settings

| Variable | Description | Default |
| --- | --- | --- |
| `SAGEMATH_MCP_SECURITY_ENABLED` | Enable/disable AST-based code validation. | `true` |
| `SAGEMATH_MCP_SECURITY_MAX_SOURCE` | Maximum source length in characters. | `8000` |
| `SAGEMATH_MCP_SECURITY_MAX_AST_NODES` | Maximum AST node count allowed. | `2500` |
| `SAGEMATH_MCP_SECURITY_MAX_AST_DEPTH` | Maximum AST depth allowed. | `75` |
| `SAGEMATH_MCP_SECURITY_ALLOW_IMPORTS` | Permit `import` statements when set to `true`. | `false` |
| `SAGEMATH_MCP_SECURITY_FORBID_GLOBAL` | Block `global` statements when `true`. | `true` |
| `SAGEMATH_MCP_SECURITY_FORBID_NONLOCAL` | Block `nonlocal` statements when `true`. | `true` |
| `SAGEMATH_MCP_SECURITY_LOG_VIOLATIONS` | Emit warnings when code is blocked. | `true` |
| `SAGEMATH_MCP_SECURITY_ALLOWED_IMPORTS` | Comma-separated allowlist of importable modules. | `math,cmath,statistics,base64,io,sage,sage.all` |
| `SAGEMATH_MCP_SECURITY_ALLOWED_IMPORT_PREFIXES` | Comma-separated prefixes treated as safe namespaces. | `sage.` |

---

## CLI Reference

```
usage: sagemath-mcp [--transport {stdio,http,streamable-http,sse}]
                    [--host HOST] [--port PORT] [--path PATH]
                    [--log-level LOG_LEVEL]
```

| Argument | Description | Default |
|----------|-------------|---------|
| `--transport` | Transport protocol: `stdio`, `http`, `streamable-http`, or `sse`. | `stdio` |
| `--host` | Bind address for HTTP transports. | `127.0.0.1` |
| `--port` | Listen port for HTTP transports. | `8314` |
| `--path` | Custom HTTP path (e.g., `/mcp`) for `streamable-http` or `sse` transports. | auto |
| `--log-level` | Python logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`). | `INFO` |

```bash
# Default: stdio transport for Claude Desktop / Codex CLI
sagemath-mcp

# HTTP transport for browser-based or remote clients
sagemath-mcp --transport streamable-http --host 0.0.0.0 --port 8314

# Debug logging
sagemath-mcp --log-level DEBUG

# With uv
uv run sagemath-mcp --transport streamable-http --host 127.0.0.1 --port 8314
```

---

## Development

### Prerequisites

- Python 3.12+ with [uv](https://docs.astral.sh/uv/) installed
- Docker (optional, for integration tests and Sage container)
- SageMath (optional, for local development without Docker)

### Commands

```bash
uv pip install -e .[dev]       # Install with dev extras
make lint                       # ruff check (ruff 0.15+)
make test                       # pytest (pure Python, no Sage needed)
make integration-test           # pytest inside Sage Docker container
make build                      # sdist + wheel via scripts/build_release.py
make cli-integration            # Run CLI integration tests (Claude + Gemini)
make sage-container             # Bootstrap the Sage Docker container
```

### Running Tests

Without a local SageMath installation you can still run all 242 unit tests --- the test suite replaces the Sage worker with a lightweight Python interpreter to validate session plumbing. Code coverage is at **99%** across all core modules.

```bash
# Run all unit tests
uv run pytest

# Run a single test
uv run pytest tests/test_server.py -k "test_solve_equation"

# Run with coverage
uv run pytest --cov=sagemath_mcp --cov-report=term-missing
```

### Linting

Ruff with line-length 100, target Python 3.12. Rules: E, F, W, B, UP, ASYNC, RUF, I (import sorting). Run `make lint` before committing.

### Git Hooks

Configure Git hooks after cloning:

```bash
git config core.hooksPath .githooks
```

The pre-push hook runs ruff automatically.

---

## CLI Integration Testing

The project includes a comprehensive end-to-end test suite that validates the MCP server through real LLM CLI invocations. Located in `tests/cli_integration/`.

### Overview

- **43 test cases** across 9 mathematical domains
- Tests both **Claude Code** (`claude --print`) and **Gemini CLI** (`gemini -p`)
- Live progress reporting during execution
- Multi-tier validation: substring matching, numeric extraction, soft-fail for non-deterministic output
- JSON result export for historical tracking

### Running

```bash
# Run against both CLIs
make cli-integration

# Or use the standalone runner with options
python -m tests.cli_integration.run_cli_tests --cli claude --domain calculus
python -m tests.cli_integration.run_cli_tests --cli both --parallel
python -m tests.cli_integration.run_cli_tests --cli gemini --domain algebra,number_theory
```

### Domain Coverage

| Domain | Cases | Tools tested |
|--------|-------|-------------|
| Calculus | 10 | `differentiate_expression`, `integrate_expression`, `limit_expression`, `series_expansion` |
| Algebra | 11 | `solve_equation`, `simplify_expression`, `expand_expression`, `factor_expression`, `calculate_expression` |
| Linear algebra | 5 | `matrix_multiply`, `matrix_operation` |
| ODEs | 2 | `solve_ode` |
| Number theory | 6 | `number_theory_operation` |
| Statistics | 2 | `statistics_summary` |
| Plotting | 2 | `plot_expression` |
| General | 3 | `evaluate_sage` |
| Session | 2 | `reset_sage_session`, `cancel_sage_session` |

---

## Project Layout

```
sagemath-mcp/
├── pyproject.toml                  # Project metadata, dependencies, tool config
├── README.md                       # This file
├── USAGE.md                        # Detailed usage guide
├── CLAUDE.md                       # Claude Code project instructions
├── Dockerfile                      # Production container (SageMath + MCP server)
├── docker-compose.yml              # Local development stack
├── Makefile                        # Common commands (test, lint, build, etc.)
├── src/sagemath_mcp/
│   ├── server.py                   # FastMCP 3.x app: 33 tools, 3 resources, /health, middleware
│   ├── session.py                  # Sage worker lifecycle, session management, idle culling
│   ├── _sage_worker.py             # Subprocess worker: code execution, AST validation, LaTeX
│   ├── security.py                 # AST validator, SecurityPolicy, configurable allowlists
│   ├── config.py                   # SageSettings from environment variables
│   ├── models.py                   # Pydantic models (EvaluateResult, SessionSnapshot, etc.)
│   ├── monitoring.py               # Thread-safe evaluation metrics (EvaluationMetrics)
│   └── py.typed                    # PEP 561 type hint marker
├── tests/
│   ├── conftest.py                 # Shared FakeContext fixture
│   ├── test_server.py              # Tool & resource unit tests
│   ├── test_session.py             # Session lifecycle, timeout, reset, cancel
│   ├── test_security.py            # AST validation, policy configuration
│   ├── test_config.py              # Environment variable parsing
│   ├── test_sage_worker.py         # Worker protocol, LaTeX, startup errors
│   ├── test_integration.py         # Real Sage: monitoring, timeout, cancellation
│   ├── test_use_cases.py           # End-to-end Sage workflows
│   └── cli_integration/            # LLM CLI end-to-end tests (43 cases)
│       ├── run_cli_tests.py        # Standalone runner with rich reporting
│       ├── test_cases.py           # All test case definitions
│       ├── validate.py             # Multi-tier output validation
│       ├── runner.py               # Claude/Gemini CLI invocation
│       ├── cli_config.py           # MCP server setup/teardown for CLIs
│       ├── test_claude.py          # Pytest wrapper for Claude
│       └── test_gemini.py          # Pytest wrapper for Gemini
├── charts/sagemath-mcp/            # Helm chart for Kubernetes
├── scripts/                        # Build, release, CI scripts
├── docs/reference_md/              # SageMath reference docs (Markdown)
└── .github/workflows/
    ├── ci.yml                      # 6 parallel jobs: lint, test (3.12+3.13), security
    │                               #   (pip-audit), helm, integration, smoke
    ├── release.yml                 # Multi-Python test, build, GHCR push, PyPI publish
    └── version-bump.yml            # Manual version bump + tag workflow
```

---

## Technology Stack

| Component | Version | Purpose |
|-----------|---------|---------|
| [FastMCP](https://gofastmcp.com/) | 3.2+ | MCP server framework (tools, resources, middleware) |
| [MCP SDK](https://github.com/modelcontextprotocol/python-sdk) | 1.27+ | Model Context Protocol implementation |
| [Pydantic](https://docs.pydantic.dev/) | 2.12+ | Data validation and serialization for all models |
| [anyio](https://anyio.readthedocs.io/) | 4.13+ | Async runtime abstraction |
| [SageMath](https://www.sagemath.org/) | 10.x | Mathematics engine (subprocess worker) |
| [Ruff](https://docs.astral.sh/ruff/) | 0.15+ | Linting and import sorting |
| [pytest](https://docs.pytest.org/) | 9.0+ | Test framework |
| [pytest-asyncio](https://github.com/pytest-dev/pytest-asyncio) | 1.3+ | Async test support |
| [pytest-cov](https://github.com/pytest-dev/pytest-cov) | 7.0+ | Coverage reporting (99% branch coverage, 242 tests) |
| [pip-audit](https://github.com/pypa/pip-audit) | 2.9+ | Dependency vulnerability scanning |
| [Hatchling](https://hatch.pypa.io/) | 1.29+ | Build backend |
| [Docker](https://www.docker.com/) | --- | Containerization and CI integration testing |
| [Helm](https://helm.sh/) | 3.15+ | Kubernetes deployment |
| [GitHub Actions](https://github.com/features/actions) | --- | CI/CD (Node.js 24 compatible) |
| [Cosign](https://docs.sigstore.dev/cosign/) | --- | Container image signing |

---

## Changelog

### v0.2.0 (2026-04-03)

#### New MCP Tools (18 tools added)

The server grew from a single `evaluate_sage` tool to a comprehensive mathematics toolkit with 33 MCP tools (30 Sage-backed, 1 pure-Python, 2 infrastructure). Each tool accepts structured parameters, runs through the AST security validator, and returns typed JSON responses.

**Calculus (4 tools):**
- `differentiate_expression` --- symbolic derivatives of any order. Supports all Sage-recognized expressions including trigonometric, exponential, logarithmic, and user-defined functions. The `order` parameter handles higher-order derivatives without repeated calls.
- `integrate_expression` --- indefinite and definite integrals. Accepts symbolic bounds (`"-oo"`, `"oo"`, `"pi/2"`) for improper integrals. Returns whether the result is definite or indefinite for downstream processing.
- `limit_expression` --- one-sided and two-sided limits. The `direction` parameter (`"plus"` / `"minus"`) enables computing left and right limits separately, critical for analyzing discontinuities.
- `series_expansion` --- Taylor and Laurent series around any point. The `order` parameter controls the number of terms, and the output includes the Big-O remainder term.

**Algebra & Simplification (5 tools):**
- `solve_equation` --- single equations and systems of simultaneous equations. Parses human-readable equation strings (splitting on `=`) so clients don't need to construct Sage syntax. Supports symbolic solutions including trigonometric roots.
- `simplify_expression` --- applies Sage's `simplify()` which tries multiple simplification strategies (trigonometric identities, algebraic rules, etc.) and returns the simplest form found.
- `expand_expression` --- expands products, powers, and identities using Sage's `expand()`. Useful for verifying algebraic identities or preparing expressions for further manipulation.
- `factor_expression` --- factors both symbolic polynomials and integers. Returns human-readable factorization strings (e.g., `"2^2 * 3 * 5"` for integers).
- `calculate_expression` --- evaluates any expression and returns both its symbolic string form and numeric float value (when possible). Pre-declares variables `x, y, z, t` for convenience.

**Linear Algebra (2 tools):**
- `matrix_multiply` --- multiplies two matrices over the Symbolic Ring. Accepts nested list input and returns nested list output with proper type coercion.
- `matrix_operation` --- performs determinant, inverse, eigenvalue, rank, RREF, and transpose operations. Each operation returns appropriately typed results (scalar, matrix, or list).

**Differential Equations (1 tool):**
- `solve_ode` --- solves first- and higher-order ODEs using Sage's `desolve()`. Returns general solutions with arbitrary constants. Supports custom function and variable names for non-standard ODE notation.

**Number Theory (1 tool):**
- `number_theory_operation` --- five operations in one tool: `is_prime`, `factor_integer`, `next_prime`, `gcd`, `lcm`. Each maps directly to the corresponding Sage function with proper integer validation.

**Statistics (1 tool):**
- `statistics_summary` --- computes 8 descriptive statistics (mean, median, population/sample variance, population/sample std dev, min, max) in a single call. Uses Python's `statistics` module for numerical stability.

**Visualization (1 tool):**
- `plot_expression` --- renders 2D function plots and returns base64-encoded PNG images. Uses Sage's `plot()` with configurable range bounds. The `base64` and `io` imports were added to the security allowlist specifically for this tool.

**Session Management (2 tools):**
- `reset_sage_session` --- clears all session state (variables, functions, definitions) without killing the worker process. Fast operation for starting fresh within the same session.
- `cancel_sage_session` --- kills the worker process and starts a new one. Use when a computation is stuck. All state is lost but a clean worker is guaranteed.

#### Enhanced `evaluate_sage`

The core evaluation tool received major improvements:
- **Domain-specific examples** added to the tool description so LLMs know what Sage can do: combinatorics, graph theory, number theory, geometry, probability, group theory, polynomial rings, and coding theory examples are included in the description that clients see.
- **Startup error propagation** --- if `from sage.all import *` (or custom startup code) fails, subsequent calls return a clear `StartupError` with the original exception message instead of a confusing `NameError`.
- **Result type simplification** --- removed the unused `"void"` literal from `result_type`, leaving only `"expression"` and `"statement"`.

#### CLI Integration Test Suite

A new end-to-end test suite validates the MCP server through real LLM CLI invocations:
- **43 test cases** across 9 mathematical domains (calculus, algebra, linear algebra, ODEs, number theory, statistics, plotting, general computation, session management)
- **Dual CLI support** --- tests both Claude Code (`claude --print`) and Gemini CLI (`gemini -p`)
- **Live progress reporting** --- each test prints status as it completes, with color-coded pass/fail indicators and elapsed time
- **Parallel execution** --- `--parallel` flag runs both CLIs concurrently via `ThreadPoolExecutor`
- **Domain filtering** --- `--domain calculus,algebra` runs only selected test domains
- **Multi-tier validation** --- checks expected substrings first (case-insensitive), then extracts numbers from output, then falls back to soft-fail for non-deterministic answers. Error indicators are checked *after* content matching to avoid false negatives when the LLM mentions "MCP server" in a correct answer.
- **JSON result export** --- each run saves timestamped JSON results for historical tracking
- **Pytest integration** --- `test_claude.py` and `test_gemini.py` wrap all cases as parametrized pytest tests with proper skip/fail handling

#### Dependency Upgrades

| Package | Old | New | Notes |
|---------|-----|-----|-------|
| FastMCP | 2.13 | **3.2** | Major version. `@mcp.tool()` / `@mcp.resource()` now return the original function directly (no `.fn` wrapper). All test invocations migrated. |
| MCP SDK | 1.20 | 1.27 | Protocol improvements |
| pytest | 8.4 | **9.0** | Major version |
| pytest-asyncio | 1.2 | 1.3 | Minor improvements |
| Ruff | 0.14 | 0.15 | New lint rules |
| Pydantic | 2.8+ | 2.12+ | Performance and validation improvements |
| anyio | 4.4+ | 4.13+ | Bug fixes and new features |
| Hatchling | 1.26+ | 1.29+ | Build backend improvements |
| build | 1.2+ | 1.4+ | sdist/wheel builder |
| coverage | 7.6+ | 7.13+ | Coverage reporting |

#### Infrastructure Modernization

**Python version:**
- Minimum Python raised from 3.11 to **3.12**. Python 3.12 brings 5-15% performance improvements (PEP 709 inlined comprehensions, faster `asyncio`), and all CI/release workflows now test on 3.12 and 3.13 only.
- Ruff target updated from `py311` to `py312`.

**CI/CD overhaul:**
- **Parallel job structure** --- the monolithic CI job was split into 6 independent jobs (`lint`, `test`, `security`, `helm`, `integration`, `smoke`) that run in parallel. Lint and test complete in ~1 minute; integration and smoke tests run only after they pass.
- **Matrix testing** --- unit tests now run on both Python 3.12 and 3.13 (previously only tested one version in CI; matrix testing was reserved for release).
- **uv caching** --- `enable-cache: true` added to all `astral-sh/setup-uv` steps, eliminating redundant dependency downloads across runs.
- **Coverage reporting** --- pytest runs with `--cov` and uploads `coverage.xml` as a build artifact.
- **Dependency security scanning** --- new `pip-audit` job checks for known vulnerabilities in all installed packages.
- **GitHub Actions Node.js 24** --- all actions bumped: `checkout@v5`, `setup-uv@v7`, `setup-python@v6`, `download-artifact@v6`, `build-push-action@v6`, `upload-artifact@v4`.

**Docker:**
- Base image pinned from `sagemath/sagemath:latest` to `sagemath/sagemath:10.5` for reproducible builds. The `latest` tag was non-deterministic and could break builds when SageMath released new versions.

**Kubernetes (Helm chart):**
- Added **liveness probe** (TCP socket on HTTP port, 30s initial delay, 15s period, 3 failure threshold) --- restarts the pod if the server becomes unresponsive.
- Added **readiness probe** (TCP socket, 10s initial delay, 10s period) --- removes the pod from service endpoints during startup or transient failures.
- Added **startup probe** (TCP socket, 5s initial delay, 5s period, 12 failures = 60s budget) --- gives SageMath time to initialize (`from sage.all import *` can take 10-20s) without triggering liveness failures.
- All probe parameters are configurable via `values.yaml`.

**Project metadata:**
- `pyproject.toml` author updated from placeholder to "XBP Europe"
- Added PyPI classifiers: Development Status, Intended Audience, Python versions, License, Topic
- Added project URLs: Homepage, Repository, Issues, Changelog

#### Test Coverage

Test suite expanded from 136 to **242 unit tests** with branch coverage at **99%** across all core modules. New tests cover:

- Session error paths: no Python interpreter, SAGE_VENV/PYTHONPATH environment handling, reset failures (worker terminated, `ok=False`), `_terminate_worker` with running process, `cull_idle` with no stale sessions
- Server error branches: `evaluate_sage` with no context / no session_id, `SecurityViolation` error type, non-security error type, `SageProcessError` with `__cause__`
- Security: `_format_violation` with blank-lines-only code, `log_violations=False` branch, debug log on successful validation

Remaining 1% is defensive `if ctx is not None` branches that are always true in practice, and the Sage binary path which requires a real Sage installation.

#### Bug Fixes

- **MCP resource serialization** --- `monitoring_resource` and `session_resource` now return JSON strings via `model_dump_json()` instead of raw Pydantic model objects. FastMCP 3.x requires resources to return `str` or `ResourceContent`, not models. The CI metrics verification script and all tests were updated accordingly.
- **ASYNC240 lint fix** --- moved `Path(__file__).resolve()` from inside an async function to a module-level `_PROJECT_ROOT` constant to avoid sync filesystem calls in async context.
- **CLI integration validator** --- error indicator checks (phrases like "I can't", "MCP server") are now evaluated *after* expected-substring matching, preventing false negatives when a correct answer happens to mention the MCP server.
- **Broken `--` separator in CLI commands** --- all documentation previously showed `uv run sagemath-mcp -- --transport streamable-http` which fails because argparse treats `--` as a positional argument. Fixed across README, INSTALLATION, CLAUDE, USAGE, DISTRIBUTION, and MONITORING docs.
- **LICENSE file mismatch** --- the LICENSE file contained Apache 2.0 text but `pyproject.toml` declared MIT. Replaced with the correct MIT license text.
- **Version synchronization** --- `__init__.py` fallback version (was `0.1.2`) and Helm chart version/appVersion (was `0.1.0`) updated to match `pyproject.toml` (`0.2.0`).
- **Missing `pytest-cov` dependency** --- CI coverage step failed because `pytest-cov` was not in dev dependencies. Added alongside `pip-audit`.
- **Suppressed `PytestUnraisableExceptionWarning`** --- cosmetic asyncio subprocess transport finalizer warning no longer appears in test output.

#### Documentation

- **Complete README rewrite** --- added table of contents, architecture diagram, technology stack table, changelog, CLI integration testing section, and detailed examples for every tool parameter and return type.
- **USAGE.md** updated with new tool workflows and deployment options.
- **CLAUDE.md** added for Claude Code project instructions.
- **INSTALLATION.md** updated Python version from 3.11 to 3.12.

### v0.1.2 (2025-11-02)

**Initial public release.** The server provided a single MCP tool (`evaluate_sage`) that executed arbitrary SageMath code within persistent sessions. Key capabilities in the initial release:

- **`evaluate_sage` tool** --- execute any SageMath code with LaTeX output, stdout capture, and configurable per-call timeouts. Variables and functions persist across calls within the same MCP session.
- **Session isolation** --- each MCP client gets a dedicated Sage worker subprocess. Crashes or timeouts in one session cannot affect others.
- **AST-based security sandbox** --- every code snippet is validated before execution, blocking `eval`/`exec`, filesystem operations, process spawning, and unauthorized imports. Configurable via environment variables.
- **Progress heartbeats** --- long-running computations emit periodic progress events (~1.5s) so clients can display activity indicators.
- **Multiple transports** --- stdio (for Claude Desktop), HTTP, streamable-HTTP, and SSE.
- **Docker deployment** --- Dockerfile, Docker Compose, and Helm chart for Kubernetes with non-root execution (UID/GID 1000).
- **CI/CD pipeline** --- GitHub Actions with lint, unit tests, integration tests (real Sage in Docker), Docker Compose smoke test, Helm validation, signed GHCR image publishing, and PyPI publishing.
- **Monitoring resources** --- MCP resources for session snapshots, aggregated metrics, and SageMath documentation links.

---

## Roadmap

See [ROADMAP.md](ROADMAP.md) for the full prioritized plan. Highlights:

**Phase 1 — High-value tools:**
- `symbolic_sum` / `symbolic_product` --- symbolic summation and products
- `combinatorics_operation` --- binomial, permutations, combinations, partitions, Catalan, Fibonacci
- `plot3d_expression` --- 3D surface plots for two-variable functions

**Phase 2 — Medium-value tools:**
- `distribution_operation` --- probability distributions (PDF, CDF, sampling, quantiles)
- `find_root` --- numeric root-finding (complements symbolic `solve_equation`)
- Multi-expression plotting --- overlay multiple functions in one plot
- `vector_calculus_operation` --- gradient, divergence, curl, Laplacian

**Phase 3 — Enrichment:**
- Richer `evaluate_sage` examples (Fourier/Laplace transforms, modular arithmetic, recurrences)
- HTTP `/health` endpoint for Helm probes
- Streaming partial output for long computations
- Disk-backed session persistence

## Requirements

- Python 3.12+
- A local SageMath installation available on the `PATH` (tested with Sage 10.x), or Docker.
- FastMCP-compatible MCP client (e.g. Claude Desktop, Claude Code, Codex CLI, Gemini CLI).

## Contributing

We welcome issues and pull requests! Review the [Code of Conduct](CODE_OF_CONDUCT.md) and
[Contributing Guide](CONTRIBUTING.md) before opening a PR. For vulnerability disclosures,
follow the steps in [SECURITY.md](SECURITY.md). Ownership defaults are defined in
[.github/CODEOWNERS](.github/CODEOWNERS).

## License

MIT
