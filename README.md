# SageMath MCP Server

<!-- mcp-name: io.github.XBP-Europe/sagemath-mcp -->

[![CI](https://github.com/XBP-Europe/sagemath-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/XBP-Europe/sagemath-mcp/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/XBP-Europe/sagemath-mcp.svg)](https://github.com/XBP-Europe/sagemath-mcp/releases/latest)
[![PyPI](https://img.shields.io/pypi/v/sagemath-mcp.svg)](https://pypi.org/project/sagemath-mcp/)
[![GHCR](https://img.shields.io/badge/GHCR-sagemath--mcp-blue?logo=github)](https://github.com/XBP-Europe/sagemath-mcp/pkgs/container/sagemath-mcp)
[![License](https://img.shields.io/github/license/XBP-Europe/sagemath-mcp.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/MCP-Model%20Context%20Protocol-purple)](https://modelcontextprotocol.io/)
[![FastMCP](https://img.shields.io/badge/FastMCP-3.4%2B-green.svg)](https://gofastmcp.com/)
[![SageMath](https://img.shields.io/badge/SageMath-10.9-orange)](https://www.sagemath.org/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://docs.astral.sh/ruff/)
[![Typed](https://img.shields.io/badge/type--checked-py.typed-blue)](https://peps.python.org/pep-0561/)
[![Coverage](https://img.shields.io/badge/coverage-100%25-brightgreen.svg)](https://github.com/XBP-Europe/sagemath-mcp/actions/workflows/ci.yml)
[![Downloads](https://img.shields.io/pypi/dm/sagemath-mcp.svg)](https://pypi.org/project/sagemath-mcp/)
[![MCP Registry](https://img.shields.io/badge/MCP%20Registry-listed-purple)](https://registry.modelcontextprotocol.io/)
[![Signed](https://img.shields.io/badge/images-cosign%20signed-blueviolet?logo=sigstore)](https://github.com/XBP-Europe/sagemath-mcp/blob/main/.github/workflows/release.yml)
[![Dependabot](https://img.shields.io/badge/dependabot-enabled-025E8C?logo=dependabot)](https://github.com/XBP-Europe/sagemath-mcp/blob/main/.github/dependabot.yml)
[![Last commit](https://img.shields.io/github/last-commit/XBP-Europe/sagemath-mcp.svg)](https://github.com/XBP-Europe/sagemath-mcp/commits/main)

A universal mathematics [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) server that gives LLM clients full access to [SageMath](https://www.sagemath.org/) --- one of the most comprehensive open-source mathematics systems available. Built on [FastMCP 3.x](https://gofastmcp.com/), the server maintains a dedicated SageMath process for each MCP session so variables, functions, and assumptions persist across tool calls.

Whether the task is symbolic calculus, number theory, linear algebra, differential equations, plotting, combinatorics, graph theory, group theory, or basic arithmetic, the server provides **37 MCP tools** --- all math tools backed by the full SageMath engine, plus `evaluate_sage_streaming` (streaming wrapper) and an HTTP `/health` endpoint.

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
| **Graph theory** | `graph_operation` | Sage | Named graphs including parameterised constructors (`CompleteGraph(4)`) and adjacency dicts; chromatic number, connectivity, planarity, diameter, shortest path |
| **Group theory** | `group_operation` | Sage | Symmetric, dihedral, cyclic, alternating groups; order, abelian/cyclic test, center, exponent |
| **Elliptic curves** | `elliptic_curve_operation` | Sage | Rank, torsion, discriminant, j-invariant, conductor, generators |
| **Coding theory** | `coding_theory_operation` | Sage | Hamming and generalized Reed-Solomon codes; length, dimension, minimum distance, generator matrix, rate |
| **Polynomial rings** | `polynomial_ring_operation` | Sage | Groebner bases, ideal dimension/variety, reduction, Groebner test |
| **Boolean algebra** | `boolean_algebra_operation` | Sage | Boolean polynomial ring, addressed as `x, y, z` or `x0, x1, x2`; evaluate, variables, degree, zero/one test |
| **Geometry** | `geometry_operation` | Sage | Distance, polygon area, polytope volume, convex hull, compactness via `Polyhedron` |
| **Statistics** | `statistics_summary` | Sage | Mean, median, population & sample variance/std dev, min, max |
| **Probability** | `distribution_operation` | Sage | Normal, exponential, Poisson, chi-squared, Student-t, uniform, beta, gamma; PDF, CDF, quantile, analytic mean/variance, sampling |
| **Visualization** | `plot_expression`, `plot3d_expression`, `plot_multi_expression` | Sage | 2D plots, 3D surface plots, multi-function overlays as base64-encoded PNG |
| **Numeric methods** | `find_root` | Sage | Numeric root-finding in an interval via Sage's `find_root()`, from an expression or an equation |
| **Vector calculus** | `vector_calculus_operation` | Sage | Gradient, divergence, curl, Laplacian on scalar/vector fields |
| **Session control** | `reset_sage_session`, `interrupt_sage_session`, `cancel_sage_session` | Worker | Clear state, or stop a computation with or without keeping variables |
| **Named workspaces** | `start_sage_session`, `list_sage_sessions`, `stop_sage_session` | Worker | Several independent variable namespaces per client |
| **Infrastructure** | `/health` endpoint, 3 MCP resources | Server | Health check, session snapshots, aggregated metrics, documentation links |

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│  MCP Client (Claude Desktop, Gemini CLI, Codex CLI, etc.)       │
└─────────────────────────────────────────────────────────────────┘
                      │  MCP protocol (stdio or HTTP)
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│  app.py + tools/ --- FastMCP 3.x Application                    │
│                                                                 │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────────┐  │
│  │ 37 MCP Tools│  │ 3 Resources  │  │ Middleware             │  │
│  │ (evaluate,  │  │ (session,    │  │ - Request logging      │  │
│  │  solve,     │  │  monitoring, │  │ - Catalogue cache only │  │
│  │  diff, ...) │  │  docs)       │  │ - Progress heartbeats  │  │
│  └──────┬──────┘  └──────────────┘  └────────────────────────┘  │
│         │                                                       │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  session.py --- SageSessionManager                          ││
│  │   Per-client session map with asyncio locks, idle culling   ││
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐          ││
│  │  │ Session A   │  │ Session B   │  │ Session C   │  ...     ││
│  │  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘          ││
│  └─────────┼────────────────┼────────────────┼─────────────────┘│
└────────────┼────────────────┼────────────────┼──────────────────┘
             │                │                │
             ▼                ▼                ▼
     ┌────────────────────────────────────────────────┐
     │  _sage_worker.py --- Subprocess Workers        │
     │  JSON stdin/stdout protocol                    │
     │                                                │
     │  ┌────────────┐   ┌──────────────────────┐     │
     │  │allowlist.py│──▶│ is this name offered?│     │
     │  │security.py │   │ AST checks, then     │     │
     │  │            │   │ exec() -- or refuse  │     │
     │  └────────────┘   └──────────────────────┘     │
     │                                                │
     │  Namespace scrubbed at startup, then           │
     │  persistent: vars, functions and classes       │
     │  survive across calls                          │
     └────────────────────────────────────────────────┘
```

**Request flow:** MCP client → a tool in `tools/` → `SageSessionManager.get_or_create()` → `SageSession.evaluate()` → JSON request to `_sage_worker.py` subprocess → AST validation → `exec()` in persistent namespace → JSON response back.

**Key design decisions:**

- **Process isolation:** Each session runs SageMath in a separate subprocess. A crash or timeout in one session cannot affect others.
- **Stateful sessions:** Variables, functions, and assumptions persist across tool calls within the same MCP session, enabling multi-step mathematical workflows.
- **Deny-by-default for caller code:** a name is refused unless the generated allowlist offers it or the caller's own code bound it. Every snippet also passes an AST validator before execution, whichever tool it arrived through. The allowlist came after a run of bypasses that shared one shape — a name nobody had thought to forbid — and it means a helper a future SageMath adds is refused until someone reviews it, rather than reachable the day it lands.
- **Caching is deliberately narrow:** only the tool, resource and prompt *catalogues* are cached. Tool-call and resource-response caching are off, because the cache key does not include the client identity and two clients making the same call would collide.
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

The compose service exposes port `8314` on both host and container and mounts the repository at `/workspace`. Containers run as the non-root `sage` user (UID/GID 1001) to match the base image. Tweak runtime settings by editing the environment block (for example, increase `SAGEMATH_MCP_EVAL_TIMEOUT` or adjust `SAGEMATH_MCP_MAX_STDOUT`) before launch.

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
- **Caller code is checked against an allowlist**, so a name works only if SageMath preloads it for mathematics, it is a safe builtin, or your own code defined it — including earlier in the same session. Anything else is refused, and the message names the fix where there is one. The AST validator runs on top of that (see [Security Sandbox](#security-sandbox)).
- **`x`, `y`, `z` and `t` are predefined**, and `evaluate_sage` auto-declares any other symbol-shaped name (`w`, `x_2`, `alpha`) as a symbol the way SageMath's SR does — so `w^2 + 1` just works. The shape is narrow and typo-guarded: a multi-letter name like `sinn` stays an error, and a name you assigned earlier keeps its value.
- Indentation shared by every line is stripped before parsing, so a snippet pasted out of a markdown block is accepted rather than failing as a syntax error.

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

Bounds may also be free symbols, so `upper_bound="a"` integrates to a symbolic limit.
Names Sage already defines keep their meaning: `e`, `pi` and `oo` are the constants,
not new variables.

Both `lower_bound` and `upper_bound` must be provided together for a definite integral, or both omitted for an indefinite integral. Providing only one raises an error.

**Returns:** `{"integral": "...", "definite": true/false}`

```
> integrate_expression(expression="x^2")
  {"integral": "1/3*x^3", "definite": false}

> integrate_expression(expression="x^2", lower_bound="0", upper_bound="1")
  {"integral": "1/3", "definite": true}

> integrate_expression(expression="e^(-x^2)", lower_bound="-oo", upper_bound="oo")
  {"integral": "sqrt(pi)", "definite": true}

> integrate_expression(expression="x", lower_bound="0", upper_bound="a")
  {"integral": "1/2*a^2", "definite": true}
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

The dependent function may be written either applied (`diff(y(x), x) + y(x)`) or bare
(`diff(y, x) + y`). Both describe the same equation and return identical solutions.

**Returns:** `{"solution": "..."}`

```
> solve_ode(equation="diff(y(x),x) + y(x) = 0")
  {"solution": "_C*e^(-x)"}

> solve_ode(equation="diff(y,x) + y = 0")     # bare form, same result
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

Compute descriptive statistics for a numeric dataset using Sage's `mean()` and `sqrt()` functions.

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

### Sage semantics

`evaluate_sage` runs your code through Sage's preparser, exactly as the Sage
REPL does. `2^3` is 8, not 1; integer literals are Sage `Integer`s; generator
syntax such as `K.<a> = NumberField(x^3 - 2)` parses; and `x`, `y`, `z` and `t`
are predefined. Use `^^` for XOR, as in Sage.

Sage's own REPL predefines `x` alone. This server predefines four, because the
specialised tools have always declared `x, y, z, t` in their prelude: with only
`x`, `differentiate_expression("x^2*y^3")` worked while the identical
mathematics through `evaluate_sage` failed.

**In `evaluate_sage`, any other symbol needs `var('w')`,** and the error message
says so. That is exactly SageMath's own rule: `w + 1` typed as *code* is a
`NameError` there too.

**The specialised tools declare a symbol on sight,** because they take an
expression as a *string* and that is SageMath's other rule — `SR("a*b + a")`
creates `a` and `b`. So `simplify_expression("w^2 + w^2")` answers `2*w^2`, and
`expand_expression("(θ + φ)^2")` answers in the letters you wrote.

Narrower than `SR` in the way that matters: `SR` invents *any* identifier, so
`SR("sinn(x)")` returns `sinn(x)` and a typo becomes a silent wrong answer.
Only symbol-shaped names are declared — a letter with an optional index (`a`,
`w`, `x_2`), a spelled-out Greek name (`alpha`), or a Greek letter (`α`, `Ω`) —
so `sinn`, `foobar` and `pi2` are still errors. Names SageMath already defines
are never shadowed: `e` stays Euler's number, `I` the imaginary unit, and
`gamma`, `zeta`, `π`, `σ`, `Γ` and `ψ` stay the functions they are.

Only caller code is preparsed. The specialised tools build plain Python around
`sage_eval`, and preparsing those templates would change what they mean.

### Large integers

Mathematics produces integers that JSON numbers cannot carry. Above 2^53 a JSON
number stops being exact, and JavaScript-based MCP clients parse every number as
an IEEE double --- so `bell(30)` arrived in one CLI as `846749014511809388871680`
instead of `846749014511809332450147`. Nothing errored; the number was simply
wrong, which is the worst way for it to fail.

Both directions therefore speak decimal strings past that boundary:

- **In:** integer parameters from 2^53 upward must be passed as decimal strings;
  a numeric literal that large is rejected rather than silently rounded. The
  boundary is JavaScript's `Number.MAX_SAFE_INTEGER` (2^53 - 1), not 2^53:
  2^53 + 1 rounds to exactly 2^53, so those two arrive indistinguishable and
  neither can be trusted.
- **Out:** integer results beyond that boundary come back as decimal strings.
  Smaller integers keep their numeric type, so ordinary results are unchanged.
- **Matrices:** entries may be integers, decimal strings or floats. Integer
  entries stay exact rather than being rounded through a double, and an
  integral result past the boundary comes back exact. Float matrices behave
  exactly as before.

```json
{"operation": "bell", "result": "846749014511809332450147"}
{"operation": "binomial", "result": 120}
```

#### `interrupt_sage_session`

Stop a running computation **while keeping every variable defined so far**. The worker is signalled, abandons the current statement, and stays alive with its namespace intact. The interrupted call returns an `Interrupted` error.

Prefer this over `cancel_sage_session` — cancelling discards state that may have been expensive to build.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `session` | `string` | `"default"` | Named workspace to interrupt. |

**Returns:** `{"message": "Interrupted session 'default'; state preserved"}`

Interrupting when nothing is running is reported, not an error, and no signal is
sent: `{"message": "No running computation in session 'default'"}`. That matters
beyond tidiness — an idle worker is blocked reading its input, where a SIGINT has
no computation to abort, and signalling it anyway left real Sage workers unable
to answer the next request. POSIX only.

#### `cancel_sage_session`

Abort any in-flight computation by killing the worker process and starting a new one. **All session state is lost** — reach for this only when the worker is wedged badly enough that interrupting does not help.

**Returns:** `{"message": "Session cancelled and restarted"}`

#### `start_sage_session`, `list_sage_sessions`, `stop_sage_session`

One client can hold several independent workspaces. Variables defined in one are invisible to the others, so a long-running exploration and a quick scratch calculation need not collide.

```
> start_sage_session(name="curves")
> evaluate_sage(code="E = EllipticCurve([0,-1])", session="curves")
> evaluate_sage(code="G = graphs.PetersenGraph()", session="graphs")

> evaluate_sage(code="E.rank()", session="curves")
  0
> evaluate_sage(code="E.rank()", session="graphs")     # not defined here
  NameError

> list_sage_sessions()
  {"sessions": [{"name": "curves", "alive": true, "statements": 2}, ...], "count": 2}

> stop_sage_session(name="curves")
```

Every tool that runs on a worker accepts the same optional `session` argument.
Omitting it uses the `default` workspace, which is the behaviour of every earlier
version.

**What `session` does, precisely.** It selects which worker process runs the
call, so a long computation in one workspace can be interrupted or cancelled
without disturbing another. It does **not** give the specialised tools access to
variables you defined with `evaluate_sage`: those tools evaluate their input in a
fresh Sage namespace, so `calculate_expression("myvar")` will not see a `myvar`
assigned earlier. Use `evaluate_sage` for anything that has to build on previous
state.

#### MCP Resources

| Resource URI | Scope values | Description |
|-------------|-------------|-------------|
| `resource://sagemath/session/{scope}` | `all`, or a specific session ID | Returns JSON with: `session_id`, `live` (bool), `started_at`, `last_used_at`, `idle_seconds`. |
| `resource://sagemath/monitoring/{scope}` | `metrics`, `all` | Returns JSON with the process-wide aggregates only: `attempts`, `successes`, `failures`, `security_failures`, `avg_elapsed_ms`, `max_elapsed_ms`, `last_run_at`. Per-failure error text and stdout are not exposed here (they are shared process-global state); see the server logs instead. |
| `resource://sagemath/docs/{scope}` | `all`, `reference`, `tutorial` | Returns documentation link objects with URLs to SageMath documentation. |

---

## Security Sandbox

All code --- whether from `evaluate_sage` or generated internally by helper tools --- passes through an AST-based security validator before execution.

> **What this is, and is not.** The validator is defence in depth against
> accidents and casual misuse. It is **not** a boundary against determined
> adversarial code, and it should not be the only thing standing between an
> untrusted caller and your host. **The container is the security boundary** ---
> run the server in one, and see [Container hardening](#container-hardening).
>
> These are removed from the worker namespace as well as rejected by the
> validator, and by **where they come from** rather than by name: a list of names
> cannot keep up with a namespace thousands deep, and `cython(get_remote_file(url))`
> was download, compile and execute in one expression. `gp('system("id")')` ran a
> shell command. Neither involved a name any rule mentioned.
>
> This section was previously inaccurate: it claimed `subprocess.*`, `pathlib.*`
> and `socket.*` were blocked when none of them were, because a rule required a
> module *and* a specific attribute name to match. Seven further bypasses were
> found and closed at the same time. It was inaccurate a second time, more
> subtly: the forbidden names were rejected only where they were *called*, so
> `f = open` followed by `f("/etc/passwd")` passed --- through the specialised
> tools as well as `evaluate_sage`. Forbidden names are now rejected wherever
> they are read, and the worker's namespace no longer contains them at all.
> The table below is covered by a test that fails if the code stops enforcing
> it, and that test now checks aliases, not just call sites.

**The rule that comes first: an allowlist.**

Caller code may read a name only if it is one this server offers --- the ~1900
mathematical names SageMath preloads, the safe builtins, and whatever the caller
defines itself (assignments, loop variables, function arguments, `var('t')`, and
anything created earlier in the same session). Everything else is refused.

That inversion is the point. Seven sandbox bypasses in two days had one shape
between them: a name nobody had thought to forbid --- `cython`, `sh`, `gp`,
`get_remote_file`, `unpickle_global`. A denylist over a namespace that size is
always one name behind. It does not retroactively catch something dangerous still
sitting in the namespace, but a helper added by a future SageMath release is
denied until someone looks at it, rather than reachable the day it lands. A test
run weekly, and on every push, fails when the two disagree.

The rules below still apply, and now serve as defence in depth behind it.

**What is blocked:**

Names in the first three rows are rejected **anywhere they are read** --- called,
assigned, aliased, defaulted into a `lambda`, placed in a list, or reached through
an attribute chain --- not only in call position. The last of those matters more
than it sounds: `sage` is an allowed import root, so
`sage.misc.sage_eval.sage_eval("...")` reached the same function that a bare
`sage_eval` could not.

| Category | Details |
|----------|---------|
| Dangerous builtins | `eval()`, `exec()`, `compile()`, `__import__()`, `open()`, `input()`, `globals()`, `locals()`, `vars()` |
| Attribute indirection | `getattr()`, `setattr()`, `delattr()` --- these defeat every attribute rule by naming the attribute at runtime |
| Runtime string evaluation | `sage_eval()`, `preparse()`, `sage_input()` --- these evaluate a string *after* the AST has been approved |
| Dunder access | Any `__dunder__` name or attribute, which blocks `().__class__.__bases__[0].__subclasses__()` and `__builtins__` |
| Sage helpers that execute or fetch | `cython()`, `cython_lambda()`, `fortran()` (compile and run code), `sh()` (runs a shell), `get_remote_file()` (downloads), `loads`/`dumps`/`save`/`db_save` (pickle is code execution) |
| External CAS interfaces | `gp`, `maxima`, `gap`, `singular`, `octave`, `magma`, `sage0` and everything else `sage.interfaces.all` exports --- each spawns the real program, and those have shell escapes of their own |
| Names that write, fetch or display | `oeis` (queries oeis.org), `install_doc`, `show`, `view`, `animate`, `html`, `latex`, `search_src`, `search_doc`, `reference`, `Profiler` --- each demonstrated a file written, a network request or the installation read. Plot tools are unaffected: they render through `.savefig(BytesIO)`, and LaTeX output imports `latex` from `sage.all` directly rather than from the caller namespace |
| Sage loaders | `load()` and `attach()` execute whatever path they are given, and `load()` accepts a URL |
| String-path attribute access | `attrgetter`, `methodcaller`, `itemgetter`, and the `operator` module that carries them. Every attribute rule here is enforced on the AST, and these take the path as a *runtime string* the AST never sees: `operator.attrgetter("misc.persist.unpickle_global")(sage)` returned the real function, which is arbitrary code execution. `getattr`, `setattr` and `vars` were already refused, which left `operator` as the only way in |
| Forbidden modules | **Every** attribute of `os`, `sys`, `subprocess`, `shutil`, `socket`, `pathlib`, `builtins`, `operator`, `warnings`, `pari`, `oeis` --- at any depth, so `sage.misc.temporary_file.os` is caught too. `pari` is the PARI *library* interface, which the external-CAS scrub missed because it comes from `sage.libs.pari`; `pari('system("id")')` ran a shell command |
| Sage sub-packages that execute | `cython`, `persist`, `remote_file`, `interfaces`, `inline_fortran`, `repl`, `package`, `temporary_file`, `attached_files`, `explain_pickle`, `edit_module`, `dev_tools`, `trace`, `sh` --- at any depth. Blocked as a *path*, so `sage.misc.trace.trace(...)` is refused and `A.trace()` is not |
| Imports | **Refused by default.** An import is how you get back a helper the worker removed, and the namespace already has Sage loaded. Two narrow exceptions change nothing reachable: an import of names already offered, and `from <module> import *` for a curated set of internal SageMath modules whose public names are all ordinary mathematics --- screened clean as a whole and generated into `star_exports.py`, with any re-exported module object dropped so it cannot become a pivot. Nothing is added to the allowlist |
| Scope manipulation | `global` and `nonlocal` statements (configurable) |
| Namespace removal | The worker's `__builtins__` omits `open`, `eval`, `exec`, `compile`, `input`, `breakpoint`, `globals`, `locals`, `vars`, `memoryview`, `help`, `exit` and `quit` outright --- a backstop for spellings the AST pass misses. `__import__` deliberately stays, because Sage imports lazily during ordinary mathematics; it is unreachable from caller code, which cannot name any dunder. |

Caller-supplied expressions passed to the specialised tools are validated as
expressions in their own right before they are embedded in generated code.
Without that, `calculate_expression("__import__('os').getuid()")` reached the
operating system, because the validator saw only a string constant.

**What is allowed:**

Everything Sage preloads --- which is the whole library. `factorial(5)`,
`integrate(sin(x), x)`, `matrix(...)`, `EllipticCurve(...)` and the rest need no
import, because the worker starts with `from sage.all import *` already done.

The import allowlist below applies **only to the snippets this server generates**.
Caller code gets a much narrower door --- the imports that would change nothing
(a name already offered, or `from <curated module> import *` expanded to its
screened names), and nothing else --- see the Imports row above:

| Import | Used by |
|--------|---------|
| `sage`, `sage.all` | The generated prelude |
| `base64`, `io` | The plot templates, for in-memory PNG encoding |
| `math`, `cmath`, `statistics` | Helper templates |

### Network exposure

**The server has no authentication.** Anyone who can reach the HTTP endpoint can
evaluate code, which is why every default here is loopback: `--host` defaults to
`127.0.0.1`, the default transport is stdio, the bundled compose file publishes
to `127.0.0.1:8314`, and the Helm service is `ClusterIP`. Putting it on a network
means putting something that authenticates in front of it.

### Container hardening

The validator narrows what caller code can express. The container is what
actually contains it, so `docker-compose.yml` sets:

| Setting | Why |
|---------|-----|
| `read_only: true` | The root filesystem is immutable. Sage needs only a writable temp dir and its own dot-directory, supplied as the two `tmpfs` mounts below; without them it fails outright, which is how they were sized. |
| `tmpfs: /tmp`, `/home/sage/.sage` | The only writable paths, in memory, capped at 512 MB and 256 MB. |
| `./:/workspace:ro` | The server runs from the package installed in the image; an escaped process should not be able to edit the checkout it reads. |
| `cap_drop: [ALL]` | No Linux capabilities are needed to do mathematics. |
| `security_opt: [no-new-privileges:true]` | Blocks privilege escalation via setuid binaries. |
| `pids_limit: 256` | A fork bomb cannot exhaust the host. |
| `mem_limit: 4g` | Neither can a runaway computation. |

An escape was measured reading all environment variables, reading the mounted
checkout and opening outbound sockets. If the server is exposed to untrusted
callers, also consider `network_mode: none` where the workload allows it, and
avoid passing secrets in the environment of this container.

The Helm chart applies `runAsNonRoot`, `allowPrivilegeEscalation: false`,
`capabilities.drop: [ALL]` and `readOnlyRootFilesystem: true`, with `emptyDir`
volumes for the same two writable paths and default CPU/memory requests and
limits. It is close but not identical: compose's `pids_limit` has no direct
chart equivalent (pod PID limits are a kubelet setting), so set one on the node
if you need it.

**Enforced limits:**

| Limit | Default | Env var |
|-------|---------|---------|
| Max source code length | 131,072 chars | `SAGEMATH_MCP_SECURITY_MAX_SOURCE` |
| Max AST node count | 50,000 | `SAGEMATH_MCP_SECURITY_MAX_AST_NODES` |
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

Exposes `http://127.0.0.1:8314/mcp`. Runs as non-root `sage` user (UID/GID 1001). The compose file mounts the repository at `/workspace` and accepts environment variable overrides for all `SAGEMATH_MCP_*` settings.

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
| `SAGEMATH_MCP_SECURITY_MAX_SOURCE` | Maximum source length in characters, measured after preparsing. | `131072` |
| `SAGEMATH_MCP_SECURITY_MAX_AST_NODES` | Maximum AST node count allowed. | `50000` |
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
make allowlist                  # Regenerate the caller allowlist from that Sage
```

`make allowlist` is needed after a SageMath upgrade or any change to what the
worker namespace contains; an integration test and a weekly job fail when the
committed allowlist and the installed Sage disagree. It writes through a
temporary file, because the generator imports the module it replaces. **Read the
diff**: every added name is a name every caller can then use, and anything that
compiles, spawns, writes or fetches belongs in `_DANGEROUS_BARE_NAMES` instead.

### Running Tests

Without a local SageMath installation you can still run the whole unit suite --- it replaces the Sage worker with a lightweight Python interpreter to validate session plumbing. Coverage is at **100%** of statements and branches, enforced in CI by `--cov-fail-under=100`; that number is checked on every run, unlike a test count written into prose.

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
│   ├── server.py                   # Entry point: /health route, main(), and the imports that register everything
│   ├── app.py                      # The FastMCP object, instructions, lifespan, middleware
│   ├── runtime.py                  # Settings and the session manager
│   ├── codegen.py                  # Prelude, literal encoding, validation gates, numeric guards
│   ├── text.py                     # Client-facing strings shared by app and tools
│   ├── tools/                      # The 37 tools and 3 resources, by domain
│   │   ├── session.py              #   6 session tools + the 3 resources
│   │   ├── core.py                 #   evaluate_sage, streaming, calculate, simplify/expand/factor, find_root
│   │   ├── calculus.py             #   differentiate, integrate, limit, series, ODEs, sums, vector calculus
│   │   ├── algebra.py              #   solve, matrices, polynomial rings, boolean algebra
│   │   ├── discrete.py             #   number theory, combinatorics, graphs, groups, curves, codes
│   │   ├── stats.py                #   statistics_summary, distribution_operation
│   │   └── plotting.py             #   2D/3D plots and geometry
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
├── docs/mcp_quickstart.md          # Client quickstart and prompt cookbook
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
| [pytest-cov](https://github.com/pytest-dev/pytest-cov) | 7.0+ | Coverage reporting (100% statement and branch coverage, gated in CI) |
| [pip-audit](https://github.com/pypa/pip-audit) | 2.9+ | Dependency vulnerability scanning |
| [Hatchling](https://hatch.pypa.io/) | 1.29+ | Build backend |
| [Docker](https://www.docker.com/) | --- | Containerization and CI integration testing |
| [Helm](https://helm.sh/) | 3.15+ | Kubernetes deployment |
| [GitHub Actions](https://github.com/features/actions) | --- | CI/CD (Node.js 24 compatible) |
| [Cosign](https://docs.sigstore.dev/cosign/) | --- | Container image signing |

---

## Changelog

Every released version, newest first. [`CHANGELOG.md`](CHANGELOG.md) carries the
full detail; this is the shape of each release.

### v0.6.1 (2026-08-16)

A security patch on 0.6.0.

**Security**

- **A critical sandbox escape in the curated `import *` feature.** The screen
  vetted each export by its `__module__`, but a module object has none, so a
  re-exported module (`sage.modular.dims` → `dirichlet`) passed and became a
  pivot into the whole `sage.*` tree; `dirichlet.free_module_element.sage.env.os.system('id')`
  ran a shell. The screen now drops module-object exports and the validator
  refuses a terminal module name under any root.
- **The monitoring resource leaked another client's inputs and outputs** — the
  free-text error, rejected-code and stdout fields are dropped from the
  process-global snapshot.

**Added**

- Caller code may `from <module> import *` for a curated set of clean internal
  SageMath modules (generated into `star_exports.py`; nothing added to the
  allowlist).
- `evaluate_sage` **auto-declares symbol-shaped free names** (`w`, `x_2`,
  `alpha`) the way SageMath's SR does, instead of refusing them — narrow and
  typo-guarded, and a session variable is never turned back into a symbol.

**Changed**

- `set_verbose` is offered as a no-op (it only sets a global verbosity level,
  which has no surface over MCP); `inject_shorthands` is simulated so its names
  are readable; a literal `attrcall('method')` is accepted after its name is
  screened. Doctest-corpus acceptance rose 98.69% → 98.95%.

**Fixed**

- The guarded `attrcall` wrapper is reinstalled after every namespace reseal; it
  had silently stopped working after the first specialised-tool call in a session.

### v0.6.0 (2026-08-15)

A security and correctness release, and the largest so far. **Output changes**,
so it is a minor bump rather than a patch: `2^3` is 8, `x`/`y`/`z`/`t` are
predefined, and callers lose imports, the external CAS interfaces and
`show`/`view`/`latex`/`html`.

**Security**

- **Caller code moved to a deny-by-default allowlist.** A name is refused unless
  SageMath preloads it, it is a safe builtin, or the caller's own code bound it.
  This replaced a denylist over a namespace thousands of names deep, after a run
  of bypasses that were each a name nobody had forbidden.
- **A series of sandbox escapes closed, each with a regression test and each
  verified against real SageMath 10.9**: string-path attribute access
  (`operator.attrgetter`, and Sage's own `attrcall`/`raw_getattr`/`getattr_debug`);
  `pari` and `latex.has_file` running shell commands; `unpickle_global`
  reachable after a tool call re-imported `sage.all`; and bindings authorizing
  names that already existed. See `CHANGELOG.md` and `REVIEW_ACTIONS.md` for the
  full list with reproductions.
- **Tool parameters refuse the names the namespace scrub removes**, and cannot
  walk the `sage` module tree — the fragment path is validated independently of
  where `sage_eval` resolves.

**Changed**

- **`evaluate_sage` runs SageMath, not Python** — the preparser is applied, so
  `2^3` is 8 and generator syntax parses.
- **`x`, `y`, `z` and `t` are predefined**, matching the specialised tools'
  prelude; any other symbol needs `var('w')`, and the error says so.

**Fixed**

- `f(x) = x^2 + 1` (the tutorial's first line), `find_root` taking an equation,
  `match` statements and `function('f')` binding names, uniformly-indented code,
  and refusal messages that now name an actionable fix.

**Added**

- Suites for the mathematics that must *work* (`test_math_coverage.py`), the
  research and physics sessions a user actually runs, and SageMath's own
  doctests executed through the server.

### v0.5.0 (2026-08-14)

A correctness and hardening release. **Output changes** for large integers, so it
is a minor bump rather than a patch.

**Security**

- Caller strings reaching `sage_eval`-enabled generated code are now validated.
  Four tool parameters (`graph_operation.graph`, `group_operation.group`,
  `coding_theory_operation.code_type`, `polynomial_ring_operation.base_ring`) were
  interpolated raw, which was demonstrated reading files, running shell commands
  and opening outbound connections.
- Forbidden names are rejected wherever they are *read*, not only where called:
  `f = open`, a `lambda` default, a list literal, and the same for modules
  (`m = os`, `from sage.all import os as m`).
- The worker namespace no longer contains `open`, `eval`, `exec`, `compile` and
  the rest of that family.

**Changed**

- Integer results at or above 2^53 are returned as decimal strings, and the same
  parameters accept them on the way in. JavaScript-based clients parse JSON
  numbers as doubles, so `bell(30)` was reaching one CLI as
  `846749014511809388871680` instead of `846749014511809332450147`.
- Matrix entries accept integers and decimal strings and stay exact; float
  matrices behave exactly as before.
- `interrupt_sage_session` reports `No running computation` when nothing is
  running instead of claiming state was preserved. Signalling an idle worker
  could leave it unable to answer, costing the namespace it was protecting.
- The container runs with a read-only root filesystem; the Helm chart gained
  `readOnlyRootFilesystem` and resource defaults.

**Fixed**

- `/health` was never registered under FastMCP 3.x and returned 404 in every HTTP
  deployment.
- `is_convex` returned true for concave and self-intersecting polygons.
- Persisted sessions that had used a specialised tool could not be restored.
- Streaming progress is bounded by both event count and characters, and a slow
  callback can no longer time out a finished evaluation.

**Internal**

- `server.py` split from 2327 lines into `app.py`, `runtime.py`, `codegen.py` and
  a `tools/` package; tool names, schemas and descriptions held identical by a
  snapshot test.
- 100% statement and branch coverage, enforced in CI. CLI suites run nightly.

### v0.4.0 (2026-08-13)

A correctness release: several tools returned wrong values or did not work at
all, so **output differs from 0.3.1**. Named workspaces
(`start_sage_session`/`list_sage_sessions`/`stop_sage_session` plus a `session`
argument), `interrupt_sage_session`, and the first exact-integer guards on
`number_theory_operation`.

### v0.3.1 (2026-04-03)

Release-pipeline fixes only, no code change: Cosign lowercases the GHCR
reference, the build installs `build` first, PyPI trusted publishing via a `pypi`
environment.

### v0.3.0 (2026-04-03)

18 tools to 33, all Sage-backed: `symbolic_sum`, `combinatorics_operation`,
`plot3d_expression`, `distribution_operation`, `find_root`,
`plot_multi_expression` and `vector_calculus_operation`.

### v0.2.0 (2026-04-03)

The first substantial release: 18 MCP tools across calculus, algebra, linear
algebra, ODEs, number theory, statistics and plotting; CLI integration suite;
FastMCP 3.x migration; Docker pinned to SageMath 10.9; Helm health probes;
Python 3.12 minimum.

### v0.1.2 (2025-11-02)

Default HTTP port aligned to 8314 across code, docs and deployment artifacts;
package published to GitHub Packages during release.

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
