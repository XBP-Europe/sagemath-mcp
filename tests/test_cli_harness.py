"""Tests for the extended CLI harness's verdict logic.

The harness is what decides whether a real-CLI run passed, so its own bugs are
invisible: a broken rule shows up as a green suite. These run without any CLI,
by feeding it wire logs directly.

Two rules matter and pull in opposite directions. A model inventing an argument
is not a server fault -- the server rejects it, the model retries, and the case
should still pass. But excluding those failures cannot be allowed to mean a case
passes with no successful tool call at all, which is exactly what happened: the
tool stayed in the "called" list, so a malformed failed call plus a
plausible-looking answer was a PASS.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.cli_integration.extended_cases import ToolForcingCase
from tests.cli_integration.run_extended import evaluate, read_wire_log

CASE = ToolForcingCase(
    id="unit-case",
    domain="test",
    prompt="irrelevant",
    expected_answers=["42"],
    accepted_tools=["combinatorics_operation"],
)


def _log(tmp_path: Path, records: list[dict]) -> Path:
    path = tmp_path / "wire.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
    return path


def _call(call_id: int, tool: str = "combinatorics_operation") -> dict:
    return {"kind": "tool_call", "id": call_id, "tool": tool}


def _response(call_id: int, *, is_error: bool = False, preview: str = "{}") -> dict:
    return {"kind": "response", "id": call_id, "is_error": is_error, "preview": preview}


def test_a_case_needs_a_tool_call_that_actually_answered(tmp_path: Path) -> None:
    """The regression: one malformed, failed call plus a good-looking answer.

    This returned PASS. The call was excluded from the failures as a client
    fault, but still counted as the accepted tool having been used.
    """
    log = _log(tmp_path, [
        _call(1),
        _response(1, is_error=True,
                  preview="1 validation error for call[combinatorics_operation] "
                          "wait_for_previous Unexpected keyword argument"),
    ])
    result = evaluate(CASE, "the answer is 42", log, 1.0, "gemini")
    assert result.status != "PASS", "passed without any tool call succeeding"
    assert "no tool actually answered" in result.detail


def test_a_recovered_client_fault_still_passes(tmp_path: Path) -> None:
    """The behaviour that rule protects: model retries, server answers."""
    log = _log(tmp_path, [
        _call(1),
        _response(1, is_error=True,
                  preview="1 validation error for call[combinatorics_operation] "
                          "wait_for_previous Unexpected keyword argument"),
        _call(2),
        _response(2, preview='{"result": "42"}'),
    ])
    result = evaluate(CASE, "the answer is 42", log, 1.0, "gemini")
    assert result.status == "PASS", result.detail


def test_a_real_server_error_still_fails(tmp_path: Path) -> None:
    """A security violation or dead worker is our problem, not the model's."""
    log = _log(tmp_path, [
        _call(1),
        _response(1, is_error=True,
                  preview="SecurityViolation: Reference to forbidden name 'open' is blocked"),
        _call(2),
        _response(2, preview='{"result": "42"}'),
    ])
    result = evaluate(CASE, "the answer is 42", log, 1.0, "claude")
    assert result.status == "TOOL_ERROR", result.detail


def test_the_wrong_answer_still_fails_even_with_a_successful_call(tmp_path: Path) -> None:
    log = _log(tmp_path, [_call(1), _response(1, preview='{"result": "41"}')])
    result = evaluate(CASE, "the answer is 41", log, 1.0, "codex")
    assert result.status == "WRONG_ANSWER", result.detail


def test_calling_no_accepted_tool_fails(tmp_path: Path) -> None:
    log = _log(tmp_path, [
        _call(1, tool="evaluate_sage"),
        _response(1, preview='{"result": "42"}'),
    ])
    result = evaluate(CASE, "the answer is 42", log, 1.0, "codex")
    assert result.status == "NO_TOOL_CALL", result.detail


@pytest.mark.parametrize(
    "preview,is_client_fault",
    [
        ("1 validation error ... Unexpected keyword argument", True),
        ("Input should be a valid integer", True),
        ("field required", True),
        ("SecurityViolation: blocked", False),
        ("Sage worker terminated unexpectedly.", False),
    ],
)
def test_client_faults_are_told_apart_from_server_faults(
    tmp_path: Path, preview: str, is_client_fault: bool
) -> None:
    log = _log(tmp_path, [_call(1), _response(1, is_error=True, preview=preview)])
    _tools, errored, succeeded = read_wire_log(log)
    assert (not errored) is is_client_fault
    assert not succeeded


def test_a_missing_wire_log_reports_no_tool_call(tmp_path: Path) -> None:
    """The proxy may never have been reached at all.

    read_wire_log's early exit for a missing file kept returning two values
    after the third was added, so this path raised a ValueError from unpacking
    instead of reporting that nothing was called -- a crash in the code that
    decides whether a run passed.
    """
    missing = tmp_path / "never-written.jsonl"
    assert read_wire_log(missing) == ([], set(), [])

    result = evaluate(CASE, "the answer is 42", missing, 1.0, "claude")
    assert result.status == "NO_TOOL_CALL", result.detail
