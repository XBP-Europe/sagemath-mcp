#!/usr/bin/env python3
"""A transparent MCP stdio proxy that records which tools a client called.

Why this exists: an LLM can answer "differentiate x^3 + 2x" from memory. A test
that only greps the CLI's final answer therefore proves nothing about the MCP
server -- it passes just as happily when the model never connects. The existing
CLI suite has that shape.

Sitting between the CLI and the real server makes tool invocation observable,
without touching the server or depending on each CLI's log format. The test can
then assert what actually happened on the wire.

Usage:
    mcp_proxy.py --log /path/to/session.jsonl -- <real server command...>

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


def _pump(src, dst, log_path: Path, direction: str) -> None:
    """Forward frames verbatim, recording a summary of each."""
    for raw in iter(src.readline, b""):
        dst.write(raw)
        dst.flush()
        record = _describe(direction, raw.strip())
        if record is not None:
            _append(log_path, record)
    with contextlib.suppress(Exception):
        dst.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", required=True, help="JSONL file to append to")
    parser.add_argument("command", nargs=argparse.REMAINDER,
                        help="the real MCP server command, after --")
    args = parser.parse_args()

    command = [part for part in args.command if part != "--"]
    if not command:
        print("mcp_proxy: no server command given", file=sys.stderr)
        return 2

    log_path = Path(args.log)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    server = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=None,  # let the server's stderr reach the CLI's own logs
    )
    assert server.stdin and server.stdout

    to_server = threading.Thread(
        target=_pump, args=(sys.stdin.buffer, server.stdin, log_path, "client->server"),
        daemon=True,
    )
    to_client = threading.Thread(
        target=_pump, args=(server.stdout, sys.stdout.buffer, log_path, "server->client"),
        daemon=True,
    )
    to_server.start()
    to_client.start()
    to_client.join()
    return server.wait()


if __name__ == "__main__":
    raise SystemExit(main())
