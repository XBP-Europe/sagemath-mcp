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
