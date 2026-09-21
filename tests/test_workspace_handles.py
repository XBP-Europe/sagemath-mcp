"""Server-issued portable workspace handles.

The transport-level MCP session id does two jobs that pull apart: it isolates
one client's `default` workspace from another's, and it is supposed to keep a
client's state across calls -- but it is unstable (the MCP spec is retiring
protocol sessions, and fastmcp 4 rotated it per call, which is what silently
lost state). A handle is the fix: an unguessable, server-issued bearer token
that addresses one workspace independently of the transport id. Possession
grants access -- it is a capability, not authentication -- so the guarantees
are (1) it reaches the same workspace whatever the transport id is, and (2) an
unknown handle cannot be fabricated to reach someone else's state.
"""

from __future__ import annotations

import string
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from sagemath_mcp import runtime, server
from sagemath_mcp.config import SageSettings
from sagemath_mcp.session import (
    DEFAULT_SESSION_NAME,
    WORKSPACE_TOKEN_PREFIX,
    SageProcessError,
    SageSessionManager,
)

from .conftest import FakeContext


@pytest.fixture
def manager(monkeypatch):
    mgr = SageSessionManager(SageSettings(force_python_worker=True))
    monkeypatch.setattr(runtime, "SESSION_MANAGER", mgr)
    return mgr


async def test_start_sage_session_issues_a_handle(manager):
    result = await server.start_sage_session("curves", ctx=FakeContext("client-a"))
    assert result.name == "curves"
    assert result.workspace_token.startswith(WORKSPACE_TOKEN_PREFIX)
    # Unguessable: token_urlsafe(24) is 32 characters after the prefix.
    assert len(result.workspace_token) > len(WORKSPACE_TOKEN_PREFIX) + 20


async def test_two_starts_issue_distinct_handles(manager):
    ctx = FakeContext("client-a")
    a = await server.start_sage_session("one", ctx=ctx)
    b = await server.start_sage_session("two", ctx=ctx)
    assert a.workspace_token != b.workspace_token


async def test_a_handle_reaches_the_same_workspace_across_transport_ids(manager):
    """The whole point: state survives a changed transport session id.

    The client starts a workspace on one transport id, defines a variable, then
    reconnects -- a *different* ctx.session_id -- and presents the handle. It
    must reach the same worker, not a fresh one keyed on the new id.
    """
    started = await server.start_sage_session("work", ctx=FakeContext("transport-1"))
    token = started.workspace_token

    await server.evaluate_sage("keeper = 41", session=token, ctx=FakeContext("transport-1"))
    # A brand-new transport session id, as a reconnect or a per-call rotation
    # would produce. Name-based scoping would miss the state; the handle does not.
    read = await server.evaluate_sage("keeper + 1", session=token, ctx=FakeContext("transport-2"))
    assert read.result == "42"


async def test_a_name_is_still_scoped_to_the_transport_session(manager):
    """Backward compatibility: a plain name behaves exactly as before.

    Two clients both using the default (or any name) must stay isolated -- the
    handle feature must not weaken the confidentiality the transport scope gives.
    """
    await server.evaluate_sage("secret = 1", session="shared", ctx=FakeContext("client-a"))
    # Same workspace *name*, different client: must not see client-a's variable.
    other = await server.evaluate_sage(
        "'secret' in dir()", session="shared", ctx=FakeContext("client-b")
    )
    assert other.result == "False"


async def test_an_unknown_handle_is_refused_not_silently_opened(manager):
    """A fabricated handle must not reach a fresh workspace -- unguessability is
    the isolation guarantee, so an unrecognised token is an error."""
    forged = WORKSPACE_TOKEN_PREFIX + "not-a-real-token"
    with pytest.raises(Exception) as excinfo:  # ToolError wraps it at the tool
        await server.evaluate_sage("1 + 1", session=forged, ctx=FakeContext("attacker"))
    assert "handle" in str(excinfo.value).lower()


async def test_resolve_key_rejects_an_unknown_handle(manager):
    with pytest.raises(SageProcessError, match="Unknown or expired workspace handle"):
        manager.resolve_key("scope", WORKSPACE_TOKEN_PREFIX + "bogus")


async def test_a_name_may_not_masquerade_as_a_handle(manager):
    with pytest.raises(Exception, match="reserved"):
        await server.start_sage_session(WORKSPACE_TOKEN_PREFIX + "sneaky", ctx=FakeContext("c"))


async def test_reset_and_cancel_honor_the_handle(manager):
    """The lifecycle operations resolve a handle the same way evaluation does.

    Reset clears the namespace but keeps the worker; cancel restarts the worker.
    Both keep the workspace (and therefore the handle) alive -- the reviewer's
    acceptance criterion that evaluation, interrupt, cancel and stop all honour
    one handle. A handle that resolved before reset/cancel must resolve after.
    """
    started = await server.start_sage_session("lc", ctx=FakeContext("client-a"))
    token = started.workspace_token
    key = manager.resolve_key("client-a", token)

    await server.reset_sage_session(session=token, ctx=FakeContext("t2"))
    assert manager.resolve_key("client-a", token) == key  # still valid

    await server.cancel_sage_session(session=token, ctx=FakeContext("t3"))
    assert manager.resolve_key("client-a", token) == key  # still valid

    # And it still reaches a live, usable worker on a fresh transport id.
    result = await server.evaluate_sage("2 + 3", session=token, ctx=FakeContext("t4"))
    assert result.result == "5"


