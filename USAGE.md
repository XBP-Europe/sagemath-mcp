# SageMath MCP Server Usage Guide

## Prerequisites
- Python 3.12+ with [uv](https://docs.astral.sh/uv/) installed (`curl -LsSf https://astral.sh/uv/install.sh | sh`).
- A working SageMath installation. The reference environment uses Docker:  
  ```bash
  docker pull sagemath/sagemath:10.9
  docker run --name sage-mcp -d -v "$PWD":/workspace -w /workspace sagemath/sagemath:10.9 tail -f /dev/null
  ```
  Pin the version rather than taking `:latest`. The set of names callers may use
  is generated from a specific SageMath and baked into the package, so a
  different release can offer names this build does not admit. A scheduled job
  and an integration test both fail when the two disagree.
- Alternatively, run `make sage-container` (or `./scripts/setup_sage_container.sh`) to pull and launch
  the Docker image automatically.
- Optional: `sage` on your `PATH` if running outside Docker.
- `docker compose up --build` (or `docker-compose up --build` on Compose v1) launches the bundled stack on `http://127.0.0.1:8314/mcp` using the
  non-root `sage` user (UID/GID 1001); ensure the mounted project directory is writable by that UID.
- To deploy to Kubernetes, use the Helm chart in `charts/sagemath-mcp` and set
  `image.repository`/`image.tag` to the published container (non-root execution is enforced by default).

## Installing Dependencies
Inside the repo (or inside the container):
```bash
uv pip install -e .[cli]
```
This installs the MCP server along with the `mcp` CLI helpers.

## Running the Server
### StdIO Transport (local development)
```bash
uv run sagemath-mcp
```
This exposes the server over stdio and is suitable for tools like Claude Desktop configured with `"command": "uv", "args": ["run", "sagemath-mcp"]`.

### HTTP / Streamable Transport (recommended for streaming + cancellation)
```bash
uv run sagemath-mcp --transport streamable-http --host 127.0.0.1 --port 8314
```
Inside Docker, prefer running through Sage to inherit the full runtime:
```bash
sage -python -m uv run sagemath-mcp --transport streamable-http --host 0.0.0.0 --port 8314
```
> `--host 0.0.0.0` is correct **inside a container**, where it means "listen on
> the container's interfaces" and the published port decides who can reach it.
> Do not use it on a host: the server evaluates code and has no authentication
> by default, so binding every interface exposes an unauthenticated evaluator to
> the network. The bundled compose file publishes to `127.0.0.1` for the same
> reason.
The server advertises its MCP endpoint at `http://HOST:PORT/mcp`.

#### Optional bearer-token authentication

No auth is the deliberate default (the container is the boundary — see
[SECURITY.md](SECURITY.md)). If you front the HTTP endpoint on a network, set a
shared secret and every MCP request must then present it:

```bash
export SAGEMATH_MCP_HTTP_AUTH_TOKEN="$(openssl rand -hex 32)"
uv run sagemath-mcp --transport streamable-http --host 0.0.0.0 --port 8314
# clients send:  Authorization: Bearer <that token>
```

The token is compared in constant time and never logged. The `/health` and
`/ready` probes stay open so a load balancer can reach them. It is a single
shared secret — an API key, not an OAuth server, and not a substitute for the
container boundary or TLS. Leave `SAGEMATH_MCP_HTTP_AUTH_TOKEN` unset to keep the
endpoint open; the server logs a warning if it binds a non-loopback host with no
token.

## Available Tools & Resources (40 tools, 3 resources)

All math tools use **SageMath** as the computation backend.

| Name | Backend | Description |
| --- | --- | --- |
| `evaluate_sage` | Sage | Execute SageMath code (the sandbox's mathematical subset) within a persistent session; supports `timeout`, `want_latex`, `capture_stdout`. Specialized tools evaluate in a fresh namespace, so multi-step work that reuses variables belongs here. |
| `evaluate_sage_streaming` | Sage | Like `evaluate_sage` but emits each stdout line as a progress event for real-time display. |
| `calculate_expression` | Sage | Evaluate a Sage expression and return string/numeric results. |
| `solve_equation` | Sage | Solve a single equation or a system of equations for one or more variables. |
| `differentiate_expression` | Sage | Symbolic differentiation of any order (set `order` for higher-order derivatives). |
| `integrate_expression` | Sage | Indefinite or definite integration (pass `lower_bound`/`upper_bound` for definite integrals). |
| `simplify_expression` | Sage | Simplify a mathematical expression via Sage's `simplify()`. |
| `expand_expression` | Sage | Expand products, powers, and identities in an expression. |
| `factor_expression` | Sage | Factor a symbolic expression or integer. |
| `limit_expression` | Sage | Compute limits with optional one-sided direction (`plus`/`minus`). |
| `series_expansion` | Sage | Taylor / Laurent series expansion around a point with configurable order. |
| `symbolic_sum` | Sage | Symbolic summation and products (finite and infinite series). |
| `matrix_multiply` | Sage | Multiply two matrices (nested list input) and return the product. |
| `matrix_operation` | Sage | Determinant, inverse, eigenvalues, rank, RREF, or transpose of a matrix. |
| `solve_ode` | Sage | Solve ordinary differential equations via Sage's `desolve()`. |
| `number_theory_operation` | Sage | Primality testing, integer factoring, next prime, GCD, LCM. |
| `combinatorics_operation` | Sage | Binomial, permutations, combinations, partitions, factorial, Catalan, Fibonacci, Bell. |
| `statistics_summary` | Sage | Compute population & sample mean/variance/std-dev plus min/max. |
| `distribution_operation` | Sage | Probability distributions: normal, exponential, Poisson, chi-squared, Student-t, uniform, beta, gamma. |
| `plot_expression` | Sage | Render a 2D plot and return it as MCP image content (PNG or SVG via `image_format`) the client displays inline. |
| `plot3d_expression` | Sage | Render a 3D surface plot and return it as MCP image content the client displays inline. |
| `plot_multi_expression` | Sage | Overlay multiple functions in a single 2D plot. |
| `find_root` | Sage | Numeric root-finding in an interval via Sage's `find_root()`. Accepts an expression or an equation (`E - 0.6*sin(E) = 0.75`). |
| `verify_claim` | Sage | Independently re-check a stated claim (`sin(x)^2 + cos(x)^2 == 1`) through a proof ladder: symbolic prover, exact difference, exact algebraic arithmetic, certified intervals, numeric sampling. Answers `proved`, `refuted`, `supported` or `undecided`, always with its evidence. |
| `vector_calculus_operation` | Sage | Gradient, divergence, curl, Laplacian on scalar/vector fields. |
| `graph_operation` | Sage | Named graphs and adjacency dicts; chromatic number, connectivity, planarity, diameter, shortest path. |
| `group_operation` | Sage | Symmetric, dihedral, cyclic, alternating groups; order, abelian/cyclic test, center, exponent. |
| `elliptic_curve_operation` | Sage | Rank, torsion, discriminant, j-invariant, conductor, generators. |
| `coding_theory_operation` | Sage | Hamming, Reed-Solomon codes; length, dimension, minimum distance, generator matrix, rate. |
| `boolean_algebra_operation` | Sage | Boolean polynomial ring; evaluate, variables, degree, zero/one test. |
| `polynomial_ring_operation` | Sage | Groebner bases, ideal dimension/variety, reduction, Groebner test. |
| `geometry_operation` | Sage | Distance, polygon area, polytope volume, convex hull, compactness via `Polyhedron`. |
| `interrupt_sage_session` | Worker | Interrupt a running computation **and keep the variables defined so far**. Prefer this over cancelling. |
| `cancel_sage_session` | Worker | Cancel the active computation and restart the underlying worker, discarding its variables. |
| `reset_sage_session` | Worker | Clear the session state without cancelling a running job. |
| `start_sage_session` | Worker | Start a **named workspace** with its own independent variables, and return a portable `workspace_token`: an unguessable bearer handle that reaches the same workspace across reconnects when passed as `session`. Keep it secret. |
| `list_sage_sessions` | Worker | List the named workspaces belonging to this client. |
| `stop_sage_session` | Worker | Stop a named workspace and release its worker. |
| `check_sage_health` | Worker | Probe readiness: spins up (or reuses) the workspace worker, evaluates `1+1`, reports `ok`/latency instead of erroring. |
| `lookup_sage_doc` | Server | Documentation links for a SageMath name, plus whether this server offers it to caller code. |
| `resource://sagemath/session/{scope}` | Server | Inspect active sessions (`scope=all` or specific session id). |
| `resource://sagemath/monitoring/{scope}` | Server | Fetch evaluation metrics (`scope=metrics` or `all`). |
| `resource://sagemath/docs/{scope}` | Server | Retrieve SageMath documentation links (`scope=all`, `reference`, `tutorial`). |
| `/health` | Server | HTTP liveness endpoint: 200 while the process is up and answering. Deliberately shallow — does not touch a Sage worker, so a busy backend does not restart the pod. |
| `/ready` | Server | HTTP readiness endpoint: evaluates `1+1` on the backend and returns 200 only when it computes correctly, 503 otherwise. This is the probe a Service should gate traffic on. |

The `resource://sagemath/docs/{scope}` resource returns links into the upstream
SageMath manual, which is the authoritative copy and always current.

Refer to [MONITORING.md](MONITORING.md) for details on exporting metrics to Prometheus or other dashboards.
For container deployments, scrape metrics from whichever service (compose or Helm) exposes
`resource://sagemath/monitoring/metrics` through your MCP client.

## Tool reference

Every tool's parameters and behaviour, grouped by domain. The table above is
the index; this is the detail. `evaluate_sage` is first because it is the one
that carries session state.

### `evaluate_sage` --- Open-Ended SageMath Execution

Executes SageMath code — the mathematical subset the sandbox permits (see [Security Sandbox](#security-sandbox)) — inside a persistent worker process. Variables, functions, classes, and assumptions defined in one call survive into subsequent calls within the same MCP session.

Its own tool description calls it a **LAST RESORT**, and for a single self-contained calculation a specialized tool is better: it validates arguments and returns a typed result. But that steer has one important exception. The specialized tools evaluate their input in a **fresh namespace** and cannot see variables you assigned with `evaluate_sage` — so any workflow that builds an object once and then explores it (a graph and its invariants, a number field, a polynomial ideal, a matrix decomposition) belongs in `evaluate_sage`, across as many calls as it takes. Persistent state is the reason to reach for it, not a reason to avoid it.

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

Render a 2D plot of an expression and return it as MCP image content (PNG by default, or SVG via `image_format`) the client displays inline. Calls Sage's `plot()`, renders to an in-memory buffer at a bounded size, and returns it as an image block rather than a base64 string.

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

## How Code Is Interpreted

`evaluate_sage` runs your code through Sage's preparser, exactly as the Sage REPL
does, so it is Sage that you are writing and not Python:

| You send | You get | Note |
|----------|---------|------|
| `2^3` | `8` | `^` is exponentiation. `^^` is XOR |
| `type(2)` | `sage.rings.integer.Integer` | not a machine `int` |
| `K.<a> = NumberField(x^3 - 2)` | works | preparser-only syntax |
| `x`, `y`, `z`, `t` | symbolic | predefined. The REPL gives you only `x`; the tools have always declared four, so caller code does too |

Integers at or above 2^53 travel as **decimal strings** in both directions,
because a JSON number that large has already been rounded by a JavaScript-based
client before the server sees it:

```json
{"operation": "bell", "n": 30}  ->  {"result": "846749014511809332450147"}
```

Interrupting is not cancelling. `interrupt_sage_session` abandons the running
computation and keeps every variable; `cancel_sage_session` restarts the worker
and discards them. Prefer the first.

### Worked example: general relativity through `evaluate_sage`

There is no dedicated tensor tool — deliberately, see ROADMAP.md — because the
whole SageManifolds workflow passes the policy as ordinary `evaluate_sage`
calls, including the preparser-only chart syntax. Curvature of the hyperbolic
plane (the 2D Anti-de Sitter analogue), one call:

```python
H = Manifold(2, 'H', structure='Riemannian')
X.<p,q> = H.chart('p q:(0,+oo)')
g = H.metric('g')
g[0,0] = 1/q^2
g[1,1] = 1/q^2
g.ricci_scalar().expr()   # -> -2, constant negative curvature
```

Lorentzian signatures (`structure='Lorentzian'`), the metric catalog
(`manifolds.Sphere(2).induced_metric()`), Ricci and Riemann tensors and
connections all work the same way; the session keeps the manifold alive across
calls, so the metric can be defined once and interrogated repeatedly.
`tests/test_use_cases.py::test_use_cases_cover_the_sympy_mcp_showcase` pins
this workflow against a real Sage runtime.

## Sage semantics and number handling

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

**Portable workspace handles.** `start_sage_session` also returns a
`workspace_token` — a server-issued, unguessable handle that addresses that one
workspace:

```
> start_sage_session(name="curves")
  {"message": "Session 'curves' ready", "name": "curves",
   "workspace_token": "wsk_9f3c…"}          # keep this secret

> evaluate_sage(code="E.rank()", session="wsk_9f3c…")   # reaches 'curves'
```

A plain `name` is scoped to your current MCP session, so it is lost if the
transport hands you a new session id (a reconnect, or a transport that rotates
the id per call). A handle is not: passed as the `session` argument it reaches
the same workspace regardless of the transport id, which is what keeps state
across a reconnect. It is a **bearer credential**, not authentication — it
identifies no one, and anyone who holds it can reach that workspace — so treat
it as a secret. An unknown or revoked handle is refused, never silently turned
into a fresh workspace, and stopping a workspace invalidates its handles. The
handle keeps its workspace only while that worker is alive (a server restart or
an idle cull ends it); it is not a cross-restart recovery token.

#### `check_sage_health`

The MCP-level readiness probe, for stdio clients that cannot reach the HTTP
`/ready` route. It exercises the real path -- worker spawn, protocol round
trip, evaluation of `1+1` -- and reports failure in its result rather than
erroring, so an agent can always call it before committing to a workflow.

**Returns:** `{"ok": true, "backend": "sagemath", "elapsed_ms": 412.3, "session": "default"}`

#### `lookup_sage_doc`

Documentation links for one SageMath name, plus the half the upstream manual
cannot answer: whether *this server* offers the name to `evaluate_sage` caller
code. Caller code is deny-by-default, so a name Sage documents may still be
withheld here; saying so up front saves the model a refused evaluation.

**Returns:** `{"symbol": "EllipticCurve", "offered_to_caller_code": true, "links": {...}, "note": "..."}`

#### `verify_claim`

The checking primitive for the dominant failure mode of models doing
mathematics: confident wrong algebra. The model states a claim -- an equality,
an inequality, anything that evaluates to True/False -- and the server
re-checks it independently through a ladder: Sage's symbolic prover, the exact
difference (`(lhs-rhs).simplify_full().is_zero()`), exact arithmetic over
`QQbar`/`AA` when the claim is constant, then certified interval arithmetic and
numeric sampling over the free variables.

```
> verify_claim(claim="integral(x^2/(e^x-1), x, 0, oo) == 2*zeta(3)")
  {"verdict": "proved", "method": "symbolic_prover", ...}

> verify_claim(claim="log(640320^3 + 744)/sqrt(163) == pi", precision_bits=256)
  {"verdict": "refuted", "method": "certified_interval",
   "evidence": "lhs - rhs lies in ..., a certified enclosure at 256 bits that excludes zero"}
```

Two rules keep the verdicts honest. The prover returning `False` means *not
proved*, never *false* -- `refuted` requires an exact decision or an exhibited
counterexample (interval evidence is always a certified enclosure, not a
floating-point comparison). And `supported` always carries its evidence --
sample count and precision -- never a bare confidence number.

Exactness is never assumed. Decimal literals are read as the exact rationals
they denote -- `0.1` means 1/10, so `0.1 + 0.2 == 0.3` is proved and
`1.0 + 1e-20 == 1.0` is refuted, where deciding over 53-bit doubles would answer
both wrongly while claiming exactness. But a comparison whose operands are
genuine machine floats (`RR(1)`, an `.n()` result, a session value in `RR`) is
reported as `supported` "over inexact machine numbers", never as an exact proof
-- `RR(1) + RR(1)/10^20 == RR(1)` is true only by rounding, and saying `proved`
there would be the false certainty this tool exists to prevent. And the
session's active assumptions are honored, domain declarations included: under
`assume(x, 'integer')` a sampled point of 1/2 is not admissible, so it is never
offered as a counterexample to `x != 1/2`; any verdict that leaned on an
assumption names it in the evidence.

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

## Security model

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

## Verifying the Server
### Automated Tests & Lint
```bash
uv run pytest
uv run ruff check
```

### Manual Workflow
With the HTTP server running:
```bash
sage -python scripts/exercise_mcp.py
```
This script performs an assignment, a dependent evaluation, launches a long-running loop (emitting progress every 1.5 seconds), and cancels it using `cancel_sage_session`.

When running via Docker Compose, the same script can target `http://127.0.0.1:8314/mcp`. Under Helm,
use `kubectl port-forward` (see chart `NOTES.txt`) or expose an ingress to reach the MCP endpoint.

## Integrating with MCP Clients
Sample Claude Desktop snippet:
```json
{
  "mcpServers": {
    "sagemath": {
      "command": "uv",
      "args": ["run", "sagemath-mcp"],
      "transport": "stdio"
    }
  }
}
```
For HTTP transports, point the client at `http://HOST:PORT/mcp` and enable streaming to receive progress heartbeats.

## Troubleshooting Tips
- **ModuleNotFoundError for `sage`**: ensure the server is launched via `sage -python ...` so Sage’s site-packages are on `PYTHONPATH`.
- **Long-running jobs**: use `interrupt_sage_session` first — it stops the computation and keeps your variables. `cancel_sage_session` also works but restarts the worker, so everything defined in that session is gone.
- **Idle sessions**: the background culler removes sessions after `SAGEMATH_MCP_IDLE_TTL` seconds (default 900). Adjust via environment variables as documented in `README.md`.
- **`SecurityViolation` on ordinary-looking code**: caller code is checked
  against an **allowlist**, so the question is not "is this name forbidden" but
  "is this name offered". You get the mathematical names SageMath preloads, the
  safe builtins, and whatever your own code defines — including names bound
  earlier in the same session. Anything else is refused, including a helper a
  future SageMath adds, until someone reviews it.

  What that rules out in practice:

  | Refused | Why, and what to do instead |
  |---|---|
  | `import` of anything | The names are already there without it. Drop the import. |
  | `eval`, `exec`, `compile`, `getattr`, `setattr`, `vars` | Each has executed code in testing. |
  | `attrgetter`, `methodcaller`, `itemgetter`, `operator.*` | They fetch attributes by a runtime string, which defeats every other rule here. |
  | `gp`, `maxima`, `singular`, `pari`, … | Each spawns the real program, and those have shell escapes: `pari('system("id")')` ran one. |
  | `cython()`, `sh()`, `load()`, `attach()`, `save`/`dump`/`export` | Compile, run a shell, execute a path, or write files. |
  | `show`, `view`, `latex`, `html`, `animate`, `oeis` | Write to disk, launch a viewer or reach the network. **Use the plot tools instead** — `plot_expression` and friends return rendered MCP image content (PNG or SVG) the client displays, which is what you want over an MCP connection anyway. |

  The specialised tools cover most of what people reach for these for.
- **`'n' is larger than 2^53`**: pass that argument as a decimal string. A JSON
  number that large is not exact, so the server refuses it rather than computing
  from a rounded value.
- **`'w' is not defined`**: in `evaluate_sage`, `x`, `y`, `z` and `t` exist
  without being declared and anything else needs `var('w')` first, exactly as in
  the Sage REPL — `w + 1` as code is a `NameError` there too. The error says so
  and names the declaration to write. The specialised tools do not need it: they
  take an expression as a string, which is `SR`'s contract, and declare a
  symbol-shaped name on sight (`a`, `x_2`, `alpha`, `α`, `Ω`). A name that is
  not symbol-shaped stays an error, so a typo like `sinn(3)` is reported rather
  than quietly turned into a symbol.
- **Indented code is fine.** A snippet pasted out of a markdown block with four
  spaces on every line used to fail as a syntax error; the shared indentation is
  now stripped before anything else happens.
- **Permission denied on volume mounts**: the checkout is mounted read-only on purpose, so a write failure there is usually the application trying to write where it should not. If the path really is meant to be writable (a persistence volume), give that single path to UID/GID 1001 — not the whole tree.
