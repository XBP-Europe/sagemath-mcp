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


def test_a_recovered_mathematics_error_still_passes(tmp_path: Path) -> None:
    """Sage refusing the mathematics is not the server failing.

    Watched against the real thing: asked for the Bose-Einstein integral, Claude
    tried the symbolic form, got an unevaluated `limit(...)` that `N()` cannot
    reduce, and switched to `numerical_integral`. That is a session working, and
    it used to be reported as TOOL_ERROR -- so the harness failed the case with
    the right answer on screen and nothing wrong with the server.
    """
    log = _log(tmp_path, [
        _call(1),
        _response(1, is_error=True,
                  preview="TypeError: cannot evaluate symbolic expression numerically"),
        _call(2),
        _response(2, preview='{"result": "42"}'),
    ])
    result = evaluate(CASE, "the answer is 42", log, 1.0, "claude")
    assert result.status == "PASS", result.detail


def test_a_mathematics_error_with_no_recovery_still_fails(tmp_path: Path) -> None:
    """Tolerating the error is not the same as tolerating the case.

    Nothing answered, so there is no evidence the server works -- which is the
    property the whole suite exists to check.
    """
    log = _log(tmp_path, [
        _call(1),
        _response(1, is_error=True, preview="RuntimeError: Brent's method failed"),
    ])
    result = evaluate(CASE, "the answer is 42", log, 1.0, "claude")
    assert result.status == "NO_TOOL_CALL", result.detail
    assert "no tool actually answered" in result.detail


def test_a_refusal_is_never_excused_as_mathematics(tmp_path: Path) -> None:
    """The over-block this suite is meant to catch must stay fatal.

    A model that is refused, retries a different spelling and succeeds looks
    exactly like a model recovering from a divergent integral. It is not: the
    first is a defect in this server's policy, and it is precisely the kind that
    a security suite full of refusal assertions cannot see.
    """
    for preview in (
        "SecurityViolation: Access to dunder name '__tmp__' is blocked",
        "SecurityViolation: 'foo' is not a name this server offers",
        "Sage worker terminated unexpectedly.",
        "Evaluation timed out after 30s",
    ):
        log = _log(tmp_path, [
            _call(1),
            _response(1, is_error=True, preview=preview),
            _call(2),
            _response(2, preview='{"result": "42"}'),
        ])
        result = evaluate(CASE, "the answer is 42", log, 1.0, "claude")
        assert result.status == "TOOL_ERROR", f"{preview!r} was excused: {result.detail}"


def test_a_declined_answer_is_reported_as_dodged(tmp_path: Path) -> None:
    """Two failures that want different fixes should not share a name."""
    log = _log(tmp_path, [_call(1), _response(1, preview='{"result": "?"}')])
    result = evaluate(CASE, "I cannot compute that without more information", log, 1.0, "codex")
    assert result.status == "DODGED", result.detail


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
    _tools, errored, succeeded, _tolerated = read_wire_log(log)
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
    assert read_wire_log(missing) == ([], {}, [], [])

    result = evaluate(CASE, "the answer is 42", missing, 1.0, "claude")
    assert result.status == "NO_TOOL_CALL", result.detail


def test_running_no_cases_for_a_selected_cli_is_a_failure(monkeypatch, capsys) -> None:
    """Registration failure must not look like success.

    run_extended catches the CalledProcessError from `mcp add`, prints a note and
    continues; with no CaseResult recorded it then reported "0/0 passed" and
    exited 0. The nightly went green exactly when the CLI could not reach the
    server. Missing credentials are a different path -- those legs never start
    the runner at all.
    """
    import subprocess

    from tests.cli_integration import run_extended

    def registration_fails(cli, log_path):
        raise subprocess.CalledProcessError(1, ["gemini", "mcp", "add"], stderr="unknown flag")

    monkeypatch.setattr(run_extended, "register", registration_fails)
    monkeypatch.setattr(run_extended, "unregister", lambda cli: None)
    monkeypatch.setattr(run_extended.sys, "argv", ["run_extended", "--cli", "gemini"])

    assert run_extended.main() == 1, "a CLI that ran no cases reported success"
    assert "ran no cases" in capsys.readouterr().out


# --- Docker Compose is spelled two ways ---------------------------------------
# v2 is a docker plugin (`docker compose`); v1 is a separate binary
# (`docker-compose`) that reached end of life in 2023. Code hardcoding either one
# breaks on half the machines out there, and this repository had both spellings
# in different places -- CI on v2, the harness and the CI simulation on v1.


