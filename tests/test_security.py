import logging

import pytest

from sagemath_mcp.security import (
    SecurityPolicy,
    SecurityViolation,
    _bool_env,
    _format_violation,
    _int_env,
    _tuple_env,
    validate_code,
)


def test_validate_code_blocks_forbidden_import():
    with pytest.raises(SecurityViolation):
        validate_code("import os\nos.system('echo hi')")


def test_validate_code_allows_whitelisted_imports():
    # sage imports are explicitly allowed by default policy
    validate_code("from sage.all import sin")


def test_validate_code_blocks_global_and_nonlocal():
    with pytest.raises(SecurityViolation):
        validate_code("global x\nx = 1")

    code = """
def outer():
    value = 0
    def inner():
        nonlocal value
        value = 1
    inner()
"""
    with pytest.raises(SecurityViolation):
        validate_code(code)


def test_validate_code_blocks_forbidden_attribute_call():
    with pytest.raises(SecurityViolation):
        validate_code("os.system('shutdown')")


def test_validate_code_blocks_forbidden_function():
    with pytest.raises(SecurityViolation):
        validate_code("result = eval('2 + 2')")


def test_custom_policy_allows_imports():
    policy = SecurityPolicy(allow_imports=True)
    validate_code("import math\nmath.sqrt(4)", policy=policy)


def test_validate_module_logs_violation(caplog):
    policy = SecurityPolicy(log_violations=True)
    caplog.set_level(logging.WARNING)
    with pytest.raises(SecurityViolation):
        validate_code("import os", policy=policy)
    assert any("Blocked Sage code" in record.message for record in caplog.records)


# --- env helper coverage ---


def test_bool_env_returns_value_when_set(monkeypatch):
    monkeypatch.setenv("TEST_BOOL", "true")
    assert _bool_env("TEST_BOOL", False) is True
    monkeypatch.setenv("TEST_BOOL", "0")
    assert _bool_env("TEST_BOOL", True) is False


def test_int_env_returns_parsed_value(monkeypatch):
    monkeypatch.setenv("TEST_INT", "42")
    assert _int_env("TEST_INT", 0) == 42


def test_tuple_env_returns_parsed_values(monkeypatch):
    monkeypatch.setenv("TEST_TUPLE", "a, b ,c")
    assert _tuple_env("TEST_TUPLE", ()) == ("a", "b", "c")


def test_tuple_env_returns_default_for_empty(monkeypatch):
    monkeypatch.setenv("TEST_TUPLE", "  ,  ,  ")
    assert _tuple_env("TEST_TUPLE", ("fallback",)) == ("fallback",)


# --- format_violation coverage ---


def test_format_violation_without_code():
    assert _format_violation("error msg", None) == "error msg"
    assert _format_violation("error msg", "") == "error msg"


def test_format_violation_with_code():
    result = _format_violation("error msg", "import os\nos.system('x')")
    assert "snippet:" in result


# --- AST size/depth limit coverage ---


def test_validate_code_blocks_oversized_source():
    policy = SecurityPolicy(max_source_chars=10)
    with pytest.raises(SecurityViolation, match="maximum length"):
        validate_code("x = 1 + 2 + 3 + 4 + 5", policy=policy)


def test_validate_code_blocks_too_many_ast_nodes():
    policy = SecurityPolicy(max_ast_nodes=5)
    with pytest.raises(SecurityViolation, match="AST node count"):
        validate_code("a = 1\nb = 2\nc = 3\nd = 4\ne = 5", policy=policy)


def test_validate_code_blocks_deep_ast():
    policy = SecurityPolicy(max_ast_depth=3)
    with pytest.raises(SecurityViolation, match="AST depth"):
        validate_code("x = ((((1 + 2) + 3) + 4) + 5)", policy=policy)


# --- relative import coverage ---


def test_validate_code_blocks_relative_import():
    with pytest.raises(SecurityViolation, match="Relative imports"):
        validate_code("from . import something")


# --- disabled security ---


def test_validate_code_passes_when_disabled():
    policy = SecurityPolicy(enabled=False)
    validate_code("import os; os.system('whoami')", policy=policy)


# --- policy from_env coverage ---


def test_security_policy_from_env(monkeypatch):
    monkeypatch.setenv("SAGEMATH_MCP_SECURITY_ENABLED", "false")
    monkeypatch.setenv("SAGEMATH_MCP_SECURITY_MAX_SOURCE", "100")
    monkeypatch.setenv("SAGEMATH_MCP_SECURITY_ALLOWED_IMPORTS", "numpy,pandas")
    policy = SecurityPolicy.from_env()
    assert policy.enabled is False
    assert policy.max_source_chars == 100
    assert "numpy" in policy.allowed_import_modules


def test_format_violation_with_blank_lines_only():
    """Cover line 162: code with only whitespace lines."""
    result = _format_violation("error msg", "   \n   \n   ")
    assert result == "error msg"


def test_raise_violation_without_logging():
    """Cover branch 169->171: log_violations=False."""
    policy = SecurityPolicy(log_violations=False)
    with pytest.raises(SecurityViolation):
        validate_code("import os", policy=policy)


def test_validate_code_debug_log_on_success(caplog):
    """Cover line 264->exit: debug log emitted on successful validation."""
    policy = SecurityPolicy(log_violations=True)
    caplog.set_level(logging.DEBUG)
    validate_code("x = 1 + 2", policy=policy)
    assert any("validation passed" in record.message for record in caplog.records)
