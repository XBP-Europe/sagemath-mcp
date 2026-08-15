import ast
import io
import json
import sys
import types

import pytest

from sagemath_mcp._sage_worker import _split_code
from sagemath_mcp.security import SECURITY_POLICY, SecurityViolation


def _run_split(code: str):
    compiled = _split_code(code)
    namespace: dict[str, object] = {"__builtins__": __builtins__}
    exec(compile(compiled.prefix, "<test>", "exec"), namespace)
    result = None
    if compiled.is_expr and compiled.tail is not None:
        result = eval(compile(compiled.tail, "<test>", "eval"), namespace)
    return compiled, result, namespace


def test_split_code_with_trailing_expression(pure_python_worker):
    compiled, result, namespace = _run_split("x = 6\nx * 7")
    assert compiled.is_expr is True
    assert pytest.approx(result) == 42
    assert namespace["x"] == 6


def test_split_code_without_expression(pure_python_worker):
    compiled, result, _ = _run_split("total = sum(range(3))")
    assert compiled.is_expr is False
    assert compiled.tail is None
    assert result is None


def test_split_code_preserves_type_ignores():
    code = "value: list[int] = []  # type: ignore[assignment]\nvalue"
    compiled, result, _ = _run_split(code)
    reference_module = ast.parse(code, mode="exec", type_comments=True)
    prefix_ignores = [
        (ignore.lineno, getattr(ignore, "tag", None))
        for ignore in getattr(compiled.prefix, "type_ignores", [])
    ]
    reference_ignores = [
        (ignore.lineno, getattr(ignore, "tag", None))
        for ignore in getattr(reference_module, "type_ignores", [])
    ]
    assert prefix_ignores == reference_ignores
    assert result == []


def test_split_code_blocks_forbidden_import():
    if SECURITY_POLICY.allow_imports:
        pytest.skip("Policy permits imports; skipping security test")
    with pytest.raises(SecurityViolation):
        _split_code("import os\nos.system('echo unsafe')")


def test_main_handles_multiple_messages(tmp_path, monkeypatch):
    from sagemath_mcp import _sage_worker

    monkeypatch.setenv("SAGEMATH_MCP_PURE_PYTHON", "1")
    monkeypatch.setenv("SAGEMATH_MCP_STARTUP", "from math import *")
    monkeypatch.setattr(_sage_worker, "STARTUP_CODE", "from math import *")
    monkeypatch.setattr(_sage_worker, "PURE_PYTHON", True)

    commands = [
        json.dumps({"type": "execute", "id": "1", "code": "1+1"}),
        json.dumps({"type": "reset", "id": "2"}),
        json.dumps({"type": "foo", "id": "3"}),
        "not-json",
        json.dumps({"type": "shutdown", "id": "4"}),
        "",
    ]
    input_data = "\n".join(commands) + "\n"
    monkeypatch.setattr(_sage_worker.sys, "stdin", io.StringIO(input_data))

    captured = io.StringIO()
    monkeypatch.setattr(_sage_worker.sys, "stdout", captured)

    exit_code = _sage_worker._main()
    assert exit_code == 0

    outputs = []
    for line in captured.getvalue().splitlines():
        outputs.append(json.loads(line))
    assert outputs
    assert outputs[0]["ok"] is True
    assert outputs[0]["id"] == "1"
    assert outputs[1] == {"ok": True, "id": "2"}
    assert outputs[2]["error"]["type"] == "ValueError"
    assert outputs[3]["error"]["type"] == "JSONDecodeError"


def test_execute_returns_error_on_validation_failure(monkeypatch):
    from sagemath_mcp import _sage_worker

    monkeypatch.setenv("SAGEMATH_MCP_PURE_PYTHON", "1")
    monkeypatch.setattr(_sage_worker, "PURE_PYTHON", True)
    response = _sage_worker._execute("import os", False, False, {})
    assert response["ok"] is False
    assert response["error"]["type"] in {"SecurityViolation", "ValueError"}


