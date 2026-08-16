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
    # The import has to be *used*. A bare `import os` binds a name nothing reads,
    # and an import that would change nothing is dropped rather than refused --
    # see rewrite_permitted_imports. What must still fail is an import the
    # snippet actually depends on.
    response = _sage_worker._execute("import os\nos.getuid()", False, False, {})
    assert response["ok"] is False
    assert response["error"]["type"] in {"SecurityViolation", "ValueError"}

    # And the dropped form really does run, rather than passing by accident.
    ignored = _sage_worker._execute("import os\n2 + 2", False, False, {})
    assert ignored["ok"] is True
    assert ignored["result"] == "4"


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


def test_a_predefined_symbol_that_already_exists_is_left_alone(monkeypatch) -> None:
    """The `if symbol not in ns` guard, and the branch nothing covered.

    Real Sage already binds `x`, so the guard is what stops this server
    replacing Sage's own symbol with a freshly made one. Every unit test built a
    namespace where none of the four were present, so the guard's other edge had
    never run -- which is why the repository's 100% gate was quietly sitting at
    99.96% on one partial branch.

    Worth having beyond the number: it pins the reason the guard is written that
    way, which a reader would otherwise have to infer.
    """
    from sagemath_mcp import _sage_worker

    monkeypatch.setattr(_sage_worker, "PURE_PYTHON", False)
    monkeypatch.setattr(_sage_worker, "STARTUP_CODE", "x = 'Sage already made this'")
    monkeypatch.setattr(_sage_worker, "_STARTUP_ERROR", None)

    namespace = _sage_worker._build_namespace()

    assert namespace["x"] == "Sage already made this", "the guard overwrote Sage's own x"
    # The other three have nothing to make them from here, and the suppressed
    # failure is the point: a missing SR must not stop the namespace being built.
    assert "y" not in namespace


def test_the_denylist_derivation_resolves_lazy_imports(monkeypatch) -> None:
    """The scan that `maxima_calculus` slipped through.

    A `LazyImport` reports `sage.misc.lazy_import` as its type's module, so a
    provenance check that reads `__module__` sees the wrapper and never the
    thing wrapped. `maxima_calculus` is a `MaximaLib` behind one, which is how
    an external-CAS interface stayed reachable while every other one was
    scrubbed. The derivation now resolves them.

    Exercised here without Sage by standing in a fake `sage.all`: the real loop
    only runs when that import succeeds, so it was covered by the integration
    suite alone and by nothing in the fast one.
    """
    import importlib
    import types

    from sagemath_mcp import _sage_worker

    hidden = types.FunctionType(
        (lambda: None).__code__, {}, "unpickle_global", None, None
    )
    hidden.__module__ = "sage.misc.persist"

    class LazyImport:  # the name is what the derivation matches on
        def __init__(self, target=hidden, explodes=False):
            self._target, self._explodes = target, explodes

        def _get_object(self):
            if self._explodes:
                # SageMath 10.9 does this for `is_ProductProjectiveSpaces`:
                # resolving a lazy import can raise, and a scan that dies on one
                # broken entry stops protecting everything after it.
                raise AttributeError("module has no attribute 'is_Something'")
            return self._target

    plain = types.FunctionType((lambda: None).__code__, {}, "sh", None, None)
    plain.__module__ = "sage.misc.sh"
    innocent = types.FunctionType((lambda: None).__code__, {}, "factorial", None, None)
    innocent.__module__ = "sage.functions.other"

    fake_sage_all = types.ModuleType("sage.all")
    fake_sage_all.wrapped_danger = LazyImport()
    fake_sage_all.unresolvable = LazyImport(explodes=True)
    fake_sage_all.plain_danger = plain
    fake_sage_all.factorial = innocent

    real_import = importlib.import_module

    def only_sage_all(name, *args, **kwargs):
        if name == "sage.all":
            return fake_sage_all
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(_sage_worker.importlib, "import_module", only_sage_all)

    derived = _sage_worker._dangerous_sage_names()

    assert "wrapped_danger" in derived, "a LazyImport hid its provenance again"
    assert "plain_danger" in derived
    assert "factorial" not in derived, "ordinary mathematics must survive the scan"
    assert "unresolvable" not in derived, (
        "an entry that cannot be resolved must be skipped, not fatal"
    )


