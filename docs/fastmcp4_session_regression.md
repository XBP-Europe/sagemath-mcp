# fastmcp 4 loses session identity between tool calls

Investigated 2026-09-16 against fastmcp **4.0.4** (and 4.0.3, which CI hit
first), with **3.4.7** as the working comparison. This is why
`pyproject.toml` still says `fastmcp>=3.4.7,<4`.

Reported upstream as **PrefectHQ/fastmcp#5134**.

## Summary

Under fastmcp 4, `Context.session_id` returns a **fresh UUID on every tool
call**, on every transport. Anything keyed to it — this server's per-client Sage
worker, and fastmcp's own `ctx.set_state` / `ctx.get_state` — stops working:
each call looks like a brand new client.

Under 3.4.7 the same code sees one session id for the life of the connection.

## Reproduction

Two tools, one storing session state and one reading it back. No third-party
dependency beyond fastmcp itself.

```python
# repro_server.py
import inspect
from fastmcp import Context, FastMCP

mcp = FastMCP("session-state-repro")

async def _maybe(value):                     # set_state/get_state are async in 4.x
    return await value if inspect.isawaitable(value) else value

@mcp.tool
async def remember(value: str, ctx: Context) -> str:
    await _maybe(ctx.set_state("value", value))
    return f"stored; session_id={ctx.session_id}"

@mcp.tool
async def recall(ctx: Context) -> str:
    got = await _maybe(ctx.get_state("value"))
    return f"session_id={ctx.session_id} value={got!r}"

if __name__ == "__main__":
    mcp.run()
```

```python
# repro_client.py
import asyncio, sys, fastmcp
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

async def main():
    async with Client(StdioTransport(sys.executable, ["repro_server.py"])) as c:
        print("fastmcp", fastmcp.__version__)
        print(" ", (await c.call_tool("remember", {"value": "hello"})).content[0].text)
        print(" ", (await c.call_tool("recall", {})).content[0].text)

asyncio.run(main())
```

Measured, same machine, Python 3.12/3.13, Linux x86_64:

```
fastmcp 3.4.7
  stored; session_id=d2968c89-4f5e-4816-8bed-746180337609
  session_id=d2968c89-4f5e-4816-8bed-746180337609 value='hello'

fastmcp 4.0.4
  stored; session_id=946c6124-aee2-48d0-a503-e4b90c19f0d6
  session_id=500f46db-7480-4f21-aa37-608eafcc7976 value=None
```

Not transport-specific. Session ids observed per call:

| Transport | 3.4.7 | 4.0.4 |
| --- | --- | --- |
| stdio | one id for the connection | a new id per call |
| streamable-http | one id for the connection | a new id per call |
| in-memory (`Client(server)`) | one id for the connection | a new id per call |

## Cause

`Context.session_id` (`fastmcp/server/context.py`) caches a generated id on the
connection, with this comment:

> In SDK v2 the ServerSession is constructed fresh per request, so the stable
> per-client identity lives on the underlying Connection, which persists for the
> whole client session.

The Connection does not persist. Printing `id(session._connection)` on three
consecutive calls over stdio gives three different objects, each arriving with
its own `_fastmcp_state_prefix` already set:

```
A1 id(conn)=138474642270272 state={'_fastmcp_state_prefix': 'f4a578da'} sid=f4a578da
A2 id(conn)=138474622867344 state={'_fastmcp_state_prefix': '87faed8e'} sid=87faed8e
A3 id(conn)=138474622875984 state={'_fastmcp_state_prefix': '2d2b44b3'} sid=2d2b44b3
```

So the cache is written to an object that is discarded before the next call, and
the `connection.state.get(...)` read on the next call never hits. For HTTP,
`connection.session_id` is also `None` and no `mcp-session-id` header is
present, so it falls through to the same generated-UUID path.

## What it blocks here

`tests/test_cache_isolation.py::test_two_clients_do_not_share_tool_results`
fails under 4.x: the second client's assignment lands in one worker and its read
in another, so the variable is missing. **REVIEW_ACTIONS item 68 attributed that
to fastmcp's response cache; that diagnosis was wrong.** This server disables
tool, resource and prompt caching explicitly in `app.py`, and the failure
reproduces with caching off. The cause is session identity, and the same test
would fail for any stateful fastmcp server.

The cap therefore stays. Note that the three other tests in that file pass under
4.x for the wrong reason — they assert that reads *fail* after a reset, which an
unstable session satisfies by accident.

## What would lift the cap

Either upstream restores a stable per-connection identity, or this server stops
depending on one. The second is partly built already: `start_sage_session`
issues a portable `workspace_token` (the application-issued handle the
2026-07-28 MCP spec recommends after retiring protocol-level sessions), and any
client passing it is unaffected by this bug. What breaks is the zero-config
default, where a client just calls `evaluate_sage` and expects its variables to
still be there.

A process-wide identity would fix stdio, where one process serves exactly one
client — but it would merge every HTTP client into a single shared session,
which is precisely the confidentiality failure `test_cache_isolation.py` exists
to prevent. So it is not a safe general workaround.

## Re-testing after an upstream fix

Run the reproduction above against the new version. If both lines print the same
`session_id` and `value='hello'`, install it in the Sage container and run
`tests/test_cache_isolation.py` in full before touching the pin.
