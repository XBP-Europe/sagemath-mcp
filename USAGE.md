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
> Do not use it on a host: the server evaluates code and has no authentication,
> so binding every interface exposes an unauthenticated evaluator to the network.
> The bundled compose file publishes to `127.0.0.1` for the same reason.
The server advertises its MCP endpoint at `http://HOST:PORT/mcp`.

## Available Tools & Resources (37 tools, 3 resources)

All math tools use **SageMath** as the computation backend.

| Name | Backend | Description |
| --- | --- | --- |
| `evaluate_sage` | Sage | Execute arbitrary SageMath code within a persistent session; supports `timeout`, `want_latex`, `capture_stdout`. |
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
| `plot_expression` | Sage | Render a 2D plot and return a base64-encoded PNG image. |
| `plot3d_expression` | Sage | Render a 3D surface plot and return a base64-encoded PNG image. |
| `plot_multi_expression` | Sage | Overlay multiple functions in a single 2D plot. |
| `find_root` | Sage | Numeric root-finding in an interval via Sage's `find_root()`. |
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
| `start_sage_session` | Worker | Start a **named workspace** with its own independent variables. |
| `list_sage_sessions` | Worker | List the named workspaces belonging to this client. |
| `stop_sage_session` | Worker | Stop a named workspace and release its worker. |
| `resource://sagemath/session/{scope}` | Server | Inspect active sessions (`scope=all` or specific session id). |
| `resource://sagemath/monitoring/{scope}` | Server | Fetch evaluation metrics (`scope=metrics` or `all`). |
| `resource://sagemath/docs/{scope}` | Server | Retrieve SageMath documentation links (`scope=all`, `reference`, `tutorial`). |
| `/health` | Server | HTTP health check endpoint returning server status (for Kubernetes probes). |

The `resource://sagemath/docs/{scope}` resource returns links into the upstream
SageMath manual, which is the authoritative copy and always current.

Refer to [MONITORING.md](MONITORING.md) for details on exporting metrics to Prometheus or other dashboards.
For container deployments, scrape metrics from whichever service (compose or Helm) exposes
`resource://sagemath/monitoring/metrics` through your MCP client.

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
  | `show`, `view`, `latex`, `html`, `animate`, `oeis` | Write to disk, launch a viewer or reach the network. **Use the plot tools instead** — `plot_expression` and friends return a base64 PNG, which is what you want over an MCP connection anyway. |

  The specialised tools cover most of what people reach for these for.
- **`'n' is larger than 2^53`**: pass that argument as a decimal string. A JSON
  number that large is not exact, so the server refuses it rather than computing
  from a rounded value.
- **`'w' is not defined`**: `x`, `y`, `z` and `t` exist without being declared;
  anything else needs `var('w')` first, exactly as in the Sage REPL. The error
  says so and names the declaration to write.
- **Indented code is fine.** A snippet pasted out of a markdown block with four
  spaces on every line used to fail as a syntax error; the shared indentation is
  now stripped before anything else happens.
- **Permission denied on volume mounts**: the checkout is mounted read-only on purpose, so a write failure there is usually the application trying to write where it should not. If the path really is meant to be writable (a persistence volume), give that single path to UID/GID 1001 — not the whole tree.