def test_an_injecting_call_hands_its_new_names_to_the_caller() -> None:
    """`R.<x> = QQ[]` is not the only way names arrive.

    `R.inject_variables()` puts the generators into the namespace, and nothing
    in the snippet's AST names them -- so without this the caller could not read
    what they had just asked for. The diff is gated on the caller having written
    an injecting call, which is what stops it trusting names that merely
    appeared.
    """
    from sagemath_mcp import _sage_worker

    class Ring:
        def __init__(self, namespace):
            self._namespace = namespace

        def inject_variables(self):
            self._namespace["injected_gen"] = 42

    namespace: dict = {"__builtins__": _sage_worker._restricted_builtins()}
    namespace["R"] = Ring(namespace)

    original = _sage_worker._STARTUP_ERROR
    _sage_worker._STARTUP_ERROR = None
    _sage_worker._CALLER_BOUND_NAMES.clear()
    try:
        response = _sage_worker._execute(
            "R.inject_variables()", want_latex=False, capture_stdout=False,
            namespace=namespace, trusted=False,
        )
    finally:
        _sage_worker._STARTUP_ERROR = original

    assert response["ok"] is True, response
    assert "injected_gen" in _sage_worker._CALLER_BOUND_NAMES, (
        "a name the caller asked to have injected must be readable afterwards"
    )
    _sage_worker._CALLER_BOUND_NAMES.clear()


def test_a_list_result_is_formatted_the_way_sage_prints_it(monkeypatch) -> None:
    """`_format_result` reaches for Sage's own list formatter, and copes without it.

    Both halves need a namespace the unit suite does not build: the formatter
    lives in `sage.repl.display.util`, and the branch is skipped entirely in
    pure-Python mode. Stood up here with a stand-in module, and with the import
    failing, because "Sage is present but that import moved" is the case the
    `except` exists for -- a result that cannot be pretty-printed must still be
    returned, not lost.
    """
    import sys
    import types

    from sagemath_mcp import _sage_worker

    monkeypatch.setattr(_sage_worker, "PURE_PYTHON", False)

    formatter = types.ModuleType("sage.repl.display.util")
    formatter.format_list = lambda value: "<tall>"
    monkeypatch.setitem(sys.modules, "sage.repl.display.util", formatter)

    class AsciiArt:
        """An element that opts into the layout, as a matrix does."""

        def _repr_option(self, key):
            return key == "ascii_art"

    # Sage only lays a sequence out in columns when an element asks for it, so
    # ordinary values are untouched however multi-line they are...
    assert _sage_worker._format_result([1, 2, 3]) == repr([1, 2, 3])
    assert _sage_worker._format_result((1, 2)) == repr((1, 2))
    assert _sage_worker._format_result([]) == "[]"

    # ...and one that asks goes through Sage's formatter.
    assert _sage_worker._format_result([AsciiArt()]) == "<tall>"
    assert _sage_worker._format_result((AsciiArt(), AsciiArt())) == "<tall>"

    # A non-sequence never goes near it.
    assert _sage_worker._format_result(42) == "42"

    # And when the import fails, the value still comes back.
    broken = types.ModuleType("sage.repl.display.util")
    monkeypatch.setitem(sys.modules, "sage.repl.display.util", broken)
    assert _sage_worker._format_result([AsciiArt()]).startswith("[<")


def test_tall_layout_is_declined_when_an_element_says_no() -> None:
    """`_wants_tall_layout` when a probe answers falsy rather than raising.

    The layout is opt-in: an element, or its parent, has to say it is ascii art
    via `_repr_option`. Existing coverage had elements that say yes (return True)
    and elements with no such method (raise AttributeError). The third case --
    an element that *has* the option and returns False -- was never exercised,
    so the branch where the first probe is falsy and the loop tries the second,
    then exhausts, went uncovered. That is the ordinary object: it answers no.
    """
    from sagemath_mcp import _sage_worker

    class Parent:
        def _repr_option(self, key):
            return False   # the parent also declines

    class Element:
        def _repr_option(self, key):
            return False   # not None and not raising -- a real "no"

        def parent(self):
            return Parent()

    assert _sage_worker._wants_tall_layout([Element(), Element()]) is False

    # And it still says yes when an element opts in, so the no-path did not
    # break the yes-path.
    class AsciiArt(Element):
        def _repr_option(self, key):
            return key == "ascii_art"

    assert _sage_worker._wants_tall_layout([Element(), AsciiArt()]) is True