async def test_interrupt_honors_the_handle(manager):
    """Interrupt on an idle handle-addressed workspace reports nothing running,
    without creating or losing anything."""
    started = await server.start_sage_session("iw", ctx=FakeContext("client-a"))
    token = started.workspace_token
    result = await server.interrupt_sage_session(session=token, ctx=FakeContext("t2"))
    assert "No running" in result.message or "state preserved" in result.message


async def test_stopping_by_handle_forgets_it(manager):
    ctx = FakeContext("client-a")
    started = await server.start_sage_session("temp", ctx=ctx)
    token = started.workspace_token
    # Stop by handle: the workspace goes, and the handle stops resolving.
    stopped = await server.stop_sage_session(token, ctx=ctx)
    assert "stopped" in stopped.message.lower()
    with pytest.raises(SageProcessError):
        manager.resolve_key("client-a", token)


async def test_stopping_an_unknown_handle_is_a_harmless_false(manager):
    """Stop is idempotent: an unknown handle names no workspace, so it reports
    'did not exist' rather than raising."""
    stopped = await runtime.SESSION_MANAGER.stop("client-a", WORKSPACE_TOKEN_PREFIX + "gone")
    assert stopped is False


async def test_culling_forgets_the_handle(manager, monkeypatch):
    """A handle whose worker is culled stops resolving, bounding the map."""
    started = await server.start_sage_session("idle", ctx=FakeContext("client-a"))
    token = started.workspace_token
    key = manager.resolve_key("client-a", token)
    assert key in manager._aliases.values()

    # Force everything to look idle, then cull.
    for session in manager._sessions.values():
        monkeypatch.setattr(session, "should_cull", lambda now: True)
    await manager.cull_idle()

    assert token not in manager._aliases
    with pytest.raises(SageProcessError):
        manager.resolve_key("client-a", token)


async def test_a_handle_is_not_exposed_through_the_session_resource(manager):
    """The bearer token must not leak: the session resource lists a client's own
    workspaces by name, never the token that addresses them."""
    ctx = FakeContext("client-a")
    started = await server.start_sage_session("visible", ctx=ctx)
    token = started.workspace_token
    blob = await server.session_resource("all", ctx)
    assert token not in blob
    assert "visible" in blob  # listed by name, as intended


async def test_lifecycle_tools_never_echo_the_workspace_token(manager):
    """The token is a bearer credential; no lifecycle op may put it in a log
    notification or a response. Names are not secret and may still appear.

    Regression for an external review (REVIEW_ACTIONS 70): reset/interrupt/cancel
    interpolated the caller's `session` argument -- which now carries the token --
    straight into `ctx.info`/`ctx.warning`, and stop echoed it too.
    """
    ctx = FakeContext("client-a")
    token = (await server.start_sage_session("scratch", ctx=ctx)).workspace_token
    await server.evaluate_sage("a = 1", session=token, ctx=ctx)

    def _assert_clean(context, response) -> None:
        emitted = [
            *context.info_messages,
            *context.warning_messages,
            getattr(response, "message", ""),
        ]
        leaked = [m for m in emitted if token in (m or "")]
        assert not leaked, f"workspace token leaked: {leaked}"

    for tool in (
        server.reset_sage_session,
        server.interrupt_sage_session,
        server.cancel_sage_session,
    ):
        call_ctx = FakeContext("client-a")
        response = await tool(session=token, ctx=call_ctx)
        _assert_clean(call_ctx, response)

    # stop resolves a token too; whether it stops the workspace or reports none,
    # the token must not appear in the response, the logs, or an error.
    stop_ctx = FakeContext("client-a")
    try:
        stop_response = await server.stop_sage_session(token, ctx=stop_ctx)
    except server.ToolError as exc:
        assert token not in str(exc)
    else:
        _assert_clean(stop_ctx, stop_response)


def test_no_tool_interpolates_a_raw_session_argument() -> None:
    """The durable version of the check that missed `evaluate_sage`.

    Item 70 routed the lifecycle tools' strings through the masking helper and
    pinned it with a hand-written list of four tools. `evaluate_sage` takes the
    same `session` argument and was not on that list, so its cancellation path
    printed the workspace token verbatim into an MCP warning -- found by a
    security review on 2026-09-19, a year of releases later.

    A hand-written list is what failed. This reads the tool sources instead, so
    a new tool that interpolates `session` raw fails here whether or not anyone
    remembers to add it.
    """
    tools_dir = Path(__file__).resolve().parents[1] / "src" / "sagemath_mcp" / "tools"
    offenders: list[str] = []
    for source in sorted(tools_dir.glob("*.py")):
        for number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
            # An f-string interpolating the argument itself, rather than the
            # masked form. `{session_key}` is the resolved internal key, not the
            # caller's credential, and is fine.
            if "{session}" in line and "loggable_session" not in line:
                offenders.append(f"{source.name}:{number}: {line.strip()}")
    assert not offenders, (
        "a tool interpolates its raw `session` argument, which may be a "
        "workspace token (a bearer credential):\n" + "\n".join(offenders)
    )


