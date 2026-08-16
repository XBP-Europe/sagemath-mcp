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


def test_global_and_nonlocal_are_both_permitted():
    """Neither reaches anything an ordinary assignment does not.

    `nonlocal` rebinds inside an enclosing *function*, so it never touches the
    namespace. `global` does bind at module scope, which is why it was held back
    a round -- and the round found that `SR = 5` is permitted at the top level
    anyway, so the declaration cannot be what makes it dangerous. What the two
    rules upstream of it guarantee is asserted in
    `test_a_global_declaration_reaches_nothing` next door.

    Both were refused by policy flags with no comment, no recorded rationale and
    no test named for either, and the cost was the accumulator.
    """
    validate_code("total = 0\ndef add(n):\n    global total\n    total += n")

    closure = """
def outer():
    value = 0
    def inner():
        nonlocal value
        value = 1
    inner()
    return value
"""
    validate_code(closure)

    # The accumulator a mathematician actually writes.
    counting = """
def collatz_lengths(limit):
    longest = 0
    def record(n):
        nonlocal longest
        longest = max(longest, n)
    for start in range(1, limit):
        record(start)
    return longest
"""
    validate_code(counting)


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
    for still_blocked in ("open", "exec", "getattr", "__import__"):
        assert still_blocked in relaxed.forbidden_call_names

    # `eval` moved to the attribute-only list -- the bare name reaches nothing
    # (absent from builtins, namespace and allowlist), while `latex.eval()` runs
    # the LaTeX toolchain. Generated code must not reach that either.
    assert relaxed.forbidden_attribute_only_names == (
        SECURITY_POLICY.forbidden_attribute_only_names
    )
    assert "eval" in relaxed.forbidden_attribute_only_names


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


def test_the_input_limits_admit_a_pasted_matrix():
    """The limits bound parse cost; they should not refuse a matrix.

    At 8,000 characters and 2,500 nodes they did: a 40x40 integer matrix written
    out is 17,706 characters and 6,497 nodes, and that is the shape someone
    pastes into a session. Both had to move -- raising the character limit alone
    would have left the node limit refusing a 25x25.

    Measured on SageMath 10.9, preparse + parse + validate costs about 1.1us per
    character, linearly, so the limits chosen here cap one request at roughly
    140ms of parsing. Execution is bounded separately by eval_timeout.
    """
    import ast as ast_module

    from sagemath_mcp.security import SECURITY_POLICY

    # Written the way the *preparser* leaves it, because that is what the
    # validator sees and what the limits apply to. Sage wraps every integer
    # literal as `Integer(0)`, which turns a 3,306-character matrix into 17,706
    # and one node per entry into four -- the expansion is the whole reason the
    # old limits refused a matrix that looked comfortably small when typed.
    for size, chars, nodes in ((40, 17_706, 6_497), (100, 110_226, 40_217)):
        rows = ",".join(
            "[" + ",".join(f"Integer({(i * j) % 7})" for j in range(size)) + "]"
            for i in range(size)
        )
        source = f"M = matrix(ZZ, [{rows}])\nM.rank()"
        assert len(source) <= SECURITY_POLICY.max_source_chars, (
            f"a {size}x{size} matrix is {len(source)} characters, over the limit"
        )
        module = ast_module.parse(source)
        walked = sum(1 for _ in ast_module.walk(module))
        assert walked <= SECURITY_POLICY.max_ast_nodes, (
            f"a {size}x{size} matrix is {walked} nodes, over the limit"
        )
        # And it passes the policy end to end, not merely the size checks.
        validate_code(source)
        assert abs(len(source) - chars) < chars * 0.1
        assert abs(walked - nodes) < nodes * 0.2

    # The limits still exist: something an order of magnitude larger is refused.
    huge = "x = [" + ",".join(str(i) for i in range(200_000)) + "]"
    with pytest.raises(SecurityViolation):
        validate_code(huge)


# --- session-level name injection (the sweep's model of a running session) -----