def test_the_scrub_reaches_sage_all_where_sage_eval_resolves(monkeypatch) -> None:
    """`_strip_from_sage_all`, the fix that made the denylist real for tools.

    A tool wraps caller input in `sage_eval(...)`, and `sage_eval` resolves "in
    namespace of sage.all plus locals" -- not in the worker's namespace. So
    scrubbing the worker namespace left `unpickle_global` reachable through any
    generated template, which was remote code execution. This strips it from
    `sage.all` itself.

    Gated on `not PURE_PYTHON`, so the unit suite never enters it; exercised
    here with a stand-in `sage.all`. Two things it must get right: remove the
    dangerous names, and keep `sage_eval` and the other template imports, which
    live in `sage.all` and every tool depends on.
    """
    import sys
    import types

    from sagemath_mcp import _sage_worker

    # `import sage.all` needs the parent package registered too, or it fails
    # before sys.modules is consulted -- Sage is not installed in this Python.
    sage_pkg = types.ModuleType("sage")
    fake = types.ModuleType("sage.all")
    sage_pkg.all = fake
    fake.unpickle_global = lambda *a: "danger"
    fake.sage_eval = lambda *a: "needed"       # a trusted-template import
    fake.factorial = lambda n: 1               # ordinary, not asked to remove
    monkeypatch.setitem(sys.modules, "sage", sage_pkg)
    monkeypatch.setitem(sys.modules, "sage.all", fake)

    # Three shapes in one call: a dangerous name present (removed), a trusted
    # template import (skipped by name), and a dangerous name already absent
    # (nothing to delete -- the branch the earlier version left uncovered).
    removed = _sage_worker._strip_from_sage_all(
        ("unpickle_global", "sage_eval", "cython")
    )

    assert removed == 1, "only the dangerous name that was present goes"
    assert "unpickle_global" not in fake.__dict__, "the shell primitive must be gone"
    assert "sage_eval" in fake.__dict__, "the templates still need sage_eval"
    assert "factorial" in fake.__dict__, "names not asked for are left alone"


def test_the_namespace_declares_itself_main(monkeypatch):
    """Sage's `inject_variable` writes to `get_main_globals()`, which walks the
    stack for the frame whose `__name__` is `__main__`. In the REPL the user's
    namespace *is* `__main__`; in this worker the walk used to end in the worker
    script's own globals, so `S.inject_shorthands()` printed its "Defining s"
    lines and landed where no session could read them. Declaring the namespace
    to be `__main__` is Sage's own fix -- the doctest runner stamps its test
    namespace the same way (`sage/doctest/forker.py`)."""
    from sagemath_mcp import _sage_worker

    monkeypatch.setattr(_sage_worker, "PURE_PYTHON", True)
    ns = _sage_worker._build_namespace()
    assert ns["__name__"] == "__main__"


def test_guarded_attrcall_screens_the_attribute_name(monkeypatch):
    """The namespace scrub removes Sage's `attrcall` because a runtime string
    defeats every attribute rule. What comes back in its place screens the
    string at call time against the same rules, so even a validator bypass
    would buy nothing."""
    from sagemath_mcp import _sage_worker

    monkeypatch.setattr(_sage_worker, "PURE_PYTHON", True)
    key = _sage_worker._guarded_attrcall("upper")
    assert key("abc") == "ABC"
    with_arguments = _sage_worker._guarded_attrcall("replace", "a", "o")
    assert with_arguments("abc") == "obc"

    for forbidden in ("save", "save_image", "eval", "gp", "__class__", "a.b", 123):
        with pytest.raises(ValueError):
            _sage_worker._guarded_attrcall(forbidden)


def test_set_verbose_is_offered_as_a_noop(monkeypatch):
    """`set_verbose(2)` opens many doctests as setup noise. It only sets a global
    chattiness level with no surface over MCP, so it is offered as a no-op rather
    than refused -- the validator accepts it and the namespace runs it (item 64).
    """
    from sagemath_mcp import _sage_worker

    monkeypatch.setattr(_sage_worker, "PURE_PYTHON", True)
    ns = _sage_worker._build_namespace()
    result = _sage_worker._execute(
        "set_verbose(2)", want_latex=False, capture_stdout=False,
        namespace=ns, trusted=False,
    )
    assert result["ok"] is True
    assert result.get("result") is None  # a no-op returns nothing


