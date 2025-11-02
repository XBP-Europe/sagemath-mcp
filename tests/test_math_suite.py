import ast
import math
import uuid

import pytest

from sagemath_mcp.config import SageSettings
from sagemath_mcp.security import SECURITY_POLICY
from sagemath_mcp.session import SageEvaluationError, SageSession


@pytest.fixture(scope="module")
def python_settings():
    return SageSettings(
        sage_binary="sage",
        startup_code="from math import *",
        eval_timeout=5.0,
        idle_ttl=10.0,
        shutdown_grace=1.0,
        max_stdout_chars=1000,
        force_python_worker=True,
    )


@pytest.fixture(autouse=True)
def pure_python_env(monkeypatch):
    monkeypatch.setenv("SAGEMATH_MCP_PURE_PYTHON", "1")


async def _evaluate_expression(session: SageSession, expr: str) -> float:
    result = await session.evaluate(expr, want_latex=False, capture_stdout=False)
    assert result.result_type == "expression"
    assert result.result is not None
    return ast.literal_eval(result.result)


@pytest.mark.asyncio
async def test_trigonometric_functions(python_settings):
    session = SageSession(f"math-trig-{uuid.uuid4().hex}", python_settings)
    try:
        cases = [
            ("sin(0)", math.sin(0)),
            ("sin(pi / 2)", math.sin(math.pi / 2)),
            ("sin(pi)", 0.0),
            ("cos(0)", math.cos(0)),
            ("cos(pi)", math.cos(math.pi)),
            ("tan(pi / 4)", math.tan(math.pi / 4)),
            ("asin(1)", math.asin(1)),
            ("acos(0)", math.acos(0)),
            ("atan(1)", math.atan(1)),
            ("atan2(1, 1)", math.atan2(1, 1)),
        ]
        for expr, expected in cases:
            value = await _evaluate_expression(session, expr)
            assert value == pytest.approx(expected, rel=1e-12, abs=1e-12)
    finally:
        await session.shutdown()


@pytest.mark.asyncio
async def test_security_policy_blocks_insecure_code(python_settings):
    if SECURITY_POLICY.allow_imports:
        pytest.skip("Security policy allows imports in this environment")
    session = SageSession(f"math-sec-{uuid.uuid4().hex}", python_settings)
    try:
        with pytest.raises(SageEvaluationError) as excinfo:
            await session.evaluate(
                "import os\nos.system('echo hello')",
                want_latex=False,
                capture_stdout=False,
            )
        assert excinfo.value.error_type == "SecurityViolation"
    finally:
        await session.shutdown()


@pytest.mark.asyncio
async def test_logarithmic_and_power_functions(python_settings):
    session = SageSession(f"math-log-{uuid.uuid4().hex}", python_settings)
    try:
        cases = [
            ("log(e)", 1.0),
            ("log10(1000)", math.log10(1000)),
            ("log2(8)", math.log2(8)),
            ("exp(1)", math.e),
            ("exp2(5)", math.pow(2, 5)),
            ("expm1(1e-6)", math.expm1(1e-6)),
            ("sqrt(49)", 7.0),
            ("pow(5, 3)", math.pow(5, 3)),
            ("hypot(3, 4)", math.hypot(3, 4)),
        ]
        for expr, expected in cases:
            value = await _evaluate_expression(session, expr)
            assert value == pytest.approx(expected, rel=1e-12, abs=1e-12)
    finally:
        await session.shutdown()


@pytest.mark.asyncio
async def test_combinatorics_and_factorials(python_settings):
    session = SageSession(f"math-combo-{uuid.uuid4().hex}", python_settings)
    try:
        cases = [
            ("factorial(6)", math.factorial(6)),
            ("comb(10, 3)", math.comb(10, 3)),
            ("perm(7, 2)", math.perm(7, 2)),
        ]
        for expr, expected in cases:
            value = await _evaluate_expression(session, expr)
            assert value == pytest.approx(expected, rel=1e-12, abs=1e-12)
    finally:
        await session.shutdown()


@pytest.mark.asyncio
async def test_stateful_session_and_stdout_capture(python_settings):
    session = SageSession(f"math-state-{uuid.uuid4().hex}", python_settings)
    try:
        assignment = await session.evaluate(
            "total = 21", want_latex=False, capture_stdout=False
        )
        assert assignment.result_type == "statement"
        result = await _evaluate_expression(session, "total * 2")
        assert result == 42

        captured = await session.evaluate(
            "print('ready'); total", want_latex=False, capture_stdout=True
        )
        assert captured.stdout.strip() == "ready"
        assert captured.result is not None
        assert ast.literal_eval(captured.result) == 21
    finally:
        await session.shutdown()
