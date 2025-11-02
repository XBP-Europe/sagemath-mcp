# SageMath MCP Server Usage Guide

## Prerequisites
- Python 3.11+ with [uv](https://docs.astral.sh/uv/) installed (`curl -LsSf https://astral.sh/uv/install.sh | sh`).
- A working SageMath installation. The reference environment uses Docker:  
  ```bash
  docker pull sagemath/sagemath:latest
  docker run --name sage-mcp -d -v "$PWD":/workspace -w /workspace sagemath/sagemath:latest tail -f /dev/null
  ```
- Alternatively, run `make sage-container` (or `./scripts/setup_sage_container.sh`) to pull and launch
  the Docker image automatically.
- Optional: `sage` on your `PATH` if running outside Docker.
- `docker compose up --build` launches the bundled stack on `http://127.0.0.1:31415/mcp` using the
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
uv run sagemath-mcp -- --transport streamable-http --host 127.0.0.1 --port 31415
```
Inside Docker, prefer running through Sage to inherit the full runtime:
```bash
sage -python -m uv run sagemath-mcp -- --transport streamable-http --host 0.0.0.0 --port 31415
```
The server advertises its MCP endpoint at `http://HOST:PORT/mcp`.

## Available Tools & Resources
| Name | Type | Description |
| --- | --- | --- |
| `evaluate_sage` | tool | Execute SageMath code within a persistent session; supports `timeout`, `want_latex`, `capture_stdout`. |
| `calculate_expression` | tool | Evaluate a Sage expression and return string/numeric results. |
| `solve_equation` / `differentiate_expression` / `integrate_expression` | tools | Algebra/calculus helpers built on Sage. |
| `statistics_summary` | tool | Compute population & sample mean/variance/std-dev plus min/max. |
| `matrix_multiply` | tool | Multiply matrices (nested list input) and return the product. |
| `cancel_sage_session` | tool | Coop-cancel the active computation and restart the underlying worker. |
| `reset_sage_session` | tool | Clear the session state without cancelling a running job. |
| `resource://sagemath/session/{scope}` | resource | Inspect active sessions (`scope=all` or specific session id). |
| `resource://sagemath/monitoring/{scope}` | resource | Fetch evaluation metrics (`scope=metrics` or `all`). |
| `resource://sagemath/docs/{scope}` | resource | Retrieve SageMath documentation links (`scope=all`, `reference`, `tutorial`). |

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

When running via Docker Compose, the same script can target `http://127.0.0.1:31415/mcp`. Under Helm,
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
