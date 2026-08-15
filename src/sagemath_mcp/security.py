"""Security policy and AST validation for Sage worker execution."""

from __future__ import annotations

import ast
import logging
import os
import re
import textwrap
from dataclasses import dataclass, replace

from .allowlist import ALLOWED_CALLER_NAMES
from .symbols import PREDEFINED_SYMBOLS

LOGGER = logging.getLogger(__name__)


class SecurityViolation(ValueError):
    """Raised when user code violates the configured security policy."""

    # NOTE: We consistently surface SecurityViolation instances back to the
    # caller to explain why a snippet was blocked. Raising a dedicated type
    # keeps logging/monitoring code straightforward.


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:  # pragma: no cover - defensive
        raise ValueError(f"Invalid integer for {name}: {raw}") from exc


def _tuple_env(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.getenv(name)
    if raw is None:
        return default
    values = [value.strip() for value in raw.split(",") if value.strip()]
    return tuple(values) if values else default


@dataclass(slots=True)
class SecurityPolicy:
    """Declarative policy describing acceptable Sage user code."""

    enabled: bool = True
    # Sized from a measurement rather than a guess. These bound how much parsing
    # one request can cost, and at 8,000 chars / 2,500 nodes they refused a
    # matrix: a 40x40 integer matrix written out is 17,706 characters and 6,497
    # nodes, which is exactly the shape someone pastes. Preparse, parse and
    # validate together cost about 1.1us per character on 10.9, linearly:
    #
    #     40x40      17,706 chars    6,497 nodes     18ms
    #     100x100   110,226 chars   40,217 nodes    113ms
    #     200x200   440,426 chars  160,417 nodes    478ms
    #
    # 128 KiB and 50,000 nodes admit a 100x100 matrix with headroom and cap the
    # work at roughly 140ms, which is the point of the limits. Execution is
    # bounded separately by eval_timeout. Depth is unchanged: it measures
    # nesting, not size, and a list of lists is four deep however big it is.
    max_source_chars: int = 131_072
    max_ast_nodes: int = 50_000
    max_ast_depth: int = 75
    allow_imports: bool = False
    # `global` binds at module scope, which is the reason it was held back a
    # round longer than `nonlocal`. What the round found: it reaches nothing a
    # plain module-level assignment does not already reach. `SR = 5` is
    # permitted at the top level, so `def k(): global SR; SR = 5` cannot be the
    # thing that makes it dangerous.
    #
    # The two rules that matter are both upstream of the declaration.
    # `_bound_names` records what `global` declares, and item 37 refuses any
    # name that is live but not offered *whatever* authorizes it -- so
    # `global unpickle_global` claims a name whose object was scrubbed, and
    # reading it back yields the caller's own value or a NameError. Item 41
    # covers the other direction: whatever trusted code introduces is withheld
    # regardless of what the caller claimed first.
    #
    # What it cost was the accumulator, which is how a sweep records a record.
    forbid_global_stmt: bool = False
    # `nonlocal` rebinds a name in an enclosing *function*. It cannot reach the
    # module namespace, so there is nothing for it to reach that assignment in
    # the same function does not already reach -- and refusing it cost
    # `def outer(): ... def inner(): nonlocal total`, which is how a closure
    # counts anything. It was refused by a flag with no comment, no recorded
    # rationale and no test named for it.
    # It was refused a round before `global` was, on the grounds that `global`
    # binds at module scope and deserved its own reasoning. It got it: see
    # above.
    forbid_nonlocal_stmt: bool = False
    forbidden_call_names: tuple[str, ...] = (
        # String-path attribute access. These defeat every attribute rule in
        # this file, because the attribute name is a runtime value the AST never
        # sees: on SageMath 10.9,
        # `operator.attrgetter("misc.persist.unpickle_global")(sage)` returned
        # the real function, which is arbitrary code execution.
        "attrgetter",
        "methodcaller",
        "itemgetter",
        # Sage's own equivalents. `attrcall('save', path)(M)` wrote a file, and
        # `getattr_debug` resolves anything getattr does, including
        # `__class__.__base__.__subclasses__()`.
        "attrcall",
        "call_method",
        "AttrCallObject",
        "raw_getattr",
        "getattr_debug",
        "register_unpickle_override",
        "exec",
        "compile",
        "__import__",
        "open",
        "globals",
        # `eval`, `vars`, `locals` and `input` were here. They are refused as
        # *attributes* instead -- see forbidden_attribute_only_names -- because
        # that is where the danger actually is (`latex.eval()` runs a toolchain)
        # and the bare identifiers reach nothing: measured against SageMath 10.9,
        # each is absent from the restricted builtins, from the worker namespace
        # and from the generated allowlist, all three. What the entries cost was
        # the identifier, and mathematics uses all four:
        #
        #     eval = b.multi_point_evaluation(pts)     # an evaluation
        #     delta = eval*evec - evec*A               # an eigenvalue
        #     def christoffel(i, j, k, vars, g)        # Christoffel symbols
        #     sol = desolve_system(des, vars, ics)
        #     T.process(input)                         # an automaton's input word
        #
        # Attribute access by name defeats every attribute rule below:
        # getattr(os, 'system')('id') never produces an ast.Attribute node.
        "getattr",
        "setattr",
        "delattr",
        # sage_eval and preparse evaluate a *string* at runtime, long after this
        # validator has approved the AST. They are the sharpest bypass of all,
        # since the payload is invisible at validation time.
        "sage_eval",
        "preparse",
        "sage_input",
        # Sage's loaders execute whatever they are pointed at, and load()
        # accepts a URL -- remote code execution, from an ordinary-looking name
        # that no rule mentioned.
        "load",
        "attach",
        # Sage's namespace carries more of the same: a compiler, a shell, a
        # downloader and pickle. cython(get_remote_file(url)) was download,
        # compile and execute in one expression. The worker also removes these
        # by provenance; naming them here is what produces a clear refusal
        # rather than a NameError.
        "cython",
        "cython_lambda",
        "fortran",
        "get_remote_file",
        "loads",
        "dumps",
        "save",
        "save_session",
        "load_session",
        "db_save",
        "sageobj",
        # `db`, `sh`, `trace`, `edit`, `detach` and Sage's eleven CAS interface
        # names -- gp, maxima, gap, singular, octave, magma, mathematica, maple,
        # matlab, macaulay2, sage0 -- were listed here, and are not any more.
        #
        # They were never the lock. Every one of them is removed from the worker
        # namespace by provenance and is absent from the generated allowlist, so
        # reading one unbound is refused by deny-by-default whatever this tuple
        # says. What the entry added was a nicer message; what it cost was the
        # identifier, in every position, including the caller's own:
        #
        #     db = digraphs.DeBruijn(2, 2)    -> Reference to forbidden name 'db'
        #     gap = 7; gap - 1                -> the same, for a prime gap
        #     sol = desolve_system(des, vars, ics)
        #     maxima = <anything>             -> and the same again
        #
        # 447 refusals across SageMath's own doctests, none of them reaching
        # anything: the object is gone. A caller may now use the identifier, and
        # an unbound read still fails -- see REVIEW_ACTIONS.md item 46, and
        # test_a_forbidden_name_is_only_forbidden_while_it_is_reachable, which
        # asserts the namespace really is empty of them.
        #
        # The names that stay are the ones where that argument does NOT hold:
        # `preparse` and `sage_input` are live and allowlisted; `getattr`,
        # `setattr` and `delattr` are allowlisted; and the Python evaluation
        # primitives stay refused whatever the namespace looks like, because
        # this list is the only thing standing between a future namespace
        # regression and arbitrary execution.
    )
    forbidden_attribute_parents: tuple[str, ...] = (
        # `operator` carries the string-path primitives; `pari` runs a shell
        # through PARI's own `system()`; `oeis` reaches the network. Each was
        # demonstrated against 10.9 before being listed here.
        "operator",
        "pari",
        "oeis",
        "warnings",
        "os",
        "sys",
        "pathlib",
        "subprocess",
        "shutil",
        "socket",
        "builtins",
        # Sage sub-packages that compile, run shells, download, pickle or spawn
        # other programs. Blocking the import is not enough on its own: `sage` is
        # bound in the worker namespace, so sage.misc.persist.unpickle_global was
        # reachable without importing anything.
        "cython",
        "persist",
        "remote_file",
        "interfaces",
        "inline_fortran",
        "repl",
        "package",
        "temporary_file",
        "attached_files",
        "explain_pickle",
        "edit_module",
        "dev_tools",
        # `sage.misc.trace.trace(code)` executes a string under the debugger and
        # `sage.misc.sh.sh('id')` runs a shell; `sage` is live and allowlisted,
        # so both chains are reachable and have to be cut. They are cut *here*
        # rather than by forbidding the names, because only the parents of an
        # attribute are checked: this blocks `sage.misc.trace.trace(...)` and
        # leaves `A.trace()` alone -- the trace of a matrix, refused 159 times
        # across SageMath's own doctests by a rule aimed at something else.
        "trace",
        "sh",
    )
    # `operator` is a forbidden parent for one reason -- `attrgetter`,
    # `methodcaller` and `itemgetter` take their attribute path as a runtime
    # string, which defeats every rule in this file. Those three are refused by
    # name, in every position, independently of this. Banning the module on top
    # of that bought nothing and cost `Poset((divisors(30), operator.le))`, which
    # is how a poset is built, 206 times in SageMath's own doctests.
    #
    # So: the module stays forbidden and a named set of its functions is let
    # through. A subset, not an exemption -- anything not listed is still
    # refused, so a future addition to `operator` is denied until someone reads
    # it, which is the same default the caller allowlist uses.
    allowed_module_attributes: tuple[tuple[str, str], ...] = tuple(
        ("operator", name)
        for name in (
            "lt", "le", "eq", "ne", "ge", "gt",
            "add", "sub", "mul", "truediv", "floordiv", "mod", "pow", "neg", "pos",
            "abs", "and_", "or_", "xor", "invert", "lshift", "rshift",
            "concat", "contains", "countOf", "indexOf", "not_", "truth", "is_",
            "is_not", "index", "matmul",
        )
    )
    # Persistence methods, matched by prefix rather than by name. `.dump()`,
    # `.save_image()` and `.export_jmol()` each wrote a file that no rule
    # mentioned, and enumerating the rest of Sage's persistence API one method at
    # a time is the same losing game as the namespace denylist was.
    #
    # Caller code only: trusted_policy() clears this, because the plot templates
    # legitimately call .savefig(buffer) -- to a BytesIO, never a path.
    # `write` joined these after `graphs.PetersenGraph().write_to_eps(path)`
    # was found writing a caller-chosen file: it is the same capability as
    # `.save()`, under a name the original three prefixes did not cover.
    forbidden_attribute_prefixes: tuple[str, ...] = ("save", "dump", "export", "write")
    # Refused as an attribute and nowhere else. The bare names reach nothing --
    # absent from builtins, namespace and allowlist alike -- but `x.eval(...)`
    # can still reach a real method: `latex.eval()` runs the LaTeX toolchain,
    # and that is the rule keeping it shut now that `latex` itself is offered.
    # `eval` alone, because `eval` alone was demonstrated: `latex.eval()` runs
    # the LaTeX toolchain, and `latex` is offered now. `vars`, `locals` and
    # `input` were in this tuple for symmetry and came back out -- no reachable
    # object has a dangerous method by those names, and `f.vars` is the variable
    # list of a QEPCAD formula. Symmetry is not a security justification.
    forbidden_attribute_only_names: tuple[str, ...] = ("eval",)
    # Method names that are dangerous whoever owns them. `remove`, `rmdir`,
    # `unlink`, `walk` and `system` were here for `os.remove` and `os.system`,
    # and they were redundant twice over: `os` is a forbidden attribute parent
    # *and* is absent from the namespace and the allowlist, so `os.system(...)`
    # cannot be spelled at all. What they did reach was `list.remove` and
    # `IntegratedCurve.system()` -- the system of ODEs of a geodesic -- 79
    # refusals in SageMath's own doctests, none of them touching a file.
    forbidden_attribute_names: tuple[str, ...] = (
        # `Latex.has_file(name)` runs `call("kpsewhich %s" % name, shell=True)`
        # and executed `id > /tmp/...` as the container user on 10.9;
        # `check_file` and `add_package_to_preamble_if_available` both call it.
        # By name rather than by refusing every attribute on `latex`, which also
        # refused 56 examples from SageMath's own doctests --
        # `latex.extra_preamble(...)` and friends build strings and set state.
        "has_file",
        "check_file",
        "add_package_to_preamble_if_available",
        "popen",
        "popen2",
        "popen3",
        "rmtree",
        "spawnl",
        "spawnlp",
        "spawnv",
        "spawnvp",
        "execv",
        "execvp",
        "execvpe",
        "fork",
        "forkpty",
        # `<obj>.gp()` hands back a live GP interpreter -- `Dokchitser(...).gp()`
        # returned the `gp` interface the denylist removes, and GP shells out
        # through `system(...)`. The interface is refused as a bare name and by
        # provenance; this closes the method that reconstructs one. Blocked
        # wherever it appears, because every `.gp()` in Sage returns that same
        # interpreter -- there is no benign one to protect. See item 53.
        "gp",
    )
    # EMPTY for caller code: an import is how you get back everything the worker
    # namespace scrub removed. `from sage.misc.cython import compile_and_load`
    # compiled and loaded a module, `from sage.interfaces.gp import Gp` spawned
    # GP, and `unpickle_global('os', 'system')('id')` ran a shell command -- all
    # while `sage.*` was allowlisted for the generated prelude's benefit.
    # Callers do not need imports: the namespace is preloaded with Sage already.
    # trusted_policy() puts the allowlist back for the templates that need it.
    allowed_import_modules: tuple[str, ...] = ()
    allowed_import_prefixes: tuple[str, ...] = ()
    log_violations: bool = True
    # Caller code may only read names on the allowlist, plus whatever it binds
    # itself. This is the inversion of everything above it: the rules before this
    # enumerate what is forbidden, and each bypass so far was a name nobody had
    # enumerated. trusted_policy() turns it off -- generated templates are ours.
    enforce_name_allowlist: bool = True
    allowed_names: frozenset[str] = ALLOWED_CALLER_NAMES

    @classmethod
    def from_env(cls) -> SecurityPolicy:
        """Load the security policy using environment overrides."""
        defaults = cls()
        return cls(
            enabled=_bool_env("SAGEMATH_MCP_SECURITY_ENABLED", defaults.enabled),
            max_source_chars=_int_env(
                "SAGEMATH_MCP_SECURITY_MAX_SOURCE", defaults.max_source_chars
            ),
            max_ast_nodes=_int_env(
                "SAGEMATH_MCP_SECURITY_MAX_AST_NODES", defaults.max_ast_nodes
            ),
            max_ast_depth=_int_env(
                "SAGEMATH_MCP_SECURITY_MAX_AST_DEPTH", defaults.max_ast_depth
            ),
            allow_imports=_bool_env("SAGEMATH_MCP_SECURITY_ALLOW_IMPORTS", defaults.allow_imports),
            forbid_global_stmt=_bool_env(
                "SAGEMATH_MCP_SECURITY_FORBID_GLOBAL", defaults.forbid_global_stmt
            ),
            forbid_nonlocal_stmt=_bool_env(
                "SAGEMATH_MCP_SECURITY_FORBID_NONLOCAL", defaults.forbid_nonlocal_stmt
            ),
            log_violations=_bool_env(
                "SAGEMATH_MCP_SECURITY_LOG_VIOLATIONS", defaults.log_violations
            ),
            enforce_name_allowlist=_bool_env(
                "SAGEMATH_MCP_SECURITY_NAME_ALLOWLIST", defaults.enforce_name_allowlist
            ),
            allowed_import_modules=_tuple_env(
                "SAGEMATH_MCP_SECURITY_ALLOWED_IMPORTS", defaults.allowed_import_modules
            ),
            allowed_import_prefixes=_tuple_env(
                "SAGEMATH_MCP_SECURITY_ALLOWED_IMPORT_PREFIXES",
                defaults.allowed_import_prefixes,
            ),
        )


SECURITY_POLICY = SecurityPolicy.from_env()


def _max_depth(node: ast.AST, depth: int = 0) -> int:
    child_depths = [_max_depth(child, depth + 1) for child in ast.iter_child_nodes(node)]
    if not child_depths:
        return depth
    return max(child_depths)


def _format_violation(message: str, code: str | None) -> str:
    if not code:
        return message
    snippet = code.strip().splitlines()
    if snippet:
        snippet = snippet[:3]
        joined = " / ".join(line.strip() for line in snippet if line.strip())
        return f"{message} [snippet: {joined}]"
    return message


# What to reach for instead, when an import asks for something this server does
# not offer. A refusal that names the alternative costs the caller nothing; one
# that says only "disabled" costs an exchange, and models do not always recover
# from it -- three physics cases were lost to exactly that.
_IMPORT_ALTERNATIVES: tuple[tuple[str, str], ...] = (
    ("numpy", "SageMath's own arrays: matrix(RDF, ...), vector(RDF, ...), srange"),
    ("scipy", "numerical_integral, find_root, desolve_odeint, minimize"),
    ("sympy", "SageMath is a superset: var(), integrate(), solve(), simplify()"),
    ("matplotlib", "plot(), plot3d(), list_plot(), parametric_plot()"),
    ("math", "sqrt, exp, log, pi and the rest are already available"),
    ("cmath", "ComplexField, I, and the usual functions are already available"),
    ("random", "random(), randint(), shuffle(), sample(), set_random_seed()"),
    ("fractions", "QQ and Rational are already available"),
    ("decimal", "RealField(precision) is already available"),
    ("statistics", "mean, median, variance, std are already available"),
    ("itertools", "product, permutations and combinations of Sage's own"),
)


# The mathematics behind a name this server does not offer. Every entry is a
# spelling that works, and `test_the_blocked_interfaces_do_not_block_the_
# mathematics` computes each one -- this is writing down what that test knows.
#
# It matters because of who is reading. A refusal that says only "not offered"
# leaves a model to guess, and the guess is usually another spelling of the same
# refused thing; naming the equivalent ends the exchange. ~2,300 of the refusals
# SageMath's own doctests provoke are these names.
_NATIVE_EQUIVALENTS: dict[str, str] = {
    # The external CAS interfaces. Each spawns the real program and hands it a
    # string; Sage computes all of it in-process as well.
    "gap": "SymmetricGroup(5), PermutationGroup([...]) and the group methods",
    "gap3": "the native group methods",
    "libgap": "the group methods usually answer directly: SymmetricGroup(5), "
              "PermutationGroup([...]), and .order(), .gens(), .subgroups()",
    "singular": "ideal(...).groebner_basis(), .primary_decomposition() and the "
                "polynomial ring methods",
    "maxima": "integrate(), limit(), desolve(), factor() and solve() -- all of "
              "which use Maxima in process",
    "gp": "the number theory functions directly: factor(), is_prime(), "
          "qfbclassno via QuadraticField(...).class_number()",
    "pari": "the number theory functions directly, or the .pari() method on a "
            "Sage object",
    "magma": "Sage's own algebra: PolynomialRing, NumberField, EllipticCurve",
    "mathematica": "Sage's own symbolics: var(), integrate(), solve(), simplify()",
    "maple": "Sage's own symbolics: var(), integrate(), solve(), simplify()",
    "matlab": "matrix(RDF, ...) and the numerical linear algebra methods",
    "octave": "matrix(RDF, ...) and the numerical linear algebra methods",
    "macaulay2": "ideal(...).groebner_basis() and the polynomial ring methods",
    "r": "RealDistribution, mean(), variance(), find_fit() and statistics_summary",
    "fricas": "Sage's own symbolics: var(), integrate(), solve()",
    "giac": "Sage's own symbolics: var(), integrate(), solve()",
    "sage0": "the mathematics directly; there is no second Sage to talk to",
    # String-path attribute access, which is refused as a class.
    "attrcall": "a lambda: attrcall('bruhat_le') is lambda a, b: a.bruhat_le(b)",
    "attrgetter": "a lambda, or the attribute directly",
    "methodcaller": "a lambda: methodcaller('trace') is lambda m: m.trace()",
    "itemgetter": "a lambda: itemgetter(0) is lambda s: s[0]",
    # Session and display plumbing.
    "show": "the value itself -- results come back as text, and the plot tools "
            "return an image",
    "view": "the value itself, or plot() for a picture",
    "pretty_print": "the value itself",
    "html": "the value itself",
    "reset": "the reset_sage_session tool, which restarts the worker cleanly",
    "set_verbose": "nothing -- progress is reported by the streaming tool",
    "load": "the value directly; this server keeps state between calls instead",
    "save": "the value directly; this server keeps state between calls instead",
}


# Sage's own ways of putting names into the caller's namespace. Each takes them
# from the object -- `variable_names()`, or the basis shorthands -- so what lands
# is that object's generators, and none of it is knowable before the call runs.
_NAME_INJECTING_METHODS: frozenset[str] = frozenset({
    "inject_variables",
})
# `inject_shorthands` is deliberately not here. It looks like a sibling and is
# not: Sage sends it through `sage.repl.user_globals`, so it writes into the
# REPL's namespace and nothing lands in the worker's. Gating on it would suspend
# the allowlist for a snippet where nothing is injected, and trade a message
# that names the fix -- "declare it first with var('s')" -- for a bare
# NameError. Confirmed against 10.9: after `S.inject_shorthands()`, `s` is
# undefined here.


def _native_equivalent(name: str) -> str | None:
    return _NATIVE_EQUIVALENTS.get(name)


def _import_alternative(module: str) -> str | None:
    root = (module or "").split(".", 1)[0]
    for name, advice in _IMPORT_ALTERNATIVES:
        if root == name:
            return advice
    return None


def rewrite_permitted_imports(
    module: ast.Module,
    *,
    offered: frozenset[str] | set[str],
    policy: SecurityPolicy | None = None,
) -> ast.Module:
    """Drop the imports that would change nothing, before anything is validated.

    Callers cannot import, and that rule is load-bearing: an import is how you
    get back everything the namespace scrub removed (item 27). But a great deal
    of what arrives would achieve *nothing* -- a reflex line at the top of a
    snippet, or a name the namespace already holds -- and refusing those costs
    the whole snippet for no gain. Gemini opens numerical work with
    `import numpy as np` and then never uses `np`; that line was worth ignoring,
    not erroring on.

    Three shapes are dropped, and the safety of all three is one argument:
    **nothing is imported, so nothing new becomes reachable.**

    1. `from X import a, b` where every name is already offered. The source
       module is never touched, so what it is does not matter: the caller ends
       up with the object they could already read. An alias is checked against
       the name being *imported*, not the alias, so `from sage.all import os as
       m` is still refused -- that was a real bypass.
    2. `from sage.all import *`, which is what the namespace already is.
    3. A plain `import X` whose bound name is never read in this snippet.

    Everything else is left in place for the validator to refuse, with a message
    that now names the alternative.
    """
    policy = policy or SECURITY_POLICY
    if not policy.enforce_name_allowlist:
        return module

    read: set[str] = {
        node.id
        for node in ast.walk(module)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    read |= {
        segment
        for node in ast.walk(module)
        if isinstance(node, ast.Attribute)
        for segment in _attribute_segments(node)
    }

    def replacement(node: ast.Import | ast.ImportFrom) -> list[ast.stmt] | None:
        """The statements to put in place of *node*, or None to leave it alone."""
        bound_by = {(alias.asname or alias.name).split(".", 1)[0] for alias in node.names}

        if any(alias.name == "*" for alias in node.names):
            # Only from the namespace's own source, and only as a no-op.
            if isinstance(node, ast.ImportFrom) and node.module in ("sage.all", "sage"):
                return []
            return None

        if isinstance(node, ast.Import) and not bound_by & read:
            # A plain `import numpy as np` that nothing reads is a reflex line,
            # and dropping it cannot change the result.
            #
            # Deliberately NOT extended to `from X import Y`. That form names a
            # specific object, and a caller who asks for one this server does
            # not offer deserves to be told now rather than on the next call,
            # when the failure has moved to a bare `Y` and says nothing about
            # the import. Measured against SageMath's own doctests, dropping
            # unused from-imports moved acceptance from 98.6% to 91.0% -- 32,000
            # examples whose clear refusal became a confusing one.
            return []

        if isinstance(node, ast.ImportFrom):
            wanted = [alias.name for alias in node.names]
            if all(name in offered for name in wanted):
                # Bind the object the caller could already read. Only an alias
                # needs a statement; without one the name is already correct.
                return [
                    ast.Assign(
                        targets=[ast.Name(id=alias.asname, ctx=ast.Store())],
                        value=ast.Name(id=alias.name, ctx=ast.Load()),
                    )
                    for alias in node.names
                    if alias.asname
                ]
        # `import X` binds a module object, which is a capability even when the
        # name looks familiar: `import sage.misc.persist` is not a no-op.
        return None

    changed = False
    body: list[ast.stmt] = []
    for statement in module.body:
        if isinstance(statement, (ast.Import, ast.ImportFrom)):
            substitute = replacement(statement)
            if substitute is not None:
                body.extend(substitute)
                changed = True
                continue
        body.append(statement)

    if not changed:
        return module
    rewritten = ast.Module(body=body, type_ignores=list(module.type_ignores))
    ast.fix_missing_locations(rewritten)
    return rewritten


def _raise_violation(
    message: str, *, code: str | None, policy: SecurityPolicy | None
) -> None:
    formatted = _format_violation(message, code)
    if (policy or SECURITY_POLICY).log_violations:
        LOGGER.warning("Blocked Sage code: %s", formatted)
    raise SecurityViolation(message)


def trusted_policy(policy: SecurityPolicy | None = None) -> SecurityPolicy:
    """Policy for code this server generates itself.

    The helper tools build their Sage snippets around sage_eval, which is
    forbidden to callers precisely because it evaluates a string after this
    validator has approved the AST. Server-generated code is not attacker
    controlled, so it may use it -- but only after the *user* fragments
    interpolated into it have been validated in their own right. See
    server._validated_expression.

    Everything else in the policy still applies: generated code cannot import
    os, reach dunders, or call the other forbidden builtins.
    """
    base = policy or SECURITY_POLICY
    relaxed = tuple(name for name in base.forbidden_call_names if name not in _TRUSTED_CALLS)
    return replace(
        base,
        forbidden_call_names=relaxed,
        # The prelude imports sage.all and the plot templates use base64 and io.
        # Caller code gets none of this: see allowed_import_modules above.
        allowed_import_modules=_TRUSTED_IMPORTS,
        allowed_import_prefixes=("sage.",),
        enforce_name_allowlist=False,
        # The plot templates render through .savefig(BytesIO); nothing generated
        # here writes to a path.
        forbidden_attribute_prefixes=(),
    )


# Evaluation entry points the server itself needs, and callers must not have.
_TRUSTED_CALLS = frozenset({"sage_eval", "preparse", "sage_input"})

# Imports the generated templates need. Caller code imports nothing at all.
_TRUSTED_IMPORTS = ("math", "cmath", "sage", "sage.all", "statistics", "base64", "io")

# Forbidden-parent names that are ALSO real methods on a mathematical object, so
# they are permitted as the terminal segment of a plain `object.method` chain
# (two segments) even when the root is an offered name -- `pi.operator()`,
# `M.trace()`, `E.pari()`. As a longer module path (`sage.misc.trace`,
# `sage.misc.sh`) the same name is the module, and stays refused: that chain has
# more than two segments, or reaches the name as a parent with a child hanging
# off it. See the terminal-segment rule in validate_module (items 49/52).
_TERMINAL_METHOD_NAMES = frozenset({"trace", "sh", "operator", "pari", "oeis"})


def _is_dunder(name: str) -> bool:
    """True for names like __class__, __globals__, __builtins__."""
    return len(name) > 4 and name.startswith("__") and name.endswith("__")


# The one dunder Sage's own preparser writes. `f(x) = x^2 + 1` -- the first
# function definition in every Sage tutorial, and how a physicist writes a
# potential -- expands to
#     __tmp__=var("x"); f = symbolic_expression(x**Integer(2) + Integer(1)).function(x)
# and validation runs on the preparsed source, so the dunder rule refused the
# most idiomatic syntax in the language.
_PREPARSER_TEMP = "__tmp__"


def _is_preparser_temp(node: ast.Name) -> bool:
    """Is this the preparser's scratch name, being written rather than read?

    Store only, and that one name only. The preparser never reads it back, so a
    caller who writes it themselves gains nothing they did not already have: the
    value is theirs, and loading it stays blocked. Allowing dunder *stores* in
    general would not be safe -- `__builtins__ = {...}` is a store.
    """
    return node.id == _PREPARSER_TEMP and isinstance(node.ctx, ast.Store)


def _attribute_segments(node: ast.Attribute) -> list[str]:
    """Return every dotted segment of an attribute chain, root first.

    Checking only one level let sage.misc.temporary_file.os.getuid() through,
    because func.value was an Attribute rather than a Name. Checking only the
    root is not enough either: there the root is the permitted `sage` and the
    forbidden `os` sits in the middle of the chain.
    """
    segments: list[str] = []
    current: ast.expr = node
    while isinstance(current, ast.Attribute):
        segments.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        segments.append(current.id)
    segments.reverse()
    return segments


def _is_allowed_import(module: str, policy: SecurityPolicy) -> bool:
    module = module or ""
    if module in policy.allowed_import_modules:
        return True
    return any(module.startswith(prefix) for prefix in policy.allowed_import_prefixes)


def _bound_names(module: ast.Module) -> set[str]:
    """Every name the caller's own code binds.

    Collected across the whole module rather than per scope: an over-approximation
    on purpose. Treating a name bound anywhere as readable everywhere cannot
    manufacture a dangerous object -- the caller's binding is their own value, and
    the dangerous originals are gone from the namespace -- while a strict scope
    analysis would refuse ordinary code for no gain.

    `var('t s')` is included because Sage callers create symbols that way
    constantly, and the names it makes exist only at runtime.

    Dunders are excluded. Binding is not asked whether it runs -- `if False:`,
    an except handler that never fires, a function argument -- so a binding of
    `__builtins__` would authorize reading the real one, and every name live in
    the namespace but off the allowlist is a dunder. Reading one is blocked
    anyway, which makes this the second lock rather than the first.
    """
    bound: set[str] = set()
    for node in ast.walk(module):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bound.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(node, ast.alias):
            bound.add((node.asname or node.name).split(".", 1)[0])
        elif isinstance(node, ast.Global | ast.Nonlocal):
            bound.update(node.names)
        elif isinstance(node, ast.MatchAs | ast.MatchStar) and node.name:
            # `case [a, *rest]`, `case int() as n`, `case other`. Patterns bind
            # through their own node types, not Name nodes, so a Name-based walk
            # sees a whole match statement's variables as undefined.
            bound.add(node.name)
        elif isinstance(node, ast.MatchMapping) and node.rest:
            bound.add(node.rest)
        elif isinstance(node, ast.Call) and getattr(node.func, "id", None) in ("var", "function"):
            # var('t'), var('t s'), var('a,b') and function('f') -- Sage's own
            # spellings for declaring symbols and symbolic functions. Both inject
            # into the namespace, and they are the common way a caller creates a
            # name that no assignment reveals.
            for argument in node.args:
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    bound.update(re.split(r"[,\s]+", argument.value.strip()))
    bound.discard("")
    return {name for name in bound if not name.startswith("__")}


_PREDEFINED_LIST = ", ".join(PREDEFINED_SYMBOLS)

# A single letter with an optional index: y, w, t1, x_2 as callers write them.
_SYMBOL_SHAPE = re.compile(r"^[a-zA-Z]_?\d?$")
_GREEK_NAMES = frozenset({
    "alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta", "iota",
    "kappa", "lamda", "mu", "nu", "xi", "omicron", "rho", "sigma", "tau",
    "upsilon", "phi", "chi", "psi", "omega",
})


def _looks_like_an_undeclared_symbol(name: str) -> bool:
    """Does this read like a mathematical variable rather than a missing helper?

    Narrow on purpose, and narrower than it first was. "short and lowercase"
    also matched `pari`, `oeis` and `show` -- names deliberately withheld
    because they run a shell, reach the network or write files -- and advising
    `var('pari')` is both wrong and faintly absurd. A symbol is a single letter
    with an optional index, or one of the Greek names Sage itself binds.
    """
    return bool(_SYMBOL_SHAPE.match(name)) or name in _GREEK_NAMES


def check_source_length(
    code: str | None,
    policy: SecurityPolicy | None = None,
    *,
    after_preparse: bool = False,
) -> None:
    """Refuse code that is too long, before anything tries to parse it.

    Separate from `validate_module` because it has to run *earlier*. The worker
    parses first and validates second, so a 140 KB snippet reached CPython's
    parser before this limit was consulted and came back as
    `RecursionError: maximum recursion depth exceeded during ast construction`
    -- a caller told their mathematics broke the interpreter, when the truth was
    that it exceeded a documented limit by 9 KB.
    """
    policy = policy or SECURITY_POLICY
    if not policy.enabled:
        return
    source_length = len(code or "")
    if source_length > policy.max_source_chars:
        # Which length, said plainly: Sage's preparser rewrites `1+1` as
        # `Integer(1)+Integer(1)`, so 140 KB of arithmetic becomes 770 KB before
        # anything parses it. A caller told "770012 > 131072" about code they
        # measured at 140 KB would reasonably think the number was wrong.
        where = " after Sage's preparser expanded it" if after_preparse else ""
        _raise_violation(
            f"Sage code exceeds maximum length{where} "
            f"({source_length} > {policy.max_source_chars})",
            code=code,
            policy=policy,
        )


def validate_module(
    module: ast.Module,
    *,
    code: str | None = None,
    policy: SecurityPolicy | None = None,
    extra_allowed_names: frozenset[str] | set[str] = frozenset(),
    withheld_names: frozenset[str] | set[str] = frozenset(),
) -> None:
    """Validate *module* against the configured security policy.

    ``withheld_names`` are names that exist in the worker's namespace but are
    not offered to callers. They are refused whatever else authorizes them,
    because a caller's *binding* must authorize a name the caller creates and
    not one that is already there holding something else. Binding is judged
    statically -- `leaked = smuggled(); smuggled = None` binds `smuggled` for
    the whole module -- so without this rule the read at the start is
    authorized while the name still holds the preloaded object.
    """
    policy = policy or SECURITY_POLICY
    if not policy.enabled:
        return

    source_length = len(code or "")
    check_source_length(code, policy)

    node_count = sum(1 for _ in ast.walk(module))
    if node_count > policy.max_ast_nodes:
        _raise_violation(
            f"Sage code exceeds maximum AST node count ({node_count} > {policy.max_ast_nodes})",
            code=code,
            policy=policy,
        )

    depth = _max_depth(module)
    if depth > policy.max_ast_depth:
        _raise_violation(
            f"Sage code exceeds maximum AST depth ({depth} > {policy.max_ast_depth})",
            code=code,
            policy=policy,
        )

    # Names this session already holds, beyond what Sage shipped with: `x = 5` in
    # one call and `x + 1` in the next is the whole point of a stateful session,
    # and no analysis of the second snippet alone can know about the first. The
    # worker passes what the caller has created; Sage's own names are still judged
    # against the allowlist, so a helper added by a future release stays denied.
    bound = set(extra_allowed_names) if policy.enforce_name_allowlist else set()
    if policy.enforce_name_allowlist:
        bound |= _bound_names(module)

    # The `operator` in `operator.le` is a Name node too, and the rule that
    # refuses forbidden modules by name would refuse it before the attribute
    # rule ever sees which function was wanted. Collect the ones that are part
    # of a permitted module attribute so that rule can let them through.
    exempt_module_names = {
        id(node.value)
        for node in ast.walk(module)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and (node.value.id, node.attr) in policy.allowed_module_attributes
    }

    # Names in call position, so a refusal can tell `r("'abc'")` apart from a
    # radius called `r`.
    called_names = {
        id(node.func)
        for node in ast.walk(module)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    # Does this snippet ask a Sage object to put names into the namespace?
    injects_names = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _NAME_INJECTING_METHODS
        for node in ast.walk(module)
    )

    for node in ast.walk(module):
        if isinstance(node, (ast.Import, ast.ImportFrom)) and not policy.allow_imports:
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            else:
                # ImportFrom, by the check above. `from . import x` has no
                # module at all, which the empty check below rejects.
                modules = [node.module] if node.module is not None else []
            if not modules:
                _raise_violation(
                    "Relative imports are disabled for Sage executions",
                    code=code,
                    policy=policy,
                )
            if not all(_is_allowed_import(mod, policy) for mod in modules):
                # Say what to do instead. Gemini opens numerical work with
                # `import numpy as np` or `from sage.all import *`, was told only
                # that imports are disabled, and did not recover across three
                # cases -- while the same questions passed on a client that
                # happened not to write the line. The namespace already holds
                # everything the import was for, which is a fix the caller can
                # act on; "disabled" is not.
                advice = next(
                    (found for found in (_import_alternative(mod) for mod in modules)
                     if found),
                    None,
                )
                _raise_violation(
                    "Import statements are disabled for Sage executions. "
                    + (f"Use {advice}. " if advice else
                       "SageMath is already loaded: use matrix, vector, RDF, srange, "
                       "numerical_integral, desolve_odeint and the rest directly. ")
                    + "An import that would change nothing is dropped rather than "
                    "refused, so this one is asking for something the server does "
                    "not offer",
                    code=code,
                    policy=policy,
                )
            # An allowed module can re-export a forbidden one. `sage` is on the
            # allowlist and `from sage.all import os as m` bound the real os
            # module under a fresh name, which then passed every later rule
            # because the name being read was `m`. Judge what is imported, not
            # only where it comes from.
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                if (
                    root in policy.forbidden_attribute_parents
                    or root in policy.forbidden_call_names
                ):
                    _raise_violation(
                        f"Importing '{alias.name}' is blocked "
                        f"('{root}' is not permitted in Sage executions)",
                        code=code,
                        policy=policy,
                    )
        if isinstance(node, ast.Global) and policy.forbid_global_stmt:
            _raise_violation(
                "Global statements are not permitted in Sage executions",
                code=code,
                policy=policy,
            )
        if isinstance(node, ast.Nonlocal) and policy.forbid_nonlocal_stmt:
            _raise_violation(
                "Nonlocal statements are not permitted in Sage executions",
                code=code,
                policy=policy,
            )
        # Dunder access is the shortest path out of the sandbox:
        # ().__class__.__bases__[0].__subclasses__() reaches subprocess.Popen,
        # and __builtins__ reaches __import__ by attribute or by subscript.
        # Blocking the whole namespace closes both in one rule.
        if isinstance(node, ast.Attribute) and _is_dunder(node.attr):
            _raise_violation(
                f"Access to dunder attribute '{node.attr}' is blocked",
                code=code,
                policy=policy,
            )
        if isinstance(node, ast.Name) and _is_dunder(node.id) and not _is_preparser_temp(node):
            _raise_violation(
                f"Access to dunder name '{node.id}' is blocked",
                code=code,
                policy=policy,
            )

        if (
            policy.enforce_name_allowlist
            and isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and (node.id in withheld_names or (
                node.id not in bound
                and node.id not in policy.allowed_names
                # `A.inject_variables()` creates names while the snippet runs,
                # and no static analysis can know them: they are whatever the
                # object's `variable_names()` says. `R.<u, v> = QQ[]` is covered
                # because the preparser binds statically, but
                # `R = PolynomialRing(QQ, 'u,v'); R.inject_variables(); u^2 + v`
                # is the same mathematics written the other way and was refused.
                #
                # So a snippet that asks for an injection has the *allowlist*
                # half of this rule suspended -- and only that half. The
                # withheld check above still applies, which is the half with the
                # security content: every name that is live and not offered is
                # still refused, whatever the snippet contains. What suspending
                # buys is names that are not live at all, and those are either
                # the injected ones or a NameError.
                and not injects_names
            ))
            # `operator` in `operator.le` is live and deliberately not offered as
            # a value: reading it on its own stays refused, and reading one of
            # its permitted functions does not.
            and id(node) not in exempt_module_names
        ):
            # Deny-by-default. Every bypass so far was a name no rule mentioned;
            # here an unrecognised name is refused instead of assumed harmless.
            #
            # The message matters as much as the refusal. Clients are models that
            # retry on what they are told, and the common case by far is not an
            # attack or a typo -- it is an undeclared symbol. Only four symbols
            # exist without being declared, so `diff(x^2*w^3, x, w)` is ordinary
            # mathematics that needs `var('w')` first. Sending that caller to the
            # allowlist points them at a fix they cannot perform and costs an
            # exchange; naming the fix they can perform usually costs none.
            equivalent = _native_equivalent(node.id)
            if equivalent and id(node) in called_names:
                # Being *called* settles it. A lone `r` is a radius far more
                # often than the R interface, so the symbol message wins for
                # `f(x, r)` -- but `r("'abc'")` is calling the interface, and
                # telling that caller to `var('r')` sends them somewhere with no
                # answer in it. 135 refusals in SageMath's own doctests are that
                # exact line.
                _raise_violation(
                    f"'{node.id}' is not offered: it spawns an external program, "
                    f"and this server does the same mathematics in process. "
                    f"Use {equivalent}.",
                    code=code,
                    policy=policy,
                )
            if _looks_like_an_undeclared_symbol(node.id):
                _raise_violation(
                    f"'{node.id}' is not defined. This server predefines the symbols "
                    f"{_PREDEFINED_LIST}, so declare it first with "
                    f"var('{node.id}') -- or assign it a value.",
                    code=code,
                    policy=policy,
                )
            if equivalent:
                # The name is withheld on purpose and the mathematics is not.
                # Saying which spelling works ends the exchange; saying only
                # "not offered" invites another spelling of the same thing.
                _raise_violation(
                    f"'{node.id}' is not offered: it spawns an external program, "
                    f"and this server does the same mathematics in process. "
                    f"Use {equivalent}.",
                    code=code,
                    policy=policy,
                )
            _raise_violation(
                f"'{node.id}' is not a name this server offers. If it is a typo, "
                "check the spelling; if it is a SageMath function that should be "
                "available, it needs to be added to the allowlist",
                code=code,
                policy=policy,
            )
        # Reaching the attribute is the capability; calling it is one thing you
        # can do next. Guarding only `Call(func=Attribute(...))` meant
        # `f = latex.has_file; f(payload)` passed, and each of those spellings
        # ran a shell on 10.9. That gap was as old as the list itself -- `popen`
        # and `rmtree` were reachable the same way.
        if isinstance(node, ast.Attribute) and node.attr in policy.forbidden_attribute_names:
            _raise_violation(
                f"Access to forbidden attribute '{node.attr}' is blocked",
                code=code,
                policy=policy,
            )

        # A forbidden module is forbidden entirely. Requiring the attribute to
        # ALSO be on a list of eighteen names meant os.system was blocked while
        # os.listdir, os.environ and os.chmod were not -- and the README claimed
        # subprocess.*, pathlib.* and socket.* were blocked when none of them were.
        if isinstance(node, ast.Attribute):
            segments = _attribute_segments(node)
            # A chain the caller rooted in their own value is not a module path.
            # `sh = 2; sh.bit_length()` is arithmetic; `sage.misc.sh.sh('id')` is
            # a shell. The root has to be a name the caller created *and* one
            # this server does not otherwise offer -- `sage` is offered, so
            # `if False: sage = 1` cannot buy the exemption (item 37's trap).
            root = segments[0] if segments else ""
            caller_owned = bool(
                policy.enforce_name_allowlist
                and root
                and root in bound
                and root not in policy.allowed_names
            )
            # `operator.le` and the rest of the permitted arithmetic: a
            # whole-chain exemption for exactly the named (module, attr) pairs.
            permitted_pair = (
                len(segments) == 2
                and (segments[0], segments[1]) in policy.allowed_module_attributes
            )
            if not permitted_pair:
                # Every segment is inspected, not just segments[:-1]. Checking
                # only the parents let two escapes through:
                #   items 49/50/56: `m = sage.env.os` binds the real os module
                #     under a fresh name -- `os` was the TERMINAL segment, never
                #     reached -- and `m.system(...)` then ran unchecked. Same for
                #     `f = sage.misc.persist` and `sage.env.sys.modules['os']`.
                #   item 52: the caller_owned exemption skipped the WHOLE chain,
                #     so `s = sage; s.misc.persist.unpickle_global(...)` walked
                #     past `persist` on the strength of the caller-owned root `s`.
                # A terminal forbidden name is a module only when the chain is a
                # module path (rooted at an offered name); as a plain
                # object.method it is real mathematics -- `A.trace()`,
                # `(x+y).operator()`, `E.pari()` -- so those are left alone.
                last = len(segments) - 1
                for index, segment in enumerate(segments):
                    if segment not in policy.forbidden_attribute_parents:
                        continue
                    if index == last:
                        # A module path is a dotted chain from an offered NAME:
                        # `sage.env.os`, `desolvers.os`. A single-segment chain
                        # is `<expr>.method` -- `(x+y).operator()` -- where the
                        # root was a Call or BinOp, not a Name, so `segments[0]`
                        # is the method, not a module. `operator` and `pari` are
                        # offered names AND forbidden parents, so len>=2 is what
                        # tells the module `operator` from the `.operator()`
                        # method.
                        module_path = len(segments) >= 2 and root in policy.allowed_names
                        object_method = (
                            len(segments) == 2 and segment in _TERMINAL_METHOD_NAMES
                        )
                        if not module_path or object_method:
                            continue
                    elif index == 0 and caller_owned:
                        # The caller rebound a name that happens to be a
                        # forbidden parent. Only the ROOT is theirs -- a
                        # forbidden parent deeper in the chain is an attribute of
                        # a real object (`s.misc.persist` after `s = sage`) and
                        # stays refused.
                        continue
                    _raise_violation(
                        f"Access through '{segment}' is blocked "
                        f"('{segment}' is not permitted in Sage executions)",
                        code=code,
                        policy=policy,
                    )

        # A forbidden builtin is forbidden wherever it is REFERENCED, not only
        # where it is called. Checking ast.Call.func alone let the name be
        # aliased first and called through the alias:
        #     f = open;                    f('/etc/passwd').readline()
        #     (lambda f=open: f('/etc/passwd').readline())()
        # Both returned the first line of /etc/passwd, through evaluate_sage and
        # through calculate_expression. Any expression that stores, defaults,
        # or packs the name into a container works the same way, so the check
        # belongs on the Name node itself.
        # The same reasoning applies to the forbidden MODULES, and the first fix
        # missed them: the attribute rule above inspects an ast.Attribute chain,
        # so it saw os.getuid() but not
        #     m = os;                      m.getuid()
        #     from sage.all import os as m;m.getuid()
        # Both returned the container uid from real SageMath. Once the module
        # object is bound to an unremarkable name there is no chain left to
        # inspect, so the module name has to be unreadable in the first place.
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            if node.id in policy.forbidden_call_names:
                equivalent = _native_equivalent(node.id)
                _raise_violation(
                    f"Reference to forbidden name '{node.id}' is blocked"
                    + (f". Use {equivalent}." if equivalent else ""),
                    code=code,
                    policy=policy,
                )
            if (
                node.id in policy.forbidden_attribute_parents
                and id(node) not in exempt_module_names
                # A path segment is not a variable. `sh` and `trace` are on this
                # list to cut `sage.misc.sh.sh('id')` and
                # `sage.misc.trace.trace(code)`, and without this a caller could
                # not write `sh = 2; sh + 1`. Only a name they created, and only
                # one this server does not otherwise offer -- so `sage` cannot
                # be claimed this way, which is what item 37 turned on.
                and not (
                    policy.enforce_name_allowlist
                    and node.id in bound
                    and node.id not in policy.allowed_names
                )
            ):
                _raise_violation(
                    f"Reference to forbidden module '{node.id}' is blocked",
                    code=code,
                    policy=policy,
                )

        # A forbidden name is forbidden however it is spelled. Checking bare
        # names and Call.func left the same functions reachable through an
        # attribute chain rooted at the permitted `sage`:
        #     sage.misc.sage_eval.sage_eval("__import__('os').getuid()")
        # returned the container uid. What matters is the final name, not
        # whether a dot precedes it.
        if isinstance(node, ast.Attribute) and (
            node.attr in policy.forbidden_call_names
            or node.attr in policy.forbidden_attribute_only_names
        ):
            _raise_violation(
                f"Access to forbidden function '{node.attr}' is blocked",
                code=code,
                policy=policy,
            )

        # Anything that persists: .dump(), .save_image(), .export_jmol() and the
        # rest of the family write to a path the caller chooses.
        if isinstance(node, ast.Attribute) and any(
            node.attr.startswith(prefix) for prefix in policy.forbidden_attribute_prefixes
        ):
            _raise_violation(
                f"Access to '{node.attr}' is blocked: writing files is not "
                "available to caller code",
                code=code,
                policy=policy,
            )
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in policy.forbidden_call_names:
                equivalent = _native_equivalent(func.id)
                _raise_violation(
                    f"Call to forbidden function '{func.id}' is blocked"
                    + (f". Use {equivalent}." if equivalent else ""),
                    code=code,
                    policy=policy,
                )
            # Kept for bare calls such as system(...) that arrive via a star
            # import rather than through a module attribute.
            if isinstance(func, ast.Attribute) and func.attr in policy.forbidden_attribute_names:
                _raise_violation(
                    f"Call to forbidden attribute '{func.attr}' is blocked",
                    code=code,
                    policy=policy,
                )

    if policy.log_violations:
        LOGGER.debug(
            "Sage security validation passed (length=%s, nodes=%s, depth=%s)",
            source_length,
            node_count,
            depth,
        )


def normalize_caller_code(code: str) -> str:
    """Strip an indentation prefix the whole snippet shares.

    Uniformly indented code is a syntax error in Python and in Sage's own REPL,
    and clients are models that wrap and indent freely -- a snippet lifted out of
    a markdown block arrives with four spaces on every line. Dedenting cannot
    change a valid program, because valid module-level code has no common indent
    to remove; it only admits input that was otherwise refused for its margin
    rather than its mathematics.

    Applied before validation and before execution, so both see the same text.
    """
    return textwrap.dedent(code)


def validate_code(code: str, policy: SecurityPolicy | None = None) -> None:
    """Parse *code* and validate it against the policy."""
    code = normalize_caller_code(code)
    try:
        module = ast.parse(code, mode="exec", type_comments=True)
    except SyntaxError as exc:  # pragma: no cover - already surfaced elsewhere
        raise SecurityViolation(f"Invalid Python syntax: {exc}") from exc
    validate_module(module, code=code, policy=policy)
