"""The wire proxy's tool allowlist must actually narrow what a client can do.

The tool-surface measurement's "core tools only" arm depends on it: if a hidden
tool leaked through `tools/list`, or a call to one reached the server, the arm
would silently measure the full catalogue and the comparison would be void.
Pure functions, no subprocess, no Sage.
"""

from __future__ import annotations

import json

from tests.cli_integration.extended_cases import _SUFFIX, EXTENDED_CASES
from tests.cli_integration.mcp_proxy import ToolFilter
from tests.cli_integration.run_extended import (
    CORE_TOOLS,
    accepted_tools_for,
    cases_for_arm,
    prompt_for,
)


def _frame(message: dict) -> bytes:
    return (json.dumps(message) + "\n").encode()


def test_tools_list_is_narrowed_to_the_allowlist() -> None:
    f = ToolFilter({"evaluate_sage", "reset_sage_session"})
    forward, reply = f.client_to_server(_frame({"jsonrpc": "2.0", "id": 7, "method": "tools/list"}))
    assert forward is not None and reply is None
    listing = {"jsonrpc": "2.0", "id": 7, "result": {"tools": [
        {"name": "evaluate_sage"}, {"name": "solve_equation"}, {"name": "reset_sage_session"},
    ]}}
    out = json.loads(f.server_to_client(_frame(listing)))
    assert [t["name"] for t in out["result"]["tools"]] == ["evaluate_sage", "reset_sage_session"]
    # A later, unrelated response is untouched.
    other = _frame({"jsonrpc": "2.0", "id": 8, "result": {"content": []}})
    assert f.server_to_client(other) == other


def test_a_call_to_a_hidden_tool_is_refused_without_reaching_the_server() -> None:
    f = ToolFilter({"evaluate_sage"})
    call = {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "solve_equation", "arguments": {"equation": "x=1"}}}
    forward, reply = f.client_to_server(_frame(call))
    assert forward is None, "the blocked call must not be forwarded"
    error = json.loads(reply)
    assert error["id"] == 3 and error["error"]["code"] == -32602
    assert "solve_equation" in error["error"]["message"]

    allowed = {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
               "params": {"name": "evaluate_sage", "arguments": {"code": "1+1"}}}
    forward, reply = f.client_to_server(_frame(allowed))
    assert forward == _frame(allowed) and reply is None


def test_no_allowlist_means_a_transparent_proxy() -> None:
    f = ToolFilter(None)
    call = _frame({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                   "params": {"name": "anything"}})
    assert f.client_to_server(call) == (call, None)
    listing = _frame({"jsonrpc": "2.0", "id": 1, "result": {"tools": [{"name": "x"}]}})
    assert f.server_to_client(listing) == listing
    garbage = b"not json\n"
    assert f.client_to_server(garbage) == (garbage, None)
    assert f.server_to_client(garbage) == garbage


def test_every_case_is_answerable_in_the_core_arm() -> None:
    """The core arm is only a fair comparison if every case can be solved with a
    tool that is still visible; a case that only accepts a hidden helper would
    score the arm down for the wrong reason."""
    for case in EXTENDED_CASES:
        accepted = accepted_tools_for(case, "core")
        assert accepted and set(accepted) <= CORE_TOOLS, case.id
        assert set(accepted_tools_for(case, "full")) == set(case.accepted_tools)


def test_the_no_server_prompt_stops_asking_for_the_server() -> None:
    """The session cases measure state across two server calls and are left
    out of the no-server arm; every other case must stop naming the server."""
    without_server = cases_for_arm(list(EXTENDED_CASES), "none")
    assert without_server and all(c.domain != "session" for c in without_server)
    assert len(without_server) < len(EXTENDED_CASES)
    assert cases_for_arm(list(EXTENDED_CASES), "full") == list(EXTENDED_CASES)
    for case in without_server:
        prompt = prompt_for(case, "none")
        assert "sagemath MCP server" not in prompt, case.id
        assert "Do not use any tools" in prompt
        assert prompt_for(case, "full") == case.prompt
    assert any(c.prompt.endswith(_SUFFIX) for c in EXTENDED_CASES)
