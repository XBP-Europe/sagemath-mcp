"""Property-based checks on the AST security policy.

The hand-written corpus in ``test_security_bypass.py`` catches the escapes we
have already thought of. These assert the *invariants* those escapes are
instances of, over inputs Hypothesis generates -- every forbidden name in every
referencing position, an arbitrary attribute on every forbidden module, any
import at all -- so a weakening of a rule is caught even where no one wrote the
specific case. They are also what raises the mutation score of ``security.py``:
a mutant that flips an ``in`` to a ``not in`` or drops a rule fails a property
here even when every enumerated example still passes.
"""

from __future__ import annotations

import ast
import keyword

from hypothesis import given
from hypothesis import strategies as st

from sagemath_mcp.security import SECURITY_POLICY, SecurityViolation, validate_module


def _is_refused(code: str) -> bool:
    try:
        validate_module(ast.parse(code), code=code, policy=SECURITY_POLICY)
        return False
    except SecurityViolation:
        return True


_FORBIDDEN_CALLS = sorted(SECURITY_POLICY.forbidden_call_names)
# `operator` is the one forbidden parent with a permitted subset (operator.le,
# operator.add, ...), so an arbitrary attribute on it is not universally refused.
_FORBIDDEN_PARENTS = sorted(set(SECURITY_POLICY.forbidden_attribute_parents) - {"operator"})
# Short identifiers that are not the empty string and cannot be a dunder. Python
# keywords (`as`, `or`, `if`) are filtered out: they make the generated code a
# SyntaxError rather than a policy question, which is not what these test.
_IDENTS = st.from_regex(r"[a-zA-Z][a-zA-Z0-9_]{0,7}", fullmatch=True).filter(
    lambda s: not keyword.iskeyword(s)
)
# Every syntactic position a name can be *read* in -- call, bare load, alias,
# container, lambda default, comprehension. Each defeated a naive check once.
_POSITIONS = [
    "{n}()",
    "{n}",
    "x = {n}",
    "[{n}][0]",
    "({n},)[0]",
    "(lambda a={n}: a)()",
    "[e for e in ({n},)][0]",
]


@given(name=st.sampled_from(_FORBIDDEN_CALLS), template=st.sampled_from(_POSITIONS))
def test_a_forbidden_name_is_refused_in_every_position(name: str, template: str) -> None:
    code = template.format(n=name)
    assert _is_refused(code), f"{code!r} slipped past the policy"


@given(parent=st.sampled_from(_FORBIDDEN_PARENTS), attr=_IDENTS)
def test_any_attribute_on_a_forbidden_module_is_refused(parent: str, attr: str) -> None:
    assert _is_refused(f"{parent}.{attr}"), f"{parent}.{attr} slipped past the policy"


@given(module=_IDENTS, name=_IDENTS)
def test_every_import_is_refused(module: str, name: str) -> None:
    assert _is_refused(f"import {module}")
    assert _is_refused(f"from {module} import {name}")


@given(attr=st.from_regex(r"[a-z][a-z0-9_]{0,6}", fullmatch=True))
def test_any_dunder_access_is_refused(attr: str) -> None:
    # A literal base, so the dunder rule -- not the name allowlist -- is what fires.
    assert _is_refused(f"().__{attr}__"), f"().__{attr}__ slipped past the policy"


@given(
    a=st.integers(min_value=-10_000, max_value=10_000),
    b=st.integers(min_value=1, max_value=10_000),
    op=st.sampled_from(["+", "-", "*", "//", "%", "**"]),
)
def test_plain_arithmetic_is_never_refused(a: int, b: int, op: str) -> None:
    """The counter-property: a policy that refused everything would pass every
    test above. Ordinary arithmetic must go through untouched."""
    code = f"({a}) {op} ({b})"
    validate_module(ast.parse(code), code=code, policy=SECURITY_POLICY)


@given(
    name=st.sampled_from(["x", "y", "z", "t"]),
    fn=st.sampled_from(["sin", "cos", "sqrt", "exp", "log"]),
)
def test_predefined_symbols_and_offered_functions_are_allowed(name: str, fn: str) -> None:
    code = f"{fn}({name})"
    validate_module(ast.parse(code), code=code, policy=SECURITY_POLICY)