def test_latex_handles_none(monkeypatch):
    from sagemath_mcp import _sage_worker

    assert _sage_worker._latex(None) is None

    # Exercise PURE_PYTHON branch with a stub sympy module
    fake_sympy = types.SimpleNamespace(latex=lambda value: str(value))
    monkeypatch.setitem(sys.modules, "sympy", fake_sympy)
    monkeypatch.setattr(_sage_worker, "PURE_PYTHON", True)
    assert _sage_worker._latex(2) == "2"

    # Exercise Sage branch by mocking sage.all.latex
    fake_sage_all = types.SimpleNamespace(latex=lambda value: f"latex({value})")
    fake_sage = types.SimpleNamespace(all=fake_sage_all)
    monkeypatch.setitem(sys.modules, "sage", fake_sage)
    monkeypatch.setitem(sys.modules, "sage.all", fake_sage_all)
    monkeypatch.setattr(_sage_worker, "PURE_PYTHON", False)
    assert _sage_worker._latex(3) == "latex(3)"


def test_build_namespace_without_preload(monkeypatch):
    from sagemath_mcp import _sage_worker

    monkeypatch.setattr(_sage_worker, "PURE_PYTHON", False)
    monkeypatch.setattr(_sage_worker, "STARTUP_CODE", "")
    ns = _sage_worker._build_namespace()
    assert ns["__builtins__"]


def test_execute_statement_only(monkeypatch):
    from sagemath_mcp import _sage_worker

    monkeypatch.setattr(_sage_worker, "PURE_PYTHON", True)
    response = _sage_worker._execute("value = 3", False, False, {})
    assert response["ok"] is True
    assert response["result_type"] == "statement"
    assert response["result"] is None


def test_main_returns_zero_on_exhausted_input(monkeypatch):
    from sagemath_mcp import _sage_worker

    monkeypatch.setattr(_sage_worker.sys, "stdin", io.StringIO("   \n"))
    monkeypatch.setattr(_sage_worker.sys, "stdout", io.StringIO())
    monkeypatch.setenv("SAGEMATH_MCP_PURE_PYTHON", "1")
    monkeypatch.setattr(_sage_worker, "PURE_PYTHON", True)
    exit_code = _sage_worker._main()
    assert exit_code == 0


def test_execute_with_want_latex(monkeypatch):
    """Test that want_latex=True produces a non-None latex field."""
    from sagemath_mcp import _sage_worker

    monkeypatch.setattr(_sage_worker, "PURE_PYTHON", True)
    monkeypatch.setattr(_sage_worker, "_STARTUP_ERROR", None)

    # Stub _latex to return a known value
    monkeypatch.setattr(_sage_worker, "_latex", lambda result: f"\\mathrm{{{result}}}")

    ns: dict[str, object] = {"__builtins__": __builtins__}
    response = _sage_worker._execute("2 + 3", True, False, ns)
    assert response["ok"] is True
    assert response["result_type"] == "expression"
    assert response["result"] == "5"
    assert response["latex"] == "\\mathrm{5}"


def test_execute_with_want_latex_false(monkeypatch):
    """Test that want_latex=False skips LaTeX generation."""
    from sagemath_mcp import _sage_worker

    monkeypatch.setattr(_sage_worker, "PURE_PYTHON", True)
    monkeypatch.setattr(_sage_worker, "_STARTUP_ERROR", None)

    ns: dict[str, object] = {"__builtins__": __builtins__}
    response = _sage_worker._execute("2 + 3", False, False, ns)
    assert response["ok"] is True
    assert response["latex"] is None


def test_execute_reports_startup_error(monkeypatch):
    """Test that _execute returns an error when startup code failed."""
    from sagemath_mcp import _sage_worker

    monkeypatch.setattr(_sage_worker, "_STARTUP_ERROR", "Startup code failed: boom")

    ns: dict[str, object] = {"__builtins__": __builtins__}
    response = _sage_worker._execute("1 + 1", False, False, ns)
    assert response["ok"] is False
    assert response["error"]["type"] == "StartupError"
    assert "boom" in response["error"]["message"]

    # Reset for other tests
    monkeypatch.setattr(_sage_worker, "_STARTUP_ERROR", None)


