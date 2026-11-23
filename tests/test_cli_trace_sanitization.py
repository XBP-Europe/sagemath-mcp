"""Sanitized exports never copy raw tool payloads into shareable traces."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests.cli_integration import sanitize_trace


def test_sanitizer_redacts_payloads_and_preserves_correlated_status(tmp_path: Path) -> None:
    source = tmp_path / "raw.jsonl"
    destination = tmp_path / "share.jsonl"
    records = [
        {"kind": "tool_call", "direction": "client->server", "tool": "evaluate_sage",
         "id": "secret-session-id", "arguments": "SECRET_ARGUMENT",
         "frame": {"secret": "SECRET_FRAME"}},
        {"kind": "response", "direction": "server->client", "id": "secret-session-id",
         "is_error": True, "preview": "SECRET_RESULT", "frame": {"token": "SECRET_TOKEN"}},
        {"kind": "tool_call", "direction": "client->server", "tool": "SECRET_UNKNOWN_TOOL",
         "id": "other-id", "blocked": True, "blocked_reply": {"error": "SECRET_REPLY"}},
    ]
    source.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    before = source.read_bytes()
    sanitize_trace.sanitize(source, destination)
    output = destination.read_text()
    assert "SECRET" not in output and "secret-session-id" not in output
    clean = [json.loads(line) for line in output.splitlines()]
    assert clean[0]["tool"] == "evaluate_sage" and clean[0]["id"] == clean[1]["id"]
    assert clean[1]["is_error"] and clean[2]["tool"] == "[redacted]" and clean[2]["blocked"]
    assert all(row["payload_redacted"] for row in clean)
    assert source.read_bytes() == before
    if os.name != "nt":
        assert destination.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        sanitize_trace.sanitize(source, destination)
    assert destination.read_text() == output


def test_sanitizer_labels_oversized_and_malformed_records(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(sanitize_trace, "MAX_RECORD_BYTES", 50)
    source = tmp_path / "raw.jsonl"
    source.write_bytes(b'{"secret":"' + b'x' * 100 + b'"}\nnot-json\n')
    dest = tmp_path / "share.jsonl"
    sanitize_trace.sanitize(source, dest)
    records = [json.loads(line) for line in dest.read_text().splitlines()]
    assert [r["reason"] for r in records] == ["oversized_record", "invalid_record"]
    assert records[0]["truncated"] and all(r["payload_redacted"] for r in records)
    assert "secret" not in dest.read_text()
