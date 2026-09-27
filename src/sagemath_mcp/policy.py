"""What the validator enforces: the policy, its environment overrides, and
the trusted variant generated code runs under.

The defaults are the security posture. Each override reads a
``SAGEMATH_MCP_*`` variable; see SECURITY.md.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace

from ._artifacts import ALLOWED_CALLER_NAMES, STAR_EXPORTS


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
        # that is where the danger actually is (`latex.eval` runs a toolchain)
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
    #: Names whose attribute tree caller code may not traverse AT ALL.
    #:
    #: `forbidden_attribute_parents` enumerates dangerous path segments, and a
    #: 2026-09-19 review showed why that shape cannot hold: `sage` is on the
    #: caller allowlist, so the whole module tree was live, and ten of the
    #: thirty modules the worker classifies as dangerous had no listed segment
    #: and no forbidden leaf. `sage.misc.lazy_import.LazyImport('os','system')`
    #: therefore executed while the bare `LazyImport` was refused. Any list of
    #: segments is one Sage release behind; refusing the ROOT is not.
    #:
    #: `gates._refuse_scrubbed_names` has applied exactly this rule to tool
    #: parameters since the `sage.all.unpickle_global` bypass, and for the same
    #: reason: no caller needs to traverse `sage` -- they write `matrix`,
    #: `integrate`, `codes.HammingCode` directly. `trusted_policy()` clears it,
    #: because the generated prelude does `import sage.all as _sage_ns`.
    forbidden_attribute_roots: tuple[str, ...] = ("sage",)
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
    # absent from builtins, namespace and allowlist alike -- but `x.eval`
    # can still reach a real method: `latex.eval` runs the LaTeX toolchain,
    # and that is the rule keeping it shut now that `latex` itself is offered.
    # `eval` alone, because `eval` alone was demonstrated: `latex.eval` runs
    # the LaTeX toolchain, and `latex` is offered now. `vars`, `locals` and
    # `input` were in this tuple for symmetry and came back out -- no reachable
    # object has a dangerous method by those names, and `f.vars` is the variable
    # list of a QEPCAD formula. Symmetry is not a security justification.
    forbidden_attribute_only_names: tuple[str, ...] = ("eval",)

    #: Names a caller may CALL but may not reach into. `latex(expr)` builds a
    #: string and the corpus does it 1,408 times; `latex` is also an object
    #: with thirteen public attributes, four of which run a toolchain --
    #: `latex.eval` and `latex.has_file` shell out, and `has_file` ran
    #: `call("kpsewhich %s" % name, shell=True)` as the container user on 10.9.
    #:
    #: Those four were refused by name, which is the enumeration shape item 79
    #: had to abandon for the `sage` tree: the list is only ever as good as the
    #: attributes someone thought of, and a future Sage adding a fourteenth
    #: would not be on it. The other nine are inert preamble and formatting
    #: settings -- inert because nothing here ever compiles LaTeX, which is a
    #: property of this server today rather than of the object.
    #:
    #: So attribute access on these names is deny-by-default. Measured against
    #: the corpus it costs 58 examples and keeps 1,408.
    call_only_names: tuple[str, ...] = ("latex",)
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
    # Modules whose `from <module> import *` is permitted, each mapping to the
    # exact public names the import may bind -- reviewed, screened clean as a
    # whole, and generated into star_exports.py. `rewrite_permitted_imports`
    # expands the star into these names before validation, and the import block
    # below permits an explicit `from <module> import a, b` when every name is
    # on the module's list. Empty by default; the generated mapping is the
    # default value, so a policy built without arguments carries it.
    star_export_modules: dict[str, frozenset[str]] = field(
        default_factory=lambda: STAR_EXPORTS
    )

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


def trusted_policy(policy: SecurityPolicy | None = None) -> SecurityPolicy:
    """Policy for code this server generates itself.

    The helper tools build their Sage snippets around sage_eval, which is
    forbidden to callers precisely because it evaluates a string after this
    validator has approved the AST. Server-generated code is not attacker
    controlled, so it may use it -- but only after the *user* fragments
    interpolated into it have been validated in their own right. See
    gates.validated_expression.

    Everything else in the policy still applies: generated code cannot import
    os, reach dunders, or call the other forbidden builtins.
    """
    base = policy or SECURITY_POLICY
    relaxed = tuple(name for name in base.forbidden_call_names if name not in _TRUSTED_CALLS)
    return replace(
        base,
        forbidden_call_names=relaxed,
        # The prelude does `import sage.all as _sage_ns` and reads attributes
        # off it; generated code is not attacker-controlled.
        forbidden_attribute_roots=(),
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