def test_build_namespace_logs_startup_failure(monkeypatch, capsys):
    """Test that _build_namespace captures startup errors."""
    from sagemath_mcp import _sage_worker

    monkeypatch.setattr(_sage_worker, "PURE_PYTHON", False)
    monkeypatch.setattr(_sage_worker, "STARTUP_CODE", "raise RuntimeError('test fail')")
    _sage_worker._build_namespace()
    assert _sage_worker._STARTUP_ERROR is not None
    assert "test fail" in _sage_worker._STARTUP_ERROR

    # Reset
    monkeypatch.setattr(_sage_worker, "_STARTUP_ERROR", None)


# ---------------------------------------------------------------------------
# The streaming stdout buffer
# ---------------------------------------------------------------------------


class _Sink:
    """Stands in for the real stdout the worker captured before redirection."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def write(self, text: str) -> int:
        if text.strip():
            self.lines.append(text.strip())
        return len(text)

    def flush(self) -> None:
        return None


def _events(sink: _Sink) -> list[dict]:
    return [json.loads(line) for line in sink.lines]


def test_streaming_stdout_emits_one_event_per_completed_line() -> None:
    """The point of streaming: a line is emitted when it completes, not at the end."""
    from sagemath_mcp._sage_worker import _StreamingStdout

    sink = _Sink()
    buffer = _StreamingStdout("req-1", sink)
    buffer.write("first\nsecond\n")

    assert [e["text"] for e in _events(sink)] == ["first", "second"]
    assert {e["type"] for e in _events(sink)} == {"stdout"}
    assert {e["id"] for e in _events(sink)} == {"req-1"}
    # The full text is still available for the final response.
    assert buffer.getvalue() == "first\nsecond\n"


def test_streaming_stdout_holds_a_partial_line_until_it_completes() -> None:
    from sagemath_mcp._sage_worker import _StreamingStdout

    sink = _Sink()
    buffer = _StreamingStdout("req-2", sink)
    buffer.write("half ")
    assert sink.lines == [], "a partial line was emitted before it ended"
    buffer.write("done\n")
    assert [e["text"] for e in _events(sink)] == ["half done"]


def test_streaming_stdout_flush_emits_a_trailing_line_without_a_newline() -> None:
    """print(..., end='') would otherwise be lost entirely."""
    from sagemath_mcp._sage_worker import _StreamingStdout

    sink = _Sink()
    buffer = _StreamingStdout("req-3", sink)
    buffer.write("no newline here")
    buffer.flush()
    assert [e["text"] for e in _events(sink)] == ["no newline here"]
    # A second flush has nothing left to send.
    buffer.flush()
    assert len(sink.lines) == 1


def test_execute_streams_while_it_runs(pure_python_worker) -> None:
    from sagemath_mcp._sage_worker import _build_namespace, _execute

    sink = _Sink()
    original = sys.stdout
    sys.stdout = sink
    try:
        response = _execute(
            "for _i in range(3):\n    print(_i)\n",
            want_latex=False,
            capture_stdout=True,
            namespace=_build_namespace(),
            stream_id="stream-1",
        )
    finally:
        sys.stdout = original

    assert response["ok"] is True
    assert [e["text"] for e in _events(sink)] == ["0", "1", "2"]
    assert response["stdout"] == "0\n1\n2\n"


def test_interrupting_a_computation_keeps_the_session_alive(pure_python_worker) -> None:
    """SIGINT means abandon this computation, not lose the namespace.

    KeyboardInterrupt is a BaseException, so without an explicit handler the
    worker would exit and take every variable with it -- the opposite of what
    interrupting is for.
    """
    from sagemath_mcp import _sage_worker
    from sagemath_mcp._sage_worker import _build_namespace, _execute

    namespace = _build_namespace()
    namespace["_boom"] = _raise_keyboard_interrupt
    # A name injected straight into the namespace is not one the allowlist knows
    # or that validated code bound, so record it the way a real session would.
    _sage_worker._CALLER_BOUND_NAMES.add("_boom")

    response = _execute(
        "_boom()", want_latex=False, capture_stdout=True, namespace=namespace
    )
    assert response["ok"] is False
    assert response["error"]["type"] == "Interrupted"
    assert "preserved" in response["error"]["message"]


def _raise_keyboard_interrupt():
    raise KeyboardInterrupt


def test_execute_reports_a_startup_failure_instead_of_running(monkeypatch) -> None:
    """A worker whose preload failed must say so, not evaluate against a broken namespace."""
    from sagemath_mcp import _sage_worker

    monkeypatch.setattr(_sage_worker, "_STARTUP_ERROR", "Startup code failed: boom")
    response = _sage_worker._execute(
        "2 + 2", want_latex=False, capture_stdout=True, namespace={}
    )
    assert response["ok"] is False
    assert response["error"]["type"] == "StartupError"
    assert "boom" in response["error"]["message"]


def test_an_interrupt_while_idle_does_not_kill_the_worker(
    monkeypatch, capsys, pure_python_worker
) -> None:
    """SIGINT can land between requests, where there is nothing to cancel.

    Letting KeyboardInterrupt escape the read would end the process and take the
    namespace with it, which is exactly what interrupting must not do.
    """
    from sagemath_mcp import _sage_worker

    script = [
        KeyboardInterrupt,                                    # arrives while idle
        json.dumps({"id": "a", "type": "execute", "code": "2 + 2",
                    "want_latex": False, "capture_stdout": False}) + "\n",
        "",                                                   # EOF ends the loop
    ]

    def fake_readline():
        step = script.pop(0)
        if step is KeyboardInterrupt:
            raise KeyboardInterrupt
        return step

    monkeypatch.setattr(_sage_worker.sys.stdin, "readline", fake_readline)
    assert _sage_worker._main() == 0

    responses = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert responses[-1]["result"] == "4", "the worker did not survive the idle interrupt"


def test_caller_code_is_preparsed_but_generated_code_is_not(monkeypatch) -> None:
    """Sage semantics for callers; untouched Python for our own templates.

    Preparsing a server-generated template would change what it means -- the
    caret lint exists precisely because those run as plain Python -- so the
    split is load-bearing rather than an optimisation. Verified with a stub, so
    no Sage runtime is needed.
    """
    from sagemath_mcp import _sage_worker

    seen: list[str] = []

    class _FakePreparseModule:
        @staticmethod
        def preparse(code: str) -> str:
            seen.append(code)
            return code.replace("^", "**")

    monkeypatch.setattr(_sage_worker, "PURE_PYTHON", False)
    monkeypatch.setitem(sys.modules, "sage.repl.preparse", _FakePreparseModule)
    monkeypatch.setitem(sys.modules, "sage.repl", types.ModuleType("sage.repl"))
    monkeypatch.setitem(sys.modules, "sage", types.ModuleType("sage"))

    caller = _sage_worker._split_code("2^3", trusted=False)
    assert seen == ["2^3"], "caller code was not preparsed"
    assert ast.unparse(caller.tail) == "2 ** 3"

    seen.clear()
    _sage_worker._split_code("_x = 2\n_x", trusted=True)
    assert seen == [], "a generated template was preparsed"


def test_preparsing_is_skipped_without_a_sage_runtime(monkeypatch) -> None:
    """The import failing must degrade to plain Python, not break evaluation."""
    from sagemath_mcp import _sage_worker

    monkeypatch.setattr(_sage_worker, "PURE_PYTHON", False)
    monkeypatch.setitem(sys.modules, "sage.repl.preparse", None)
    assert _sage_worker._preparse("2^3") == "2^3"


def test_x_is_predefined_when_sage_is_present(monkeypatch) -> None:
    """Sage's REPL predefines x; importing sage.all does not."""
    from sagemath_mcp import _sage_worker

    monkeypatch.setattr(_sage_worker, "PURE_PYTHON", False)
    monkeypatch.setattr(
        _sage_worker,
        "STARTUP_CODE",
        "class _SR:\n"
        "    def var(self, name):\n"
        "        return f'symbol:{name}'\n"
        "SR = _SR()\n",
    )
    namespace = _sage_worker._build_namespace()
    assert namespace["x"] == "symbol:x"


def test_x_is_not_invented_in_pure_python_mode(pure_python_worker) -> None:
    """The shim has no symbolic ring, so there is no x to define."""
    from sagemath_mcp._sage_worker import _build_namespace

    assert "x" not in _build_namespace()
