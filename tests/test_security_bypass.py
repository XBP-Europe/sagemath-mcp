"""Adversarial tests for the AST policy.

Each payload here was confirmed to escape the sandbox on a real SageMath worker
before the hardening landed: the uid probes returned 1001 and the builtins
subscript wrote a file despite `open()` being documented as blocked.

These must fail against the unhardened validator. A security test that has never
failed is not evidence of anything.
"""

from __future__ import annotations

import ast

import pytest

from sagemath_mcp.security import SECURITY_POLICY, SecurityViolation, validate_module

# (id, payload). Every one of these reached outside the sandbox.
BYPASS_PAYLOADS = [
    ("os-in-namespace", "os.getuid()"),
    ("getattr-indirection", "getattr(os, 'getuid')()"),
    ("dunder-traversal", "().__class__.__bases__[0].__subclasses__()"),
    ("builtins-attribute", "__builtins__.__import__('os').getuid()"),
    ("builtins-subscript", "__builtins__['open']('/tmp/probe', 'w').write('escaped')"),
    ("sage-eval-string", "sage_eval(\"__import__('os').getuid()\")"),
    ("attribute-chain", "sage.misc.temporary_file.os.getuid()"),
]

# The README's security table claims these are blocked wholesale.
DOCUMENTED_AS_BLOCKED = [
    ("subprocess-run", "subprocess.run(['id'])"),
    ("subprocess-popen", "subprocess.Popen(['id'])"),
    ("pathlib-read", "pathlib.Path('/etc/passwd').read_text()"),
    ("socket-open", "socket.socket()"),
    ("shutil-copy", "shutil.copy('a', 'b')"),
    ("os-listdir", "os.listdir('/')"),
    ("os-environ", "os.environ"),
    ("os-chmod", "os.chmod('a', 511)"),
    ("sys-modules", "sys.modules"),
]


def _validate(code: str) -> None:
    validate_module(ast.parse(code), code=code, policy=SECURITY_POLICY)


@pytest.mark.parametrize(
    ("case_id", "payload"), BYPASS_PAYLOADS, ids=[c for c, _ in BYPASS_PAYLOADS]
)
def test_known_bypasses_are_rejected(case_id: str, payload: str) -> None:
    with pytest.raises(SecurityViolation):
        _validate(payload)


@pytest.mark.parametrize(
    ("case_id", "payload"), DOCUMENTED_AS_BLOCKED, ids=[c for c, _ in DOCUMENTED_AS_BLOCKED]
)
def test_documented_blocks_are_actually_enforced(case_id: str, payload: str) -> None:
    """What the README promises must be what the validator does."""
    with pytest.raises(SecurityViolation):
        _validate(payload)


# Legitimate work must keep working; over-blocking would be its own outage.
ALLOWED = [
    ("arithmetic", "2 + 2"),
    ("sage-symbolics", "var('x'); integrate(sin(x), x)"),
    ("sage-import", "from sage.all import factorial\nfactorial(5)"),
    ("allowed-stdlib", "import math\nmath.sqrt(2)"),
    ("base64-io", "import base64\nimport io as _io\nbase64.b64encode(b'x')"),
    ("polynomial-ring-internals", "R = PolynomialRing(QQ, ['a', 'b']); R.gens()"),
    ("method-calls", "G = graphs.PetersenGraph(); G.chromatic_number()"),
    ("attribute-on-result", "matrix([[1,2],[3,4]]).determinant()"),
    ("comprehension", "[k**2 for k in range(5)]"),
    ("function-def", "def f(y):\n    return y + 1\nf(2)"),
]


@pytest.mark.parametrize(("case_id", "payload"), ALLOWED, ids=[c for c, _ in ALLOWED])
def test_legitimate_code_still_passes(case_id: str, payload: str) -> None:
    _validate(payload)