def test_compose_prefers_the_v2_plugin(monkeypatch) -> None:
    import subprocess

    from tests.cli_integration import cli_config

    monkeypatch.setattr(
        cli_config.subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 0, b"v2.29.0", b""),
    )
    monkeypatch.setattr(cli_config.shutil, "which", lambda name: "/usr/bin/docker-compose")
    assert cli_config.compose_command() == ["docker", "compose"]


def test_compose_falls_back_to_the_v1_binary(monkeypatch) -> None:
    import subprocess

    from tests.cli_integration import cli_config

    monkeypatch.setattr(
        cli_config.subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 1, b"", b"unknown command"),
    )
    monkeypatch.setattr(cli_config.shutil, "which", lambda name: "/usr/bin/docker-compose")
    assert cli_config.compose_command() == ["docker-compose"]


def test_compose_reports_none_when_neither_is_installed(monkeypatch) -> None:
    from tests.cli_integration import cli_config

    def no_docker(*args, **kwargs):
        raise FileNotFoundError("docker")

    monkeypatch.setattr(cli_config.subprocess, "run", no_docker)
    monkeypatch.setattr(cli_config.shutil, "which", lambda name: None)
    assert cli_config.compose_command() is None


def test_a_missing_compose_says_so_instead_of_a_filenotfound(monkeypatch) -> None:
    """The old message was 'docker-compose up failed: FileNotFoundError'."""
    from tests.cli_integration import cli_config

    monkeypatch.setattr(cli_config, "_docker_container_running", lambda: False)
    monkeypatch.setattr(cli_config, "compose_command", lambda: None)
    with pytest.raises(RuntimeError, match="no Docker Compose was found"):
        cli_config.ensure_docker_container()


def test_a_bare_division_by_zero_is_not_excused(tmp_path: Path) -> None:
    """The one marker that named no Sage subsystem.

    Every other entry in the mathematics-fault list quotes a message only Sage
    produces -- "brent's method failed", "integral is divergent". "division by
    zero" quoted nothing: it is a phrase, and a phrase matches whatever contains
    it. Sage's own spellings are all qualified (`rational division by zero`,
    `symbolic division by zero`, `power::eval(): division by zero`), so the
    marker can be too, and an unqualified one goes back to being a server fault.

    This does not separate a server defect from mathematics the model asked for
    -- both raise ZeroDivisionError and neither says whose fault it is. What
    keeps the suppression honest is the rule below it: nothing passes without a
    tool call that succeeded *and* the expected answer.
    """
    log = _log(tmp_path, [
        _call(1),
        _response(1, is_error=True, preview="ZeroDivisionError: division by zero"),
        _call(2),
        _response(2, preview='{"result": "42"}'),
    ])
    result = evaluate(CASE, "the answer is 42", log, 1.0, "claude")
    assert result.status == "TOOL_ERROR", result.detail


def test_a_qualified_division_by_zero_is_still_excused(tmp_path: Path) -> None:
    """Sage's actual message, which is the case the marker is for."""
    log = _log(tmp_path, [
        _call(1),
        _response(1, is_error=True, preview="ZeroDivisionError: rational division by zero"),
        _call(2),
        _response(2, preview='{"result": "42"}'),
    ])
    result = evaluate(CASE, "the answer is 42", log, 1.0, "claude")
    assert result.status == "PASS", result.detail


def test_tolerated_faults_are_reported_rather_than_swallowed(tmp_path: Path) -> None:
    """A suppressed error nobody sees is how a masked regression survives.

    Tolerating the model's failed attempts is right, and discarding them is not:
    a run that says PASS with nothing else on screen looks identical whether the
    session was clean or took four goes to get there. The count rides along in
    the detail so a person reading the log can tell.
    """
    log = _log(tmp_path, [
        _call(1),
        _response(1, is_error=True, preview="RuntimeError: integral is divergent"),
        _call(2),
        _response(2, is_error=True, preview="ZeroDivisionError: rational division by zero"),
        _call(3),
        _response(3, preview='{"result": "42"}'),
    ])
    result = evaluate(CASE, "the answer is 42", log, 1.0, "claude")
    assert result.status == "PASS", result.detail
    assert "2 tolerated" in result.detail, result.detail