# --- Key composition --------------------------------------------------------


def test_a_scope_may_not_contain_the_separator() -> None:
    """Two distinct pairs composed to one storage key, so two clients would
    have shared a worker and its namespace:

        key_for("A", "x")          -> "A::x"
        key_for("A::x", "default") -> "A::x"

    The default workspace keying on the bare scope is what allows it, and that
    shortcut cannot change: it is what keeps persisted journal filenames the
    same as before named sessions existed.

    Not reachable today -- the scope is the MCP session id, fastmcp issues a
    hex UUID and answers a client-supplied `Mcp-Session-Id` with 404 (measured
    2026-09-21). That is an invariant of a dependency, asserted nowhere here,
    guarding the only thing the key scheme exists to do (REVIEW_ACTIONS 93).
    """
    from sagemath_mcp.session import SageProcessError, SageSessionManager

    with pytest.raises(SageProcessError, match="may not contain"):
        SageSessionManager.key_for("A::x", DEFAULT_SESSION_NAME)
    with pytest.raises(SageProcessError, match="may not contain"):
        SageSessionManager.key_for("A::x", "anything")


@given(
    scope_a=st.text(alphabet=string.ascii_letters + string.digits + "-_", min_size=1, max_size=12),
    scope_b=st.text(alphabet=string.ascii_letters + string.digits + "-_", min_size=1, max_size=12),
    name_a=st.text(alphabet=string.ascii_letters + string.digits + "-_ ", min_size=0, max_size=12),
    name_b=st.text(alphabet=string.ascii_letters + string.digits + "-_ ", min_size=0, max_size=12),
)
def test_distinct_workspaces_never_share_a_key(
    scope_a: str, scope_b: str, name_a: str, name_b: str
) -> None:
    """Injectivity, which is the whole isolation guarantee: two workspaces that
    differ in scope or in normalised name must not compose to one key.

    Names normalise -- stripped, and empty becomes the default -- so the
    comparison is between normalised pairs, not raw arguments.
    """
    from sagemath_mcp.session import SageSessionManager

    def normalised(name: str) -> str:
        return (name or DEFAULT_SESSION_NAME).strip() or DEFAULT_SESSION_NAME

    pair_a = (scope_a, normalised(name_a))
    pair_b = (scope_b, normalised(name_b))
    key_a = SageSessionManager.key_for(*pair_a)
    key_b = SageSessionManager.key_for(*pair_b)
    if pair_a != pair_b:
        assert key_a != key_b, f"{pair_a} and {pair_b} both key to {key_a!r}"
    else:
        assert key_a == key_b


@given(name=st.text(min_size=1, max_size=40))
def test_an_unminted_handle_is_always_refused(name: str) -> None:
    """Fail closed: a handle-shaped name that was never minted must raise, not
    open a fresh workspace under the caller's own scope. Opening one would be
    the worse outcome -- the caller would think they had reached a workspace."""
    from sagemath_mcp.session import (
        WORKSPACE_TOKEN_PREFIX,
        SageProcessError,
        SageSessionManager,
    )

    manager = SageSessionManager()
    handle = WORKSPACE_TOKEN_PREFIX + name
    with pytest.raises(SageProcessError, match="Unknown or expired"):
        manager.resolve_key("scope", handle)


@given(
    scope=st.text(max_size=16)
    | st.sampled_from(["all", "*", "", "../other", "other::secret", "%2e%2e"])
)
def test_the_session_resource_never_returns_another_clients_workspace(scope: str) -> None:
    """`{scope}` is the one caller-controlled part of the resource URI, and
    the manager's map holds every client's workspaces.

    Reading `.../session/all` once returned the whole map, so any client could
    learn another's MCP session id and replay it in a header (item 57). The
    filter is now on `ctx.session_id`, which the caller does not choose, and
    `{scope}` only selects a workspace *name* within it. This asserts that
    holds for any scope at all, including one spelled like another client's
    key.
    """
    import asyncio
    from unittest.mock import MagicMock

    from sagemath_mcp import runtime
    from sagemath_mcp.tools import session as session_tools

    manager = MagicMock()
    manager.snapshot.return_value = [
        {"session_id": "mine", "live": True, "started_at": 1.0,
         "last_used_at": 2.0, "idle_seconds": 0.0},
        {"session_id": "theirs::secret", "live": True, "started_at": 1.0,
         "last_used_at": 2.0, "idle_seconds": 0.0},
    ]
    context = MagicMock()
    context.session_id = "mine"

    original = runtime.SESSION_MANAGER
    runtime.SESSION_MANAGER = manager
    try:
        body = asyncio.run(session_tools.session_resource(scope, ctx=context))
    finally:
        runtime.SESSION_MANAGER = original

    assert "theirs" not in body and "secret" not in body, (scope, body)
