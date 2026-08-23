"""Agent-facing diagnostics: a health probe and documentation lookup.

Both adopted from the 2026-08-24 peer survey. Stdio clients cannot reach the
HTTP ``/health`` route, so agents had no way to check readiness before
committing to a workflow; and models routinely want the Sage documentation
for a name, where a static URL map answers without costing a worker round
trip. The annotation dicts are spelled inline here; they match the groups in
``tools/hints.py`` once that module lands.
"""

from __future__ import annotations

import time
from typing import Annotated
from urllib.parse import quote_plus

from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import Field

from .. import runtime
from ..allowlist import ALLOWED_CALLER_NAMES
from ..app import mcp
from ..session import DEFAULT_SESSION_NAME, SageEvaluationError, SageProcessError
from ..text import SESSION_ARG_DESC as _SESSION_ARG_DESC

# The probe never waits longer than this, whatever eval_timeout is set to: a
# health check that can hang for minutes reports nothing anyone can act on.
_PROBE_TIMEOUT_SECONDS = 10.0

# Static URL templates into the upstream manual, which is the authoritative
# copy and always current -- the same stance as the docs resource. No worker
# round trip, nothing to sandbox.
_DOC_LINKS: tuple[tuple[str, str], ...] = (
    ("reference_search", "https://doc.sagemath.org/html/en/reference/search.html?q={symbol}"),
    ("reference_index", "https://doc.sagemath.org/html/en/reference/index.html"),
    ("tutorial", "https://doc.sagemath.org/html/en/tutorial/index.html"),
)


@mcp.tool(
    annotations={
        "readOnlyHint": False,   # the probe may start the workspace's worker
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
    description="Probe whether SageMath evaluation works right now: starts (or reuses) "
    "the workspace's worker, evaluates 1+1, and reports readiness and latency. "
    "Reports failure in the result instead of erroring, so it is always safe to call",
)
async def check_sage_health(
    session: Annotated[str, Field(description=_SESSION_ARG_DESC)] = DEFAULT_SESSION_NAME,
    ctx: Context | None = None,
) -> dict:
    """Answer "can this server do mathematics for me right now?" cheaply.

    The HTTP ``/health`` route answers the same question for Kubernetes, but a
    stdio client cannot reach it. This is the MCP-level equivalent, and it
    exercises the real path -- worker spawn, protocol round trip, evaluation --
    not just process liveness.
    """
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required to check health")
    backend = "pure-python" if runtime.SETTINGS.force_python_worker else "sagemath"
    started = time.perf_counter()
    try:
        sage = await runtime.resolve_session(ctx.session_id, session)
        result = await sage.evaluate(
            "1 + 1",
            want_latex=False,
            capture_stdout=False,
            timeout_seconds=min(_PROBE_TIMEOUT_SECONDS, runtime.SETTINGS.eval_timeout),
        )
    except (SageProcessError, SageEvaluationError, TimeoutError) as exc:
        # Unhealthy is this tool's answer, not its failure mode.
        return {
            "ok": False,
            "backend": backend,
            "reason": str(exc),
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            "session": session,
        }
    return {
        "ok": result.result == "2",
        "backend": backend,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        "session": session,
    }


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
    description="Documentation links for a SageMath name, plus whether this server "
    "offers that name to evaluate_sage caller code",
)
async def lookup_sage_doc(
    symbol: Annotated[
        str, Field(description="A SageMath name, e.g. 'EllipticCurve' or 'desolve'")
    ],
) -> dict:
    """Point at the upstream manual for one name, and say if it works here.

    The second half is the part the manual cannot answer: caller code is
    deny-by-default, so a name Sage documents may still be withheld by this
    server. Saying so up front saves the model a refused evaluation.
    """
    name = symbol.strip()
    if not name:
        raise ToolError("symbol must not be empty")
    links = {label: url.format(symbol=quote_plus(name)) for label, url in _DOC_LINKS}
    offered = name in ALLOWED_CALLER_NAMES
    if offered:
        note = f"'{name}' is available to evaluate_sage caller code on this server."
    else:
        note = (
            f"'{name}' is NOT offered to evaluate_sage caller code on this server -- "
            "the documentation may describe it, but calling it here will be refused. "
            "Session variables and names your own code binds are always available."
        )
    return {
        "symbol": name,
        "offered_to_caller_code": offered,
        "links": links,
        "note": note,
    }