def test_the_session_injection_flag_suspends_only_the_allowlist_half():
    """A session where an earlier call ran `R.inject_variables()` holds names
    no static analysis of the *current* snippet can know. The worker records
    the real ones by diffing the namespace around the injecting call; a static
    observer (the doctest sweep) cannot, so it passes ``session_injects_names``
    and gets the same suspension the injecting snippet itself gets: names that
    are not live at all are either the injected ones or a NameError."""
    import ast

    from sagemath_mcp.security import validate_module

    module = ast.parse("mystery_name + 1")
    with pytest.raises(SecurityViolation):
        validate_module(module, code="mystery_name + 1")
    validate_module(module, code="mystery_name + 1", session_injects_names=True)


def test_the_session_injection_flag_does_not_unlock_withheld_names():
    """The withheld half is the half with the security content: a name that is
    live in the namespace and deliberately not offered stays refused whatever
    a session has injected."""
    import ast

    from sagemath_mcp.security import validate_module

    module = ast.parse("smuggled")
    with pytest.raises(SecurityViolation):
        validate_module(
            module,
            code="smuggled",
            withheld_names=frozenset({"smuggled"}),
            session_injects_names=True,
        )


def test_inject_shorthands_counts_as_a_name_injection():
    """`S.inject_shorthands()` injects the basis shorthands the way
    `R.inject_variables()` injects generators. It used to be excluded because
    nothing landed in the worker's namespace -- Sage routes it through
    `get_main_globals()` -- and the worker now declares its namespace to be
    `__main__`, which is where that routing ends up."""
    import ast

    from sagemath_mcp.security import validate_module

    code = "S.inject_shorthands()\nzz + 1"
    module = ast.parse(code)
    validate_module(module, code=code, extra_allowed_names=frozenset({"S"}))

    # The sibling without the injection stays refused: the suspension is earned
    # by the call, not by the spelling of any method.
    plain = "S.shorthands()\nzz + 1"
    with pytest.raises(SecurityViolation):
        validate_module(
            ast.parse(plain), code=plain, extra_allowed_names=frozenset({"S"})
        )


# --- attrcall with a screened literal ------------------------------------------


def test_attrcall_with_a_screened_literal_is_accepted():
    """`attrcall('partial_sums')` is idiomatic Sage -- 155 uses in SageMath's
    own doctests, every one with a harmless literal. The string is right there
    in the AST, so it is screened against the same attribute rules the dotted
    spelling would face; what stays refused is the dynamic form, which is the
    form that defeats attribute rules."""
    import ast

    from sagemath_mcp.security import validate_module

    for code in (
        "attrcall('partial_sums')",
        "key = attrcall('degree')",
        "sorted(P, key=attrcall('length'))",
        "attrcall('conjugate')",
    ):
        validate_module(
            ast.parse(code), code=code, extra_allowed_names=frozenset({"P"})
        )


@pytest.mark.parametrize(
    "code",
    [
        # The literal fails the attribute screen.
        "attrcall('save')",
        "attrcall('save_image')",
        "attrcall('eval')",
        "attrcall('gp')",
        "attrcall('__class__')",
        "attrcall('a.b')",
        # No literal to screen.
        "name = 'degree'\nattrcall(name)",
        "attrcall()",
        "parts = ['degree']\nattrcall(*parts)",
        "attrcall(name='degree')",
        "attrcall(**{'name': 'degree'})",
        # The primitive itself stays unreadable outside the screened call.
        "f = attrcall",
        "x = 1\nx.attrcall('degree')",
    ],
    ids=[
        "save", "save-image", "eval", "gp", "dunder", "dotted-path",
        "variable", "no-args", "starred", "keyword", "double-star",
        "alias", "attribute-spelling",
    ],
)
def test_attrcall_stays_refused_outside_the_screen(code: str):
    import ast

    from sagemath_mcp.security import validate_module

    with pytest.raises(SecurityViolation):
        validate_module(ast.parse(code), code=code)


# --- vetted star imports -------------------------------------------------------

import dataclasses  # noqa: E402

from sagemath_mcp.security import (  # noqa: E402
    SECURITY_POLICY,
    rewrite_permitted_imports,
    validate_module,
)


