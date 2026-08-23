"""The health probe and the documentation lookup.

Both exist for agent ergonomics: stdio clients cannot reach the HTTP /health
route, and a doc pointer that also says "this name is withheld here" saves a
refused evaluation.
"""

import pytest

from sagemath_mcp import runtime, server
from sagemath_mcp.config import SageSettings
from sagemath_mcp.session import SageProcessError, SageSessionManager

from .conftest import FakeContext


@pytest.mark.asyncio
async def test_health_probe_reports_a_working_worker(monkeypatch):
    manager = SageSessionManager(SageSettings(force_python_worker=True))
    monkeypatch.setattr(runtime, "SESSION_MANAGER", manager)
    monkeypatch.setattr(runtime.SETTINGS, "force_python_worker", True)
    ctx = FakeContext("health-ok")
    try:
        report = await server.check_sage_health(ctx=ctx)
    finally:
        await manager.shutdown()
    assert report["ok"] is True
    assert report["backend"] == "pure-python"
    assert report["session"] == "default"
    assert report["elapsed_ms"] >= 0


@pytest.mark.asyncio
async def test_health_probe_requires_a_session_context():
    with pytest.raises(server.ToolError):
        await server.check_sage_health(ctx=None)


@pytest.mark.asyncio
async def test_health_probe_reports_unhealthy_instead_of_erroring(monkeypatch):
    """Unhealthy is the tool's answer, not its failure mode."""

    async def broken_resolve(client_session_id, name):
        raise SageProcessError("Unable to locate Sage executable 'sage'.")

    monkeypatch.setattr(runtime, "resolve_session", broken_resolve)
    monkeypatch.setattr(runtime.SETTINGS, "force_python_worker", False)
    report = await server.check_sage_health(ctx=FakeContext("health-broken"))
    assert report["ok"] is False
    assert report["backend"] == "sagemath"
    assert "Unable to locate Sage executable" in report["reason"]


@pytest.mark.asyncio
async def test_doc_lookup_flags_an_offered_name():
    report = await server.lookup_sage_doc("sqrt")
    assert report["offered_to_caller_code"] is True
    assert "available" in report["note"]
    assert report["links"]["reference_search"].endswith("?q=sqrt")


@pytest.mark.asyncio
async def test_doc_lookup_warns_about_a_withheld_name():
    """The half the upstream manual cannot answer: `cython` is documented
    there and refused here, and saying so saves the model the refusal."""
    report = await server.lookup_sage_doc("cython")
    assert report["offered_to_caller_code"] is False
    assert "NOT offered" in report["note"]
    assert "refused" in report["note"]


@pytest.mark.asyncio
async def test_doc_lookup_encodes_the_symbol_into_the_url():
    report = await server.lookup_sage_doc("  EllipticCurve  ")
    assert report["symbol"] == "EllipticCurve"
    assert report["links"]["reference_search"].endswith("?q=EllipticCurve")


@pytest.mark.asyncio
async def test_doc_lookup_refuses_an_empty_symbol():
    with pytest.raises(server.ToolError):
        await server.lookup_sage_doc("   ")
