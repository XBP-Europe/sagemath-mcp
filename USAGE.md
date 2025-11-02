# SageMath MCP Server Usage Guide

## Prerequisites
- Python 3.11+ with [uv](https://docs.astral.sh/uv/) installed (`curl -LsSf https://astral.sh/uv/install.sh | sh`).
- A working SageMath installation. The reference environment uses Docker:  
  ```bash
  docker pull sagemath/sagemath:latest
  docker run --name sage-mcp -d -v "$PWD":/workspace -w /workspace sagemath/sagemath:latest tail -f /dev/null
  ```
- Optional: `sage` on your `PATH` if running outside Docker.

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