def _policy_with_star(mapping):
    return dataclasses.replace(SECURITY_POLICY, star_export_modules=mapping)


_STAR = {"my.safe.module": frozenset({"SafeThing", "helper", "other"})}


def test_a_vetted_star_import_is_expanded_to_its_screened_names():
    """`from <vetted> import *` becomes the explicit screened list before
    validation, so what runs is exactly what was reviewed and the names bind
    the way any explicit import binds."""
    import ast

    policy = _policy_with_star(_STAR)
    module = ast.parse("from my.safe.module import *\nSafeThing()")
    rewritten = rewrite_permitted_imports(
        module, offered=frozenset(), policy=policy
    )
    imports = [n for n in ast.walk(rewritten) if isinstance(n, ast.ImportFrom)]
    assert imports, "the star import was dropped, not expanded"
    names = sorted(alias.name for alias in imports[0].names)
    assert names == ["SafeThing", "helper", "other"]
    assert not any(alias.name == "*" for alias in imports[0].names)
    # And the expanded module validates: the import is permitted and the name
    # it brought in is readable.
    validate_module(rewritten, code="from my.safe.module import *\nSafeThing()",
                    policy=policy)


def test_a_vetted_module_permits_only_its_screened_names_explicitly():
    """A caller may also name the members directly. The screened ones pass; a
    name the screen dropped -- or would drop -- does not, so a dirty member of
    an otherwise-listed module cannot be smuggled in by spelling it out."""
    import ast

    policy = _policy_with_star(_STAR)
    ok = "from my.safe.module import SafeThing, helper"
    validate_module(ast.parse(ok), code=ok, policy=policy)

    bad = "from my.safe.module import SafeThing, not_screened"
    with pytest.raises(SecurityViolation):
        validate_module(ast.parse(bad), code=bad, policy=policy)


def test_an_unvetted_star_import_is_still_refused():
    import ast

    policy = _policy_with_star(_STAR)
    for code in (
        "from sage.misc.explain_pickle import *",
        "from os import *",
        "from my.other.module import *",
    ):
        module = rewrite_permitted_imports(
            ast.parse(code), offered=frozenset(), policy=policy
        )
        with pytest.raises(SecurityViolation):
            validate_module(module, code=code, policy=policy)


def test_a_vetted_import_still_cannot_re_export_a_forbidden_root():
    """The alias-root guard runs regardless: even inside a listed module, a
    name that collides with a forbidden parent is refused. The screen keeps
    such names off the list, and this is the second lock."""
    import ast

    policy = _policy_with_star({"my.safe.module": frozenset({"SafeThing", "os"})})
    code = "from my.safe.module import os"
    with pytest.raises(SecurityViolation):
        validate_module(ast.parse(code), code=code, policy=policy)


def test_the_generated_star_exports_are_structurally_sound():
    """Whatever the installed Sage produced, the shape holds: dotted module
    names mapping to frozensets of plain identifiers, none dunder, none a name
    the base policy forbids outright."""
    from sagemath_mcp.star_exports import STAR_EXPORTS

    for module_name, names in STAR_EXPORTS.items():
        assert isinstance(module_name, str) and "." in module_name
        assert isinstance(names, frozenset) and names
        for name in names:
            assert name.isidentifier() and not name.startswith("_")
            assert name not in SECURITY_POLICY.forbidden_call_names
            assert name not in SECURITY_POLICY.forbidden_attribute_names


def test_a_vetted_module_with_no_screened_names_is_not_expanded():
    """An entry that mapped to nothing (which the generator never writes) leaves
    the star import to be refused, rather than emitting an empty import."""
    import ast

    policy = _policy_with_star({"my.empty.module": frozenset()})
    code = "from my.empty.module import *"
    rewritten = rewrite_permitted_imports(
        ast.parse(code), offered=frozenset(), policy=policy
    )
    assert not any(isinstance(n, ast.ImportFrom) and n.names[0].name != "*"
                   for n in ast.walk(rewritten))
    with pytest.raises(SecurityViolation):
        validate_module(rewritten, code=code, policy=policy)
