"""Export a shareable structural summary without copying trace payloads.

Raw wire traces can contain code, results, tokens and large image data. This
export keeps only known tool names, pseudonymous request IDs and status flags;
it deliberately removes all arguments, response text and raw frames.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

MAX_RECORD_BYTES = 2 * 1024 * 1024
INVENTORY = Path(__file__).resolve().parents[1] / "fixtures" / "tool_inventory.json"


def sanitize(source: Path, destination: Path) -> None:
    known_tools = set(json.loads(INVENTORY.read_text(encoding="utf-8"))["tools"])
    ids: dict[str, int] = {}
    with source.open("rb") as inp:
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            while chunk := inp.readline(MAX_RECORD_BYTES + 1):
                if len(chunk) > MAX_RECORD_BYTES:
                    while not chunk.endswith(b"\n"):
                        chunk = inp.readline(MAX_RECORD_BYTES + 1)
                        if not chunk:
                            break
                    out.write(json.dumps({"kind": "omitted", "reason": "oversized_record",
                                          "truncated": True, "payload_redacted": True}) + "\n")
                    continue
                try:
                    record = json.loads(chunk)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    record = None
                if not isinstance(record, dict):
                    out.write(json.dumps({"kind": "omitted", "reason": "invalid_record",
                                          "payload_redacted": True}) + "\n")
                    continue
                kind = record.get("kind")
                direction = record.get("direction")
                clean = {"kind": kind if kind in ("tool_call", "response", "request") else "other",
                         "direction": direction if direction in ("client->server", "server->client")
                         else "unknown", "payload_redacted": True}
                msg_id = record.get("id")
                if isinstance(msg_id, (str, int)) and not isinstance(msg_id, bool):
                    key = json.dumps(msg_id)
                    if key not in ids:
                        ids[key] = len(ids) + 1
                    clean["id"] = ids[key]
                if kind == "tool_call":
                    name = record.get("tool")
                    clean["tool"] = (name if isinstance(name, str) and name in known_tools
                                     else "[redacted]")
                    clean["blocked"] = record.get("blocked") is True
                if kind == "response":
                    clean["is_error"] = record.get("is_error") is True
                out.write(json.dumps(clean) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="private full trace JSONL")
    parser.add_argument("destination", type=Path, help="new sanitized JSONL file")
    args = parser.parse_args()
    sanitize(args.source, args.destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