# Every spelling below reaches a forbidden builtin WITHOUT naming it in call
# position. The first two were reported as still exploitable after the initial
# hardening: both returned the first line of /etc/passwd, through evaluate_sage
# and through calculate_expression. Checking ast.Call.func alone is not enough --
# the name has to be rejected wherever it is referenced.
ALIASING_PAYLOADS = [
    ("alias-assignment", "f = open\nf('/etc/passwd').readline()"),
    ("lambda-default", "(lambda f=open: f('/etc/passwd').readline())()"),
    ("alias-getattr", "g = getattr\ng(os, 'getuid')()"),
    ("list-literal", "[open][0]('/etc/passwd').readline()"),
    ("tuple-literal", "(open,)[0]('/etc/passwd').read()"),
    ("dict-value", "{'k': open}['k']('/etc/passwd').read()"),
    ("comprehension", "[fn for fn in (open,)][0]('/etc/passwd').read()"),
    ("bare-reference", "open"),
    ("default-in-def", "def g(h=eval):\n    return h('1+1')\ng()"),
    ("conditional-alias", "f = open if True else print\nf('/etc/passwd')"),
    ("alias-sage-eval", "se = sage_eval\nse(\"__import__('os').getuid()\")"),
]


@pytest.mark.parametrize(
    ("case_id", "payload"), ALIASING_PAYLOADS, ids=[c for c, _ in ALIASING_PAYLOADS]
)
def test_forbidden_names_cannot_be_aliased(case_id: str, payload: str) -> None:
    with pytest.raises(SecurityViolation):
        _validate(payload)


def test_restricted_builtins_exclude_the_dangerous_ones() -> None:
    """The namespace backstop, independent of the AST rules.

    If a spelling ever slips past the validator again, the object should not be
    reachable in the first place.
    """
    from sagemath_mcp._sage_worker import _restricted_builtins

    available = _restricted_builtins()
    denied = (
        "open", "eval", "exec", "compile", "input", "globals", "locals", "vars",
    )
    for name in denied:
        assert name not in available, f"{name} is still reachable in the worker namespace"
    # Ordinary mathematics must keep working.
    # __import__ stays, and this asserts it deliberately: removing it was tried
    # for item 18 and broke Sage's Singular bindings with KeyError('__import__').
    for needed in ("abs", "len", "range", "sum", "int", "float", "print", "sorted", "__import__"):
        assert needed in available, f"{needed} was removed and normal code will break"


# Aliasing a forbidden MODULE, which the first alias fix did not cover: it
# checked forbidden call names only, so `m = os` still handed over the module.
MODULE_ALIAS_PAYLOADS = [
    ("bare module load", "os"),
    ("module alias", "m = os\nm.getuid()"),
    ("module alias via tuple", "(a, b) = (os, sys)\na.getuid()"),
    ("module in a container", "[os][0].getuid()"),
    ("module as a default", "(lambda m=os: m.getuid())()"),
    ("import-as alias", "from sage.all import os as m\nm.getuid()"),
    ("import-as under another name", "from sage.all import subprocess as sp"),
    ("sys alias", "s = sys\ns.modules"),
    ("shutil alias", "sh = shutil\nsh.rmtree('/tmp/x')"),
    ("socket alias", "sk = socket\nsk.socket()"),
    ("pathlib alias", "pl = pathlib\npl.Path('/etc/passwd').read_text()"),
    ("builtins alias", "b = builtins\nb.open('/etc/passwd')"),
]


@pytest.mark.parametrize(
    "label,payload", MODULE_ALIAS_PAYLOADS, ids=[p[0] for p in MODULE_ALIAS_PAYLOADS]
)
def test_module_aliases_are_blocked(label: str, payload: str) -> None:
    """`m = os` returned the container uid from real SageMath before this."""
    with pytest.raises(SecurityViolation):
        validate_module(ast.parse(payload), code=payload, policy=SECURITY_POLICY)


def test_forbidden_modules_are_absent_from_the_worker_namespace() -> None:
    """Second layer: even if a spelling slips past, there is nothing to bind.

    `from sage.all import *` binds os, sys and friends as ordinary globals.
    """
    from sagemath_mcp._sage_worker import _build_namespace

    namespace = _build_namespace()
    present = [
        name for name in SECURITY_POLICY.forbidden_attribute_parents if name in namespace
    ]
    assert not present, f"forbidden modules reachable in the worker namespace: {present}"


