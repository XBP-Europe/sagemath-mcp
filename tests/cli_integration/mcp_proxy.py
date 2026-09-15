#!/usr/bin/env python3
"""A transparent MCP stdio proxy that records which tools a client called.

Why this exists: an LLM can answer "differentiate x^3 + 2x" from memory. A test
that only greps the CLI's final answer therefore proves nothing about the MCP
server -- it passes just as happily when the model never connects. The existing
CLI suite has that shape.

Sitting between the CLI and the real server makes tool invocation observable,
without touching the server or depending on each CLI's log format. The test can
then assert what actually happened on the wire.

It can also *narrow* what the client sees. With ``--allow-tools`` the proxy
removes every other tool from the server's ``tools/list`` answer and refuses a
``tools/call`` to a hidden tool with a JSON-RPC error, without the call reaching
the server. That is how the tool-surface measurement runs a "core tools only"
arm against the unmodified server: the reduced catalogue is enforced on the
wire, not requested in a prompt the model may ignore.

Usage:
    mcp_proxy.py --log /path/to/session.jsonl [--allow-tools a,b,c] -- <real server command...>

Only the standard library is used, so any Python on PATH can run it.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

# Recording whole frames would mean megabytes of base64 for a single plot.
_MAX_PREVIEW = 400


def _append(log_path: Path, record: dict) -> None:
    record["ts"] = time.time()
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def _describe(direction: str, raw: bytes) -> dict | None:
    """Summarise one JSON-RPC frame, or None if it is not worth recording."""
    try:
        message = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(message, dict):
        return None

    method = message.get("method")
    if method == "tools/call":
        params = message.get("params") or {}
        return {
            "direction": direction,
            "kind": "tool_call",
            "tool": params.get("name"),
            "arguments": json.dumps(params.get("arguments", {}))[:_MAX_PREVIEW],
            "id": message.get("id"),
        }
    if method:
        return {"direction": direction, "kind": "request", "method": method,
                "id": message.get("id")}

    # A response: capture whether the server reported an error, and a preview.
    if "result" in message or "error" in message:
        result = message.get("result") or {}
        is_error = bool(message.get("error")) or bool(
            isinstance(result, dict) and result.get("isError")
        )
        return {
            "direction": direction,
            "kind": "response",
            "id": message.get("id"),
            "is_error": is_error,
            "preview": json.dumps(result)[:_MAX_PREVIEW] if result else None,
            "error": json.dumps(message.get("error"))[:_MAX_PREVIEW]
            if message.get("error")
            else None,
        }
    return None


class ToolFilter:
    """Narrow the tool catalogue a client can see and call.

    ``client_to_server`` returns ``(forward, reply)``: the frame to forward to
    the server (or None to drop it) and a frame to send straight back to the
    client (or None). ``server_to_client`` returns the frame to forward, with
    hidden tools removed from a ``tools/list`` result. Frames that are not JSON,
    or not about tools, pass through untouched.
    """

    def __init__(self, allowed: set[str] | None):
        self.allowed = allowed
        self._list_ids: set = set()

    @staticmethod
    def _parse(raw: bytes) -> dict | None:
        try:
            message = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return message if isinstance(message, dict) else None

    @staticmethod
    def _frame(message: dict) -> bytes:
        return (json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8")

    def client_to_server(self, raw: bytes) -> tuple[bytes | None, bytes | None]:
        if self.allowed is None:
            return raw, None
        message = self._parse(raw)
        if message is None:
            return raw, None
        method = message.get("method")
        if method == "tools/list" and message.get("id") is not None:
            self._list_ids.add(message["id"])
            return raw, None
        if method == "tools/call":
            name = (message.get("params") or {}).get("name")
            if name not in self.allowed:
                # The MCP error for a tool the server does not have. The model
                # sees exactly what it would see from a server that never had
                # the tool, which is what the arm is meant to simulate.
                reply = {
                    "jsonrpc": "2.0",
                    "id": message.get("id"),
                    "error": {"code": -32602, "message": f"Unknown tool: {name}"},
                }
                return None, self._frame(reply)
        return raw, None

    def server_to_client(self, raw: bytes) -> bytes:
        if self.allowed is None or not self._list_ids:
            return raw
        message = self._parse(raw)
        if message is None or message.get("id") not in self._list_ids:
            return raw
        self._list_ids.discard(message["id"])
        result = message.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("tools"), list):
            return raw
        result["tools"] = [t for t in result["tools"] if t.get("name") in self.allowed]
        return self._frame(message)


def _pump_to_server(src, dst, out, out_lock, log_path: Path, tool_filter: ToolFilter) -> None:
    """Client -> server: forward, or answer a blocked call ourselves."""
    for raw in iter(src.readline, b""):
        forward, reply = tool_filter.client_to_server(raw)
        record = _describe("client->server", raw.strip())
        if forward is not None:
            dst.write(forward)
            dst.flush()
        if reply is not None:
            with out_lock:
                out.write(reply)
                out.flush()
            if record is not None:
                record["blocked"] = True
        if record is not None:
            _append(log_path, record)
    with contextlib.suppress(Exception):
        dst.close()


def _pump_to_client(src, out, out_lock, log_path: Path, tool_filter: ToolFilter) -> None:
    """Server -> client: forward, narrowing the tool list when asked to."""
    for raw in iter(src.readline, b""):
        forward = tool_filter.server_to_client(raw)
        with out_lock:
            out.write(forward)
            out.flush()
        record = _describe("server->client", raw.strip())
        if record is not None:
            _append(log_path, record)
    with contextlib.suppress(Exception):
        out.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", required=True, help="JSONL file to append to")
    parser.add_argument(
        "--allow-tools",
        help="comma-separated tool names the client may see and call; "
        "everything else is hidden from tools/list and refused on tools/call",
    )
    parser.add_argument("command", nargs=argparse.REMAINDER,
                        help="the real MCP server command, after --")
    args = parser.parse_args()

    command = [part for part in args.command if part != "--"]
    if not command:
        print("mcp_proxy: no server command given", file=sys.stderr)
        return 2

    log_path = Path(args.log)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    allowed = (
        {name.strip() for name in args.allow_tools.split(",") if name.strip()}
        if args.allow_tools is not None
        else None
    )
    tool_filter = ToolFilter(allowed)

    server = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=None,  # let the server's stderr reach the CLI's own logs
    )
    assert server.stdin and server.stdout

    out = sys.stdout.buffer
    out_lock = threading.Lock()
    to_server = threading.Thread(
        target=_pump_to_server,
        args=(sys.stdin.buffer, server.stdin, out, out_lock, log_path, tool_filter),
        daemon=True,
    )
    to_client = threading.Thread(
        target=_pump_to_client,
        args=(server.stdout, out, out_lock, log_path, tool_filter),
        daemon=True,
    )
    to_server.start()
    to_client.start()
    to_client.join()
    return server.wait()


if __name__ == "__main__":
    raise SystemExit(main())
