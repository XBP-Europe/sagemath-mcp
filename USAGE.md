# SageMath MCP Server Usage Guide

## Prerequisites
- Python 3.12+ with [uv](https://docs.astral.sh/uv/) installed (`curl -LsSf https://astral.sh/uv/install.sh | sh`).
- A working SageMath installation. The reference environment uses Docker:  
  ```bash
  docker pull sagemath/sagemath:latest
  docker run --name sage-mcp -d -v "$PWD":/workspace -w /workspace sagemath/sagemath:latest tail -f /dev/null
  ```
- Alternatively, run `make sage-container` (or `./scripts/setup_sage_container.sh`) to pull and launch
  the Docker image automatically.
- Optional: `sage` on your `PATH` if running outside Docker.
- `docker compose up --build` launches the bundled stack on `http://127.0.0.1:8314/mcp` using the
  non-root `sage` user (UID/GID 1000); ensure the mounted project directory is writable by that UID.
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
The server advertises its MCP endpoint at `http://HOST:PORT/mcp`.

## Available Tools & Resources (33 tools, 3 resources)

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
| `cancel_sage_session` | Worker | Cancel the active computation and restart the underlying worker. |
| `reset_sage_session` | Worker | Clear the session state without cancelling a running job. |
| `resource://sagemath/session/{scope}` | Server | Inspect active sessions (`scope=all` or specific session id). |
| `resource://sagemath/monitoring/{scope}` | Server | Fetch evaluation metrics (`scope=metrics` or `all`). |
| `resource://sagemath/docs/{scope}` | Server | Retrieve SageMath documentation links (`scope=all`, `reference`, `tutorial`). |
| `/health` | Server | HTTP health check endpoint returning server status (for Kubernetes probes). |

The repo ships a curated subset of the Sage reference manual (index, search, plotting/plot3d,
calculus, rings, statistics) in `docs/reference_md/`, suitable for in-context prompting.

Refer to [MONITORING.md](MONITORING.md) for details on exporting metrics to Prometheus or other dashboards.
For container deployments, scrape metrics from whichever service (compose or Helm) exposes
`resource://sagemath/monitoring/metrics` through your MCP client.

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
- **Long-running jobs**: use `cancel_sage_session`; the server restarts the worker and logs a warning for the calling context.
- **Idle sessions**: the background culler removes sessions after `SAGEMATH_MCP_IDLE_TTL` seconds (default 900). Adjust via environment variables as documented in `README.md`.
- **Permission denied on volume mounts**: confirm the host path is writable by UID/GID 1000; adjust ownership with `chown -R 1000:1000 <path>` when using Docker Compose or Helm.
