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


def test_split_code_with_trailing_expression():
    compiled, result, namespace = _run_split("x = 6\nx * 7")
    assert compiled.is_expr is True
    assert pytest.approx(result) == 42
    assert namespace["x"] == 6


def test_split_code_without_expression():
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