def test_caller_shims_survive_a_reseal(monkeypatch):
    """Before item 64 the scrub removed `attrcall` and nothing put it back, so it
    worked at startup and vanished after the first specialised-tool call (which
    reseals). The shims are reinstalled after every scrub; `set_verbose` stays
    offered, `attrcall` stays withheld (screened-call-only)."""
    from sagemath_mcp import _sage_worker

    monkeypatch.setattr(_sage_worker, "PURE_PYTHON", True)
    ns = _sage_worker._build_namespace()
    assert "attrcall" in ns and "set_verbose" in ns

    _sage_worker._reseal_namespace(ns)
    assert "attrcall" in ns and "set_verbose" in ns
    assert "set_verbose" not in _sage_worker._WITHHELD_NAMES
    assert "attrcall" in _sage_worker._WITHHELD_NAMES


def test_symbol_shaped_free_names_pass_validation(monkeypatch):
    """evaluate_sage declares a symbol-shaped free name instead of refusing it,
    so validation accepts `w` and reports it as auto-declared (item 65)."""
    from sagemath_mcp import _sage_worker

    monkeypatch.setattr(_sage_worker, "PURE_PYTHON", True)
    compiled = _sage_worker._split_code("w + 1")
    assert "w" in compiled.auto_symbols
    # A multi-letter name is not symbol-shaped: a typo stays an error.
    with pytest.raises(SecurityViolation):
        _sage_worker._split_code("sinn(x)")


def test_symbol_auto_declaration_does_not_shadow_a_session_variable(monkeypatch):
    """A name the caller already assigned is offered as their value, not turned
    into a fresh symbol -- so `w` stays whatever the session set it to."""
    from sagemath_mcp import _sage_worker

    monkeypatch.setattr(_sage_worker, "PURE_PYTHON", True)
    monkeypatch.setattr(_sage_worker, "_CALLER_BOUND_NAMES", {"w"})
    compiled = _sage_worker._split_code(
        "w + 1", session_names=_sage_worker._CALLER_BOUND_NAMES
    )
    assert "w" not in compiled.auto_symbols


def test_symbol_auto_declaration_computes_and_respects_session():
    """End to end on real Sage: an undeclared `w` becomes a symbol and computes;
    a `w` the session already set to a number stays that number (item 65)."""
    pytest.importorskip("sage.all")
    from sagemath_mcp import _sage_worker

    ns = _sage_worker._build_namespace()
    ok = _sage_worker._execute(
        "expand((w + 1)^2)", want_latex=False, capture_stdout=False,
        namespace=ns, trusted=False,
    )
    assert ok["ok"] is True and ok["result"] == "w^2 + 2*w + 1"

    # Now the caller pins w to a number; the next read must keep it, not resymbol.
    _sage_worker._execute("w = 5", want_latex=False, capture_stdout=False,
                          namespace=ns, trusted=False)
    pinned = _sage_worker._execute("w + 1", want_latex=False, capture_stdout=False,
                                   namespace=ns, trusted=False)
    assert pinned["ok"] is True and pinned["result"] == "6"

    # A multi-letter typo is still refused, not silently turned into a symbol.
    typo = _sage_worker._execute("sinn(x)", want_latex=False, capture_stdout=False,
                                 namespace=_sage_worker._build_namespace(), trusted=False)
    assert typo["ok"] is False


def test_guarded_attrcall_delegates_to_sage_when_available(monkeypatch):
    import sys
    import types

    from sagemath_mcp import _sage_worker

    real = types.SimpleNamespace(
        attrcall=lambda name, *args, **kwds: ("sage-attrcall", name, args, kwds)
    )
    monkeypatch.setitem(sys.modules, "sage", types.SimpleNamespace(misc=None))
    monkeypatch.setitem(sys.modules, "sage.misc", types.SimpleNamespace(call=real))
    monkeypatch.setitem(sys.modules, "sage.misc.call", real)
    monkeypatch.setattr(_sage_worker, "PURE_PYTHON", False)
    assert _sage_worker._guarded_attrcall("degree", 2) == (
        "sage-attrcall", "degree", (2,), {},
    )


