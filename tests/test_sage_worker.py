import ast

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
