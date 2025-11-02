# SageMath MCP Monitoring Guide

This server now exposes aggregated evaluation metrics so you can track success/failure rates, latency, and security violations in your operational dashboards.

## Available Metrics

Metrics are served through the `resource://sagemath/monitoring/metrics` MCP resource. The payload includes:

| Field | Description |
| --- | --- |
| `attempts` | Total evaluation attempts since the process started. |
| `successes` | Successful evaluations. |
| `failures` | Failed evaluations (including security violations). |
| `security_failures` | Attempts blocked by the AST security policy. |
| `avg_elapsed_ms` | Average execution time (milliseconds, success only). |
| `max_elapsed_ms` | Maximum execution time observed (milliseconds). |
| `last_run_at` | UNIX timestamp of the most recent evaluation. |
| `last_error` | Message from the latest failure (if any). |
| `last_security_violation` | Message from the latest security violation (if any). |

These counters reset when the MCP server restarts. Set `SAGEMATH_MCP_SECURITY_LOG_VIOLATIONS=true` to ensure blocked code is logged alongside the counters.

## Manual Inspection

### StdIO transport

If you run the server locally via stdio (`uv run sagemath-mcp`), you can query the resource with FastMCP’s client helpers:

```bash
uv run python - <<'PY'
import asyncio, json
from fastmcp import Client

async def main():
    client = Client("sagemath-mcp", transport="stdio")
    metrics = await client.resource("resource://sagemath/monitoring/metrics")
    print(json.dumps([m.model_dump() for m in metrics], indent=2))

asyncio.run(main())
PY
```

### HTTP transport

When the server runs over HTTP (`uv run sagemath-mcp -- --transport streamable-http --port 31415`), switch the client transport:

```bash
uv run python - <<'PY'
import asyncio, json
from fastmcp import Client

async def main():
    client = Client("http://127.0.0.1:31415/mcp", transport="http")
    metrics = await client.resource("resource://sagemath/monitoring/metrics")
    print(json.dumps([m.model_dump() for m in metrics], indent=2))

asyncio.run(main())
PY
```

## Exporting to Prometheus / Grafana

Create a small bridge that fetches metrics and exposes a Prometheus-compatible endpoint:

```python
# scripts/metrics_exporter.py
import asyncio, json
from aiohttp import web
from fastmcp import Client

TEMPLATE = """# HELP sagemath_mcp_{name} {help}
# TYPE sagemath_mcp_{name} gauge
sagemath_mcp_{name}{labels} {value}
"""

FIELDS = {
    "attempts": "Total evaluation attempts",
    "successes": "Successful evaluations",
    "failures": "Failed evaluations",
    "security_failures": "Security policy violations",
    "avg_elapsed_ms": "Average execution latency (ms)",
    "max_elapsed_ms": "Maximum execution latency (ms)",
}

async def fetch_snapshot():
    client = Client("http://127.0.0.1:31415/mcp", transport="http")
    snapshot = await client.resource("resource://sagemath/monitoring/metrics")
    return snapshot[0]

async def metrics_handler(request):
    try:
        snapshot = await fetch_snapshot()
    except Exception:
        return web.Response(status=503, text="sagemath_mcp_up 0\n")
    lines = []
    for field, help_text in FIELDS.items():
        value = getattr(snapshot, field) or 0
        lines.append(
            TEMPLATE.format(
                name=field,
                help=help_text,
                labels="{transport=\"sagemath-mcp\"}",
                value=value,
            )
        )
    return web.Response(text="".join(lines))

app = web.Application()
app.router.add_get("/metrics", metrics_handler)

if __name__ == "__main__":
    web.run_app(app, port=9108)
```

Run the exporter (inside Docker or on the host):

```bash
uv run python scripts/metrics_exporter.py
# Prometheus scrape target: http://HOST:9108/metrics
```

Add the endpoint to Prometheus, then build dashboards for `sagemath_mcp_failures`, `sagemath_mcp_security_failures`, and the latency gauges.

## Integration Testing

`tests/test_integration.py` exercises this resource against a real Sage binary. From the provided Sage Docker container:

```bash
docker exec sage-mcp bash -lc 'cd /workspace && sage -python -m pytest'
```

All integration tests should pass, confirming that metrics update correctly under live Sage workloads.

## Suggested Alerts

* **Security violation spike**: alert on a sudden rise in `security_failures`.
* **Failure rate**: track `(failures - security_failures)` to catch Sage worker issues.
* **Latency**: alert if `max_elapsed_ms` exceeds expected thresholds.

With metrics surfaced, you can correlate spikes with MCP client requests, review blocked code, and maintain a healthy Sage deployment.
