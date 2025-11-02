# SageMath MCP Server

[![CI](https://github.com/csteinl/sagemath-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/csteinl/sagemath-mcp/actions/workflows/ci.yml)

A Model Context Protocol (MCP) server that exposes stateful [SageMath](https://www.sagemath.org/) computations to LLM clients. The server uses [FastMCP](https://gofastmcp.com/) as the transport layer and maintains a dedicated SageMath session for each MCP conversation so variables, functions, and assumptions persist across tool calls.

## LLM Usage Notes

Clients connecting through MCP receive the following guidance:

- **Stateful sessions** — every conversation owns a dedicated Sage worker. Define symbols once
  (e.g., `var('x')`, `f = ...`) and reuse them across subsequent tool calls.
- **Core toolset** — use `evaluate_sage` for arbitrary Sage code, or reach for helpers like
  `calculate_expression`, `solve_equation`, `differentiate_expression`, `integrate_expression`,
  `matrix_multiply`, and `statistics_summary` for structured JSON outputs.
- **Runtime feedback** — long computations emit heartbeat progress events roughly every 1.5 seconds;
  the optional `timeout` parameter lets you extend or shorten the wait.
- **Session control** — `reset_sage_session` clears state while `cancel_sage_session` restarts the
  worker. Monitoring data (success/failure counts, latency, security violations) is available via
  `resource://sagemath/monitoring/metrics`.
- **Security sandbox** — the AST validator blocks arbitrary imports, `eval`/`exec`, filesystem/process
  calls, and other unsafe constructs. Prefer Sage primitives; if a violation occurs, rewrite the
  workflow using supported APIs.

## Features

- Stateful SageMath execution with per-session variable scope.
- Automatic LaTeX string generation for expression results (configurable per call).
- Support for capturing `stdout` output from Sage code.
- Tools for evaluating Sage code, cancelling long-running jobs, and resetting the session.
- Optional resource exposing the active workspace summary (with idle timers) to clients.
- Higher-level helpers for common math tasks (calculation, equation solving, calculus, statistics, matrices).
- Fully type-annotated package (`py.typed`) plus Ruff/pytest integration for CI.

## Requirements

- Python 3.11+
- A local SageMath installation available on the `PATH` (tested with Sage 10.x).
- FastMCP-compatible MCP client (e.g. Claude Desktop).

## Quick Start

### Install from PyPI

```bash
pip install sagemath-mcp

# Run the server over stdio (default)
sagemath-mcp

# Or expose an HTTP endpoint
sagemath-mcp -- --transport streamable-http --host 127.0.0.1 --port 31415
```

If the command is not on your `PATH`, run `python -m sagemath_mcp.server -- --help`.

### Develop from source

```bash
# Install dependencies (use uv or pip)
uv pip install -e .[cli]

# Run the server over stdio (default)
uv run sagemath-mcp

# Run with streaming-friendly HTTP transport
uv run sagemath-mcp -- --transport streamable-http --host 127.0.0.1 --port 31415
```

See [INSTALLATION.md](INSTALLATION.md) for Windows/macOS tooling tips, Docker notes,
and guidance on installing Sage locally.

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
docker run -p 31415:31415 sagemath-mcp:latest --transport streamable-http
```

This pulls the `sagemath/sagemath:latest` image (overridable via
`SAGEMATH_MCP_DOCKER_IMAGE`) and launches a long-lived container named `sage-mcp`
mounting the current repository at `/workspace`.

### Docker Compose

To bootstrap a local SageMath MCP stack with a single command, use the provided
`docker-compose.yml`:

```bash
docker compose up --build
```

The compose service exposes port `31415` by default and mounts the repository at
`/workspace`. Containers run as the non-root `sage` user (UID/GID 1000) to match the
base image. Tweak runtime settings by editing the environment block (for example,
increase `SAGEMATH_MCP_EVAL_TIMEOUT` or adjust `SAGEMATH_MCP_MAX_STDOUT`) before launch.
If your checkout directory is not writable by UID/GID 1000, run `chown -R 1000:1000 .`
or point the volume at a suitable path before bringing the stack up.

### Kubernetes (Helm)

The `charts/sagemath-mcp` Helm chart deploys the MCP server to Kubernetes. To install
directly from this repository:

```bash
helm install sagemath charts/sagemath-mcp \
--set image.repository=sagemath/sagemath-mcp \
--set image.tag=latest
```

Key values:

- `service.port` / `service.targetPort`: external and container ports (defaults map HTTP → 31415).
- `env`: map of environment overrides for `SageSettings` (e.g., `SAGEMATH_MCP_EVAL_TIMEOUT`).
- `args`: optional CLI arguments appended after the entrypoint (e.g., `--transport http`).
- `ingress.*`: enable and configure HTTP ingress resources.

Review `values.yaml` for the full list of configurable knobs, including pull secrets, resource limits,
and volume mounts. The chart enforces non-root execution (`runAsUser`/`runAsGroup` 1000, dropped
capabilities) so the packaged image must support the `sage` user.
Once the GHCR publish workflow lands, update `values.yaml` with the official `image.repository`
default to mirror CI output (current value is a placeholder).

To connect from Claude Desktop, add the following configuration snippet to `claude_desktop_config.json`:

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

## Usage

The server exposes several tools and resources:

1. `evaluate_sage`: Execute SageMath code with persistent state. Returns the result, captured stdout, and optional LaTeX. While code runs the server emits progress heartbeats, and request cancellations restart the worker safely.
2. `calculate_expression`: Evaluate a Sage expression and receive string/numeric forms.
3. `solve_equation`, `differentiate_expression`, `integrate_expression`: Convenience wrappers for algebra and calculus workflows.
4. `statistics_summary`: Produce population/sample mean, variance, and standard deviation for numeric datasets.
5. `matrix_multiply`: Multiply matrices and return the product as nested lists.
6. `cancel_sage_session` / `reset_sage_session`: Manage the current session state.
7. `resource://sagemath/session/{scope}`: Inspect active sessions and their idle timers.
8. `resource://sagemath/monitoring/{scope}`: Retrieve evaluation metrics (success/failure counts, latency stats, security violations) with `scope = "metrics"` or `"all"`.
9. `resource://sagemath/docs/{scope}`: Retrieve documentation links such as the [SageMath reference manual](https://doc.sagemath.org/html/en/reference) (`scope = "all"` for every link).

Lightweight Markdown exports covering the landing page, search index, plotting (2D/3D), calculus,
rings, and statistics live under `docs/reference_md/` for quick client-side lookups. See
[docs/mcp_quickstart.md](docs/mcp_quickstart.md) for JSON prompt examples and MCP usage patterns.

See [MONITORING.md](MONITORING.md) for guidance on scraping the metrics resource and wiring it into dashboards.
See [INSTALLATION.md](INSTALLATION.md) for platform-specific setup notes.

### Using with Codex CLI
Codex CLI can connect over stdio:

```bash
codex mcp add sagemath \
  --command uv \
  --args "run" "sagemath-mcp"
```

For streaming progress, expose the HTTP endpoint first:

```bash
sage -python -m uv run sagemath-mcp -- --transport streamable-http --host 0.0.0.0 --port 31415
codex mcp add sagemath-http --url http://127.0.0.1:31415/mcp
```

### Using with `gemini_cli`

```bash
gemini_cli mcp add sagemath \
  --transport stdio \
  --command uv \
  --arg run \
  --arg sagemath-mcp
```

Or point to the HTTP transport:

```bash
gemini_cli mcp add sagemath-http --transport http --url http://127.0.0.1:31415/mcp
```

### Using with `qwen_cli`

```bash
qwen_cli mcp add sagemath \
  --command uv \
  --args "run" "sagemath-mcp"
```

If you prefer HTTP:

```bash
qwen_cli mcp add sagemath-http \
  --url http://127.0.0.1:31415/mcp \
  --transport http
```

In all cases, restart the CLI session after adding the MCP server so the new tools and resources are discovered.

### Example interaction

```
> evaluate_sage({"code": "a = var('a'); f = (a + 1)^5"})
→ {"result": null, "stdout": "", "result_type": "statement"}

> evaluate_sage({"code": "expand(f)"})
→ {"result": "a^5 + 5*a^4 + 10*a^3 + 10*a^2 + 5*a + 1", "latex": "a^{5} + 5 a^{4} + 10 a^{3} + 10 a^{2} + 5 a + 1"}

> cancel_sage_session({})
→ {"message": "Session cancelled and restarted"}

> reset_sage_session({})
→ {"message": "Session cleared"}
```

## Configuration

Environment variables influence runtime behavior:

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
| `SAGEMATH_MCP_SECURITY_ENABLED` | Enable/disable AST-based code validation. | `true` |
| `SAGEMATH_MCP_SECURITY_MAX_SOURCE` | Maximum source length in characters. | `8000` |
| `SAGEMATH_MCP_SECURITY_MAX_AST_NODES` | Maximum AST node count allowed. | `2500` |
| `SAGEMATH_MCP_SECURITY_MAX_AST_DEPTH` | Maximum AST depth allowed. | `75` |
| `SAGEMATH_MCP_SECURITY_ALLOW_IMPORTS` | Permit `import` statements when set to `true`. | `false` |
| `SAGEMATH_MCP_SECURITY_FORBID_GLOBAL` | Block `global` statements when `true`. | `true` |
| `SAGEMATH_MCP_SECURITY_FORBID_NONLOCAL` | Block `nonlocal` statements when `true`. | `true` |
| `SAGEMATH_MCP_SECURITY_LOG_VIOLATIONS` | Emit warnings when code is blocked. | `true` |
| `SAGEMATH_MCP_SECURITY_ALLOWED_IMPORTS` | Comma-separated allowlist of exact module names permitted in imports. | `math,cmath,sage,sage.all` |
| `SAGEMATH_MCP_SECURITY_ALLOWED_IMPORT_PREFIXES` | Comma-separated prefixes treated as safe import namespaces. | `sage.` |

## Development

```bash
uv pip install -e .[dev]
make lint
make test
make integration-test  # requires running sage-mcp Docker container
make build
uv run python scripts/build_release.py  # build documented sdist/wheel into dist/

# Publish a release
git tag vX.Y.Z && git push origin vX.Y.Z
(GitHub Actions will build wheels/sdist and publish to PyPI.)
```

> GitHub Actions runs `make lint`, `make test`, `make integration-test`, and `make build` on every push/pull request. Run `make integration-test` locally once the `sage-mcp` container is available.

Without a local SageMath installation you can still run unit tests—the test suite replaces the Sage worker with a lightweight Python interpreter to validate session plumbing.

## Project Layout

```
sagemath-mcp/
├── pyproject.toml
├── README.md
├── src/
│   └── sagemath_mcp/
│       ├── __init__.py
│       ├── config.py
│       ├── models.py
│       ├── server.py
│       ├── session.py
│       ├── _sage_worker.py
│       └── py.typed
└── tests/
    ├── __init__.py
    └── test_session.py
```

## Roadmap

- Disk-backed session persistence for long-running workloads.
- Streaming partial outputs for long calculations.
- Fine-grained resource templates exposing saved worksheets.

## License

MIT