def test_attrcall_is_usable_end_to_end_in_a_session(monkeypatch):
    """Validation exempts the screened call, the namespace holds the guarded
    wrapper, and the result is the caller's to bind and reuse -- the whole
    interplay, in one flow."""
    from sagemath_mcp import _sage_worker

    monkeypatch.setattr(_sage_worker, "PURE_PYTHON", True)
    namespace = _sage_worker._build_namespace()

    original = _sage_worker._STARTUP_ERROR
    _sage_worker._STARTUP_ERROR = None
    try:
        response = _sage_worker._execute(
            "key = attrcall('upper')\nkey('abc')",
            want_latex=False, capture_stdout=False,
            namespace=namespace, trusted=False,
        )
    finally:
        _sage_worker._STARTUP_ERROR = original

    assert response["ok"] is True, response
    assert response["result"] == "'ABC'"


def test_an_inject_shorthands_call_hands_its_new_names_to_the_caller() -> None:
    """The sibling of `test_an_injecting_call_hands_its_new_names_to_the_caller`:
    `S.inject_shorthands()` earns the same namespace diff, now that the names
    actually land (see `test_the_namespace_declares_itself_main`)."""
    from sagemath_mcp import _sage_worker

    class Symmetric:
        def __init__(self, namespace):
            self._namespace = namespace

        def inject_shorthands(self):
            self._namespace["s_basis"] = 42

    namespace: dict = {"__builtins__": _sage_worker._restricted_builtins()}
    namespace["S"] = Symmetric(namespace)

    original = _sage_worker._STARTUP_ERROR
    _sage_worker._STARTUP_ERROR = None
    _sage_worker._CALLER_BOUND_NAMES.clear()
    try:
        response = _sage_worker._execute(
            "S.inject_shorthands()", want_latex=False, capture_stdout=False,
            namespace=namespace, trusted=False,
        )
    finally:
        _sage_worker._STARTUP_ERROR = original

    assert response["ok"] is True, response
    assert "s_basis" in _sage_worker._CALLER_BOUND_NAMES, (
        "a name the caller asked to have injected must be readable afterwards"
    )


def test_star_export_screen_accepts_a_clean_module(monkeypatch):
    """A module whose public names are all ordinary values is vetted whole."""
    import sys
    import types

    from sagemath_mcp import _sage_worker

    clean = types.ModuleType("fake.clean")
    clean.__all__ = ["Widget", "gadget"]
    clean.Widget = type("Widget", (), {})
    clean.gadget = lambda: None
    clean.Widget.__module__ = "fake.clean"
    clean.gadget.__module__ = "fake.clean"
    monkeypatch.setitem(sys.modules, "fake.clean", clean)

    screened = _sage_worker._star_export_screen("fake.clean")
    assert screened == frozenset({"Widget", "gadget"})


def test_star_export_screen_rejects_a_module_with_any_dangerous_name(monkeypatch):
    """Clean-modules-only: one bad export excludes the whole module, so a screen
    that misses a category still cannot leak from a listed module."""
    import sys
    import types

    from sagemath_mcp import _sage_worker

    dirty = types.ModuleType("fake.dirty")
    dirty.__all__ = ["Widget", "save_thing"]  # save* is a forbidden prefix
    dirty.Widget = type("Widget", (), {})
    dirty.Widget.__module__ = "fake.dirty"
    dirty.save_thing = lambda: None
    dirty.save_thing.__module__ = "fake.dirty"
    monkeypatch.setitem(sys.modules, "fake.dirty", dirty)

    assert _sage_worker._star_export_screen("fake.dirty") is None


def test_star_export_screen_rejects_a_re_exported_dangerous_object(monkeypatch):
    """`from sage.matroids.advanced import *` re-exports `lazy_import`, whose
    home is a dangerous module even though the name is defined elsewhere."""
    import sys
    import types

    from sagemath_mcp import _sage_worker

    reexport = types.ModuleType("fake.reexport")
    reexport.__all__ = ["Widget", "borrowed"]
    reexport.Widget = type("Widget", (), {})
    reexport.Widget.__module__ = "fake.reexport"
    reexport.borrowed = lambda: None
    # Home is one of the dangerous modules.
    reexport.borrowed.__module__ = _sage_worker._DANGEROUS_SAGE_MODULES[0]
    monkeypatch.setitem(sys.modules, "fake.reexport", reexport)

    assert _sage_worker._star_export_screen("fake.reexport") is None