def test_specialized_tool_rejects_an_aliased_payload() -> None:
    """The public path, not just the validator.

    calculate_expression embeds its argument into generated code that runs under
    the trusted policy, so a fragment that escapes _validated_expression is not
    validated again downstream.
    """
    from fastmcp.exceptions import ToolError

    from sagemath_mcp.codegen import _validated_expression

    for payload in (
        "(lambda f=open: f('/etc/passwd').readline())()",
        "[os][0].getuid()",
        "(lambda m=os: m.getuid())()",
    ):
        with pytest.raises(ToolError, match="security policy"):
            _validated_expression(payload)


def test_unparseable_fragments_are_screened_not_waved_through() -> None:
    """A fragment that will not parse used to skip validation entirely."""
    from fastmcp.exceptions import ToolError

    from sagemath_mcp.codegen import _validated_expression

    # Still accepted: the documented equation spelling is not a Python expression.
    assert _validated_expression("x^2 - 1 = 0") == "x^2 - 1 = 0"
    # Screened at token level once no parse tree is available.
    with pytest.raises(ToolError):
        _validated_expression("R.<a> = os.getuid()")


# --- Item 18: caller strings interpolated into TRUSTED code -----------------
# Generated code runs under trusted_policy(), which re-permits sage_eval because
# the helper templates are built on it. Any caller string reaching that code
# unvalidated is therefore arbitrary execution: sage_eval evaluates a string at
# runtime, where the AST validator cannot see it. These four parameters were
# interpolated raw, and each returned the container uid from real SageMath.

TRUSTED_INTERPOLATION_PAYLOAD = "sage_eval('__import__(\"os\").getuid()')"


def _trusted_cases():
    p = TRUSTED_INTERPOLATION_PAYLOAD
    return [
        ("graph_operation.graph", "graph_operation",
         {"graph": f"CompleteGraph({p})", "operation": "order"}),
        ("graph_operation.graph literal branch", "graph_operation",
         {"graph": f"{{0:[1]}} if {p} else {{0:[1]}}", "operation": "order"}),
        ("group_operation.group", "group_operation",
         {"group": f"SymmetricGroup({p})", "operation": "order"}),
        ("coding_theory_operation.code_type", "coding_theory_operation",
         {"code_type": f"HammingCode(GF(2), {p} - 998)", "operation": "dimension"}),
        ("polynomial_ring_operation.base_ring", "polynomial_ring_operation",
         {"base_ring": f"QQ if {p} else QQ", "ring_vars": ["x"],
          "polynomials": ["x^2-1"], "operation": "ideal_dimension"}),
    ]


@pytest.mark.parametrize(
    "label,tool_name,kwargs", _trusted_cases(), ids=[c[0] for c in _trusted_cases()]
)
@pytest.mark.asyncio
async def test_trusted_templates_reject_sage_eval_payloads(
    label, tool_name, kwargs, monkeypatch
):
    """Rejected before the code is ever built, so no Sage runtime is needed."""
    from fastmcp.exceptions import ToolError

    from sagemath_mcp import runtime, server
    from sagemath_mcp.config import SageSettings
    from sagemath_mcp.session import SageSessionManager

    from .conftest import FakeContext

    manager = SageSessionManager(SageSettings(force_python_worker=True))
    monkeypatch.setattr(runtime, "SESSION_MANAGER", manager)
    tool = getattr(server, tool_name)
    try:
        with pytest.raises(ToolError, match="security policy"):
            await tool(ctx=FakeContext("trusted-interp"), **kwargs)
    finally:
        await manager.shutdown()


def test_prelude_rejects_names_that_are_not_identifiers() -> None:
    """_sage_prelude quotes each name into generated code.

    A name carrying a quote escapes that string literal, which is the same
    injection one level down.
    """
    from fastmcp.exceptions import ToolError

    from sagemath_mcp.codegen import _sage_prelude

    with pytest.raises(ToolError):
        _sage_prelude(["x', sage_eval('1+1'), 'y"])
    # Ordinary names still work.
    assert "'a'" in _sage_prelude(["a"])
