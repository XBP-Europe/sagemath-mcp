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


def test_caller_code_may_not_import_even_from_sage():
    """`sage.*` was allowlisted for the generated prelude, and callers used it to
    re-import everything the worker namespace scrub had removed."""
    with pytest.raises(SecurityViolation):
        validate_code("from sage.all import sin")


def test_generated_code_may_import_what_its_templates_need():
    import ast

    from sagemath_mcp.security import trusted_policy, validate_module

    code = "from sage.all import sin\n1"
    validate_module(ast.parse(code), code=code, policy=trusted_policy())


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


def test_trusted_policy_relaxes_only_the_three_evaluation_entry_points() -> None:
    """The trusted policy is what makes the helper templates work.

    It must give back sage_eval, preparse and sage_input -- every template is
    built on sage_eval -- and nothing else. If it relaxed more, generated code
    could reach open() or getattr() directly.
    """
    from sagemath_mcp.security import SECURITY_POLICY, trusted_policy

    relaxed = trusted_policy()
    gained = set(SECURITY_POLICY.forbidden_call_names) - set(relaxed.forbidden_call_names)
    assert gained == {"sage_eval", "preparse", "sage_input"}

    # Everything else about the policy is untouched.
    assert relaxed.forbidden_attribute_parents == SECURITY_POLICY.forbidden_attribute_parents
    assert relaxed.allow_imports == SECURITY_POLICY.allow_imports
    for still_blocked in ("open", "eval", "exec", "getattr", "__import__"):
        assert still_blocked in relaxed.forbidden_call_names


def test_trusted_policy_accepts_an_explicit_base_policy() -> None:
    from dataclasses import replace

    from sagemath_mcp.security import SECURITY_POLICY, trusted_policy

    base = replace(SECURITY_POLICY, max_ast_nodes=11)
    assert trusted_policy(base).max_ast_nodes == 11


def test_a_forbidden_attribute_chain_stops_at_the_first_offending_segment() -> None:
    """The loop breaks after raising; this pins the message to the real cause."""
    import ast

    from sagemath_mcp.security import SECURITY_POLICY, SecurityViolation, validate_module

    # Now stopped a segment earlier: temporary_file is itself forbidden, since
    # sage's own sub-packages are how callers reached compilers and shells.
    code = "sage.misc.temporary_file.os.sys.path"
    with pytest.raises(SecurityViolation, match="'temporary_file'"):
        validate_module(ast.parse(code), code=code, policy=SECURITY_POLICY)


def test_relative_imports_are_rejected_by_name() -> None:
    """`from . import x` has no module, so the allowlist has nothing to check."""
    import ast

    from sagemath_mcp.security import SECURITY_POLICY, SecurityViolation, validate_module

    code = "from . import something"
    with pytest.raises(SecurityViolation, match="Relative imports"):
        validate_module(ast.parse(code), code=code, policy=SECURITY_POLICY)


def test_validation_is_silent_when_violation_logging_is_off() -> None:
    """log_violations also gates the success line, not just the failures."""
    import ast
    from dataclasses import replace

    from sagemath_mcp.security import SECURITY_POLICY, validate_module

    quiet = replace(SECURITY_POLICY, log_violations=False)
    code = "2 + 2"
    assert validate_module(ast.parse(code), code=code, policy=quiet) is None