def test_star_export_screen_drops_a_re_exported_module_object(monkeypatch):
    """A module object handed back by a star import is a pivot, and is DROPPED
    from the screened names rather than failing the whole module.

    `sage.modular.dims` re-exported the `sage.modular.dirichlet` module, which
    reaches `sage.env.os`; binding it let a caller pivot to the real `os` (the
    item 61 escape). Item 61 failed the whole module for it, which cost the
    mathematics in `real_roots`/`dims`/`pbori` for a single module object. Item
    63 drops the module-object name instead: the expansion binds only the
    screened names, so a dropped name is never imported, and item 62 refuses the
    pivot at the validator even if one were. The math names survive; the module
    does not. A re-export whose NAME is a forbidden parent (`operator`, `sage`)
    is dropped too, which is why the type check runs before the name screens.
    """
    import sys
    import types

    from sagemath_mcp import _sage_worker

    pivot = types.ModuleType("fake.pivot")
    # `operator` is both a module object AND a forbidden-parent name: it must be
    # dropped by the type check before the name screen can fail the module.
    pivot.__all__ = ["Widget", "submodule", "operator"]
    pivot.Widget = type("Widget", (), {})
    pivot.Widget.__module__ = "fake.pivot"
    pivot.submodule = types.ModuleType("some.other.module")
    pivot.operator = types.ModuleType("operator")
    monkeypatch.setitem(sys.modules, "fake.pivot", pivot)

    screened = _sage_worker._star_export_screen("fake.pivot")
    assert screened == frozenset({"Widget"})
    assert "submodule" not in screened
    assert "operator" not in screened


def test_star_export_screen_still_fails_whole_for_a_non_module_danger(monkeypatch):
    """Only module objects are dropped; every other danger still fails the module
    whole, so clean-as-a-whole holds for everything a bound value can reach."""
    import sys
    import types

    from sagemath_mcp import _sage_worker

    dirty = types.ModuleType("fake.stilldirty")
    dirty.__all__ = ["Widget", "submodule", "save_thing"]  # save* is a write prefix
    dirty.Widget = type("Widget", (), {})
    dirty.Widget.__module__ = "fake.stilldirty"
    dirty.submodule = types.ModuleType("some.other.module")  # dropped
    dirty.save_thing = lambda: None                          # fails the module
    dirty.save_thing.__module__ = "fake.stilldirty"
    monkeypatch.setitem(sys.modules, "fake.stilldirty", dirty)

    assert _sage_worker._star_export_screen("fake.stilldirty") is None


def test_star_export_screen_returns_none_for_an_unimportable_module():
    from sagemath_mcp import _sage_worker

    assert _sage_worker._star_export_screen("nope.not.a.module") is None


def test_star_export_screen_reads_dir_when_all_is_absent(monkeypatch):
    """Without `__all__`, `import *` binds every non-underscore name, so the
    screen enumerates the same way."""
    import sys
    import types

    from sagemath_mcp import _sage_worker

    mod = types.ModuleType("fake.noall")
    mod.Public = type("Public", (), {})
    mod.Public.__module__ = "fake.noall"
    mod._private = 1
    monkeypatch.setitem(sys.modules, "fake.noall", mod)

    assert _sage_worker._star_export_screen("fake.noall") == frozenset({"Public"})


def test_star_export_screen_rejects_a_forbidden_export_name(monkeypatch):
    """A name on the policy's forbidden lists excludes the module even without a
    write-prefix or a dangerous home."""
    import sys
    import types

    from sagemath_mcp import _sage_worker

    mod = types.ModuleType("fake.forbidden")
    mod.__all__ = ["eval"]  # forbidden_attribute_only_names
    mod.eval = lambda: None
    mod.eval.__module__ = "fake.forbidden"
    monkeypatch.setitem(sys.modules, "fake.forbidden", mod)

    assert _sage_worker._star_export_screen("fake.forbidden") is None


def test_star_export_screen_rejects_a_malformed_all_entry(monkeypatch):
    """A module whose `__all__` lists something that is not a plain public
    identifier is not one this screen will vouch for."""
    import sys
    import types

    from sagemath_mcp import _sage_worker

    mod = types.ModuleType("fake.malformed")
    mod.__all__ = ["_private"]
    monkeypatch.setitem(sys.modules, "fake.malformed", mod)
    assert _sage_worker._star_export_screen("fake.malformed") is None
