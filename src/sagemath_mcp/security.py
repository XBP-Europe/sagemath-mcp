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
    max_source_chars: int = 8_000
    max_ast_nodes: int = 2_500
    max_ast_depth: int = 75
    allow_imports: bool = False
    forbid_global_stmt: bool = True
    forbid_nonlocal_stmt: bool = True
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
        "eval",
        "exec",
        "compile",
        "__import__",
        "open",
        "input",
        "globals",
        "locals",
        "vars",
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
        "sh",
        "get_remote_file",
        "loads",
        "dumps",
        "save",
        "save_session",
        "load_session",
        "db",
        "db_save",
        "sageobj",
        "trace",
        "edit",
        "detach",
        # Sage's interfaces to other CAS programs: each spawns the real thing,
        # and those have shell escapes of their own. The worker removes every
        # name sage.interfaces.all exports; these are listed so the common
        # attempts fail with a policy message rather than a NameError.
        "gp",
        "maxima",
        "gap",
        "singular",
        "octave",
        "magma",
        "mathematica",
        "maple",
        "matlab",
        "macaulay2",
        "sage0",
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
    )
    # Persistence methods, matched by prefix rather than by name. `.dump()`,
    # `.save_image()` and `.export_jmol()` each wrote a file that no rule
    # mentioned, and enumerating the rest of Sage's persistence API one method at
    # a time is the same losing game as the namespace denylist was.
    #
    # Caller code only: trusted_policy() clears this, because the plot templates
    # legitimately call .savefig(buffer) -- to a BytesIO, never a path.
    forbidden_attribute_prefixes: tuple[str, ...] = ("save", "dump", "export")
    forbidden_attribute_names: tuple[str, ...] = (
        "system",
        "popen",
        "popen2",
        "popen3",
        "remove",
        "rmdir",
        "unlink",
        "rmtree",
        "walk",
        "spawnl",
        "spawnlp",
        "spawnv",
        "spawnvp",
        "execv",
        "execvp",
        "execvpe",
        "fork",
        "forkpty",
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
    if source_length > policy.max_source_chars:
        _raise_violation(
            f"Sage code exceeds maximum length ({source_length} > {policy.max_source_chars})",
            code=code,
            policy=policy,
        )

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
                _raise_violation(
                    "Import statements are disabled for Sage executions",
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
                node.id not in bound and node.id not in policy.allowed_names
            ))
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
            if _looks_like_an_undeclared_symbol(node.id):
                _raise_violation(
                    f"'{node.id}' is not defined. This server predefines the symbols "
                    f"{_PREDEFINED_LIST}, so declare it first with "
                    f"var('{node.id}') -- or assign it a value.",
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
        # A forbidden module is forbidden entirely. Requiring the attribute to
        # ALSO be on a list of eighteen names meant os.system was blocked while
        # os.listdir, os.environ and os.chmod were not -- and the README claimed
        # subprocess.*, pathlib.* and socket.* were blocked when none of them were.
        if isinstance(node, ast.Attribute):
            # Any segment, not just the root: sage.misc.temporary_file.os.getuid()
            # is rooted at the permitted `sage` and reaches os in the middle.
            for segment in _attribute_segments(node)[:-1]:
                if segment in policy.forbidden_attribute_parents:
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
                _raise_violation(
                    f"Reference to forbidden name '{node.id}' is blocked",
                    code=code,
                    policy=policy,
                )
            if node.id in policy.forbidden_attribute_parents:
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
        if isinstance(node, ast.Attribute) and node.attr in policy.forbidden_call_names:
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
                _raise_violation(
                    f"Call to forbidden function '{func.id}' is blocked",
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
