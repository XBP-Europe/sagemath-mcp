import pytest

from sagemath_mcp.security import SecurityViolation, validate_code


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
