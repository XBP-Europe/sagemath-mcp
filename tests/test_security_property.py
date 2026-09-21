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
from sagemath_mcp.symbols import PREDEFINED_SYMBOLS


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


# --- Generated contexts, rather than a list of them -------------------------
#
# `_POSITIONS` above is seven hand-written spellings, which is the same shape
# as the enumerated path segments that item 79 had to replace: a list is only
# ever as good as what someone thought of. These build the context instead, so
# the depth and the nesting are Hypothesis's to choose.
#
# A generated program is only judged when the parsed tree really contains the
# name in a Load context. The first campaign that skipped that check reported
# `f'{{name}}'` as a bypass for an hour; it is a literal brace, and no name is
# in the program at all. Verify against the AST, never against the source text.

_EXPR_WRAPS = [
    "({})", "[{}][0]", "({},)[0]", "{{'k': {}}}['k']", "{{{}}}",
    "(lambda a={}: a)()", "(lambda: {})()", "[e for e in [{}]][0]",
    "({} if True else None)", "(None if False else {})", "[*[{}]][0]",
    "not {}", "-{}", "{}()", "{}.attr", "{}[0]", "{} + 1", "f'{{{}}}'",
    "{{**{{'a': {}}}}}['a']", "sorted([{}], key=lambda v: v)",
    "[x for x in [1] if {}][0]", "(lambda *a: a)(*[{}])",
    "(lambda **k: k)(**{{'a': {}}})",
]
_STMT_WRAPS = [
    "{}", "x = {}", "print({})", "@{}\ndef f(): pass", "class C({}): pass",
    "def f(a={}): pass", "for i in [{}]: pass", "while {}: break",
    "with {} as c: pass", "match {}:\n    case _: pass", "assert {}",
    "try:\n    pass\nexcept {}: pass", "return {}", "yield {}", "raise {}",
]


@st.composite
def _program_reading(draw: st.DrawFn, names: list[str]) -> tuple[str, str] | None:
    """A program that reads `name`, wrapped in generated context."""
    name = draw(st.sampled_from(names))
    expression = name
    for wrap in draw(st.lists(st.sampled_from(_EXPR_WRAPS), max_size=3)):
        expression = wrap.format(expression)
    return name, draw(st.sampled_from(_STMT_WRAPS)).format(expression)


def _reads_name(code: str, name: str) -> bool:
    """Does the PARSED program load `name`? The source text is not evidence."""
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError, MemoryError):
        return False
    return any(
        isinstance(node, ast.Name)
        and node.id == name
        and isinstance(node.ctx, ast.Load)
        for node in ast.walk(tree)
    )


@given(program=_program_reading(_FORBIDDEN_CALLS))
def test_a_forbidden_name_is_refused_however_it_is_wrapped(
    program: tuple[str, str],
) -> None:
    """The invariant `_POSITIONS` samples: reading a forbidden name is refused
    at any nesting, in any expression or statement context."""
    name, code = program
    if not _reads_name(code, name):
        return  # the wrapping did not actually produce a read; nothing to assert
    assert _is_refused(code), f"{code!r} slipped past the policy"


@given(name=st.sampled_from(_FORBIDDEN_CALLS))
def test_deleting_a_name_does_not_buy_the_right_to_read_it(name: str) -> None:
    """`del` was counted as a binding, and `_bound_names` walks unreachable
    code, so `if False: del eval` made `eval("1")` validate -- item 37's trap,
    closed for the `sage` root and left open for every other name. Thirteen
    names were reachable this way (REVIEW_ACTIONS 90).

    None of them executed: the namespace scrub and the restricted builtins are
    the second lock and both held. The first lock is supposed to hold too.
    """
    code = f"if False:\n    del {name}\n{name}(1)"
    assert _is_refused(code), f"{code!r} bought the allowlist exemption"


@given(name=st.sampled_from(sorted(PREDEFINED_SYMBOLS)))
def test_a_predefined_symbol_cannot_be_deleted(name: str) -> None:
    """The namespace persists between calls, so a delete outlives the request
    that made it. `symbols.py` is the single source of truth for `x, y, z, t`
    precisely because the tools and `evaluate_sage` disagreeing about which
    symbols exist is a bug class of its own."""
    assert _is_refused(f"del {name}")


@given(name=st.sampled_from(["Integer", "matrix", "sin", "QQ", "factor"]))
def test_a_name_the_server_provides_cannot_be_deleted(name: str) -> None:
    """`del Integer` made `2 + 2` fail for the rest of the session: the Sage
    preparser rewrites every integer literal to `Integer(...)`. Verified
    against a real worker before this rule was written."""
    assert _is_refused(f"del {name}")


@given(name=_IDENTS)
def test_a_caller_may_delete_what_it_created(name: str) -> None:
    """The counter-property. The rule is "you may delete what you brought",
    not "deleting is refused" -- a policy that refused every `del` would pass
    the three tests above."""
    if name in SECURITY_POLICY.allowed_names or name in PREDEFINED_SYMBOLS:
        return
    code = f"{name} = 1\ndel {name}"
    validate_module(ast.parse(code), code=code, policy=SECURITY_POLICY)


# --- The import rewriter ----------------------------------------------------
#
# `rewrite_permitted_imports` runs BEFORE validation and deletes statements,
# which makes it the one place where removing code can make a program more
# permissive rather than less. The campaign in `fuzz/fuzz_validate.py` covers
# the security question (a denied name must still be refused, whatever import
# shape surrounds it). These cover the exactness question the fuzzer cannot
# phrase: a star must expand to what was screened, and nothing else.

_LISTED_MODULES = sorted(SECURITY_POLICY.star_export_modules)


@given(module=st.sampled_from(_LISTED_MODULES))
def test_a_star_expands_to_exactly_the_screened_names(module: str) -> None:
    """The safety argument for the whole star-export mechanism is that what
    runs is exactly what `_star_export_screen` passed. If the expansion bound
    one name more, that name was never reviewed."""
    from sagemath_mcp.security import rewrite_permitted_imports

    code = f"from {module} import *"
    rewritten = rewrite_permitted_imports(
        ast.parse(code), offered=frozenset(), policy=SECURITY_POLICY
    )
    bound: set[str] = set()
    for node in ast.walk(rewritten):
        if isinstance(node, ast.alias):
            bound.add(node.asname or node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            bound.add(node.id)
    assert bound <= SECURITY_POLICY.star_export_modules[module], (
        f"expanding {module} bound names the screen never passed: "
        f"{sorted(bound - SECURITY_POLICY.star_export_modules[module])}"
    )


@given(module=_IDENTS, name=_IDENTS)
def test_an_unlisted_star_is_never_expanded(module: str, name: str) -> None:
    """Only curated modules are expanded. Anything else must be left for the
    validator to refuse, not quietly turned into bindings."""
    from sagemath_mcp.security import rewrite_permitted_imports

    target = f"sage.{module}.{name}"
    if target in SECURITY_POLICY.star_export_modules:
        return
    code = f"from {target} import *"
    rewritten = rewrite_permitted_imports(
        ast.parse(code), offered=frozenset(), policy=SECURITY_POLICY
    )
    assert any(isinstance(node, ast.ImportFrom) for node in ast.walk(rewritten)), (
        f"the star import of the unlisted {target} was rewritten away"
    )
