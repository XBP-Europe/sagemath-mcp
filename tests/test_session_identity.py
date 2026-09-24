"""Where a call's client identity comes from, when the transport has none.

fastmcp 4 answers `Context.session_id` with a fresh UUID on every call. That is
not a bug to wait out: the 2026-07-28 MCP protocol era builds a new connection
per request, so nothing the server can read lasts as long as the client
session (`docs/fastmcp4_session_regression.md`). Every stateful tool used to
key its worker on that id, so each call landed in a fresh, empty session.

`runtime.client_scope` is the one place that decides instead:

- on stdio, one process serves one client, so the process is the identity;
- a workspace token resolves on its own, whatever the transport says;
- on the per-request era over HTTP, a call addressed by name is refused with a
  pointer to `start_sage_session`, rather than silently served a new session.

The contexts here rotate their session id on every read, which is what
fastmcp 4 does, so a test that passes is not relying on a stable id by luck.
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest
from fastmcp.exceptions import ToolError

from sagemath_mcp import runtime, server
from sagemath_mcp.session import WORKSPACE_TOKEN_PREFIX

from .conftest import FakeContext


class RotatingContext(FakeContext):
    """A context whose session id is new on every read, as under fastmcp 4."""

    def __init__(self, protocol_version: str | None = None):
        super().__init__()
        if protocol_version is not None:
            self.request_context = SimpleNamespace(protocol_version=protocol_version)

    @property
    def session_id(self) -> str:
        return str(uuid.uuid4())

    @session_id.setter
    def session_id(self, _value: str) -> None:
        pass  # FakeContext.__init__ assigns one; the property ignores it


@pytest.fixture
def unanchored(monkeypatch):
    """Serve as HTTP does: no process scope. Restored after the test."""
    monkeypatch.setattr(runtime, "PROCESS_SCOPE", None)


@pytest.fixture
def stdio(monkeypatch):
    """Serve as `main()` does on stdio. Restored after the test."""
    monkeypatch.setattr(runtime, "PROCESS_SCOPE", None)
    runtime.anchor_to_process()


# -- stdio: the process is the client ----------------------------------------


async def test_stdio_keeps_variables_when_the_session_id_changes_every_call(sage_manager, stdio):
    """The case the `fastmcp<4` cap exists for, on the transport most clients use."""
    await server.evaluate_sage("keeper = 41", ctx=RotatingContext())
    read = await server.evaluate_sage("keeper + 1", ctx=RotatingContext())
    assert read.result == "42"


async def test_stdio_keeps_named_workspaces_on_the_per_request_era_too(sage_manager, stdio):
    """On stdio the era does not matter: the process scope comes first."""
    ctx = RotatingContext(protocol_version=runtime.PER_REQUEST_ERA)
    await server.evaluate_sage("keeper = 1", session="work", ctx=ctx)
    read = await server.evaluate_sage("keeper", session="work", ctx=ctx)
    assert read.result == "1"
    listed = await server.list_sage_sessions(ctx=ctx)
    assert "work" in json.dumps(listed)


def test_each_process_gets_its_own_scope(monkeypatch):
    """Minted, not fixed: two stdio servers side by side, or one restarted,
    must not share a journal file and restore each other's variables. And
    never the key separator, which `key_for` refuses."""
    monkeypatch.setattr(runtime, "PROCESS_SCOPE", None)
    first = runtime.anchor_to_process()
    second = runtime.anchor_to_process()
    assert first != second
    assert runtime.PROCESS_SCOPE == second
    assert "::" not in first


# -- HTTP on the per-request era: refuse names, honour tokens -----------------


async def test_a_named_call_on_the_per_request_era_is_refused(sage_manager, unanchored):
    ctx = RotatingContext(protocol_version=runtime.PER_REQUEST_ERA)
    with pytest.raises(ToolError, match="start_sage_session"):
        await server.evaluate_sage("1 + 1", ctx=ctx)
    with pytest.raises(ToolError, match="workspace_token"):
        await server.list_sage_sessions(ctx=ctx)


async def test_a_token_works_on_the_per_request_era(sage_manager, unanchored):
    """`start_sage_session` mints under this call's throwaway id; the token it
    returns is then the way back in, whatever id later calls arrive with."""
    ctx = RotatingContext(protocol_version=runtime.PER_REQUEST_ERA)
    started = await server.start_sage_session("work", ctx=ctx)
    assert started.workspace_token.startswith(WORKSPACE_TOKEN_PREFIX)
    await server.evaluate_sage("keeper = 41", session=started.workspace_token, ctx=ctx)
    read = await server.evaluate_sage("keeper + 1", session=started.workspace_token, ctx=ctx)
    assert read.result == "42"
    # Raises if the token reached nothing, so returning at all is the check.
    stopped = await server.stop_sage_session(started.workspace_token, ctx=ctx)
    assert stopped.message.endswith("stopped")


async def test_the_session_resource_is_empty_without_an_identity(sage_manager, unanchored):
    """A resource fails closed rather than raising: nothing is this caller's."""
    ctx = RotatingContext(protocol_version=runtime.PER_REQUEST_ERA)
    assert json.loads(await server.session_resource("all", ctx=ctx)) == []


# -- which era a call is on ---------------------------------------------------


@pytest.mark.parametrize(
    ("ctx", "expected"),
    [
        (FakeContext(), False),  # fastmcp 3.x: no protocol_version at all
        (SimpleNamespace(request_context=None), False),
        (SimpleNamespace(request_context=SimpleNamespace(protocol_version="2025-11-25")), False),
        (SimpleNamespace(request_context=SimpleNamespace(protocol_version="2026-07-28")), True),
        (SimpleNamespace(request_context=SimpleNamespace(protocol_version="2027-03-01")), True),
    ],
)
def test_the_per_request_era_is_read_off_the_protocol_version(ctx, expected):
    assert runtime.identity_is_per_request(ctx) is expected


def test_on_the_handshake_era_the_transport_id_is_the_scope(unanchored):
    """Unchanged from before this existed: the id fastmcp 3.x keeps stable."""
    assert runtime.client_scope(FakeContext("client-a"), "work") == "client-a"
