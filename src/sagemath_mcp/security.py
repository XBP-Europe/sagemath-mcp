"""Security policy and AST validation for Sage worker execution."""

from __future__ import annotations

import ast
import logging
import re
import textwrap
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .imports import attribute_segments
from .policy import SECURITY_POLICY, SecurityPolicy, SecurityViolation
from .refusals import (
    format_violation,
    import_alternative,
    native_equivalent,
    reach_refusal,
    sage_spelling,
)
from .symbols import PREDEFINED_SYMBOLS

LOGGER = logging.getLogger(__name__)


def _max_depth(node: ast.AST, depth: int = 0) -> int:
    child_depths = [_max_depth(child, depth + 1) for child in ast.iter_child_nodes(node)]
    if not child_depths:
        return depth
    return max(child_depths)


# Sage's own ways of putting names into the caller's namespace. Each takes them
# from the object -- `variable_names()`, or the basis shorthands -- so what lands
# is that object's generators, and none of it is knowable before the call runs.
_NAME_INJECTING_METHODS: frozenset[str] = frozenset({
    "inject_variables",
    # `inject_shorthands` was deliberately excluded for a release: Sage routes
    # it through `get_main_globals()`, whose stack walk looks for the frame
    # named `__main__` -- the worker script's own globals, so nothing landed in
    # the session and gating on it bought a bare NameError. The worker now
    # stamps its namespace `__name__ = '__main__'`, exactly as Sage's doctest
    # runner stamps its test namespace (`sage/doctest/forker.py`), so the
    # shorthands land where the session reads and the gate means what it says.
    "inject_shorthands",
})


def injects_session_names(module: ast.Module) -> bool:
    """Does this code ask a Sage object to put names into the namespace?

    One question, three askers: the validator suspends the allowlist half of
    the name rule for the snippet, the worker diffs the namespace around the
    execution so the *next* call can read what arrived, and the doctest sweep
    marks the block as injected so its later examples are judged the way a
    session would judge them.
    """
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _NAME_INJECTING_METHODS
        for node in ast.walk(module)
    )


def attrcall_attribute_violation(
    name: object, policy: SecurityPolicy | None = None
) -> str | None:
    """Why this attribute name may not ride through `attrcall`, or None.

    `attrcall('save', path)(M)` wrote a real file: the string is attribute
    access the AST rules never see. But when the string is a *literal* it is
    right there to screen, and SageMath's own doctests use `attrcall` 155
    times, every one with a harmless literal. So the name is judged against
    every rule the dotted spelling would face -- called and accessed positions
    both, which is stricter than either alone -- and the dynamic form stays
    refused. Shared with the worker's runtime guard so the two screens cannot
    drift apart, which is how the fragment gate's token screen went stale.
    """
    policy = policy or SECURITY_POLICY
    if not isinstance(name, str) or not name.isidentifier():
        return "attrcall requires a plain identifier as the attribute name"
    if _is_dunder(name):
        return f"Access to dunder attribute '{name}' is blocked"
    if name in policy.forbidden_call_names or name in policy.forbidden_attribute_only_names:
        return f"Access to forbidden function '{name}' is blocked"
    if name in policy.forbidden_attribute_names:
        return f"Call to forbidden attribute '{name}' is blocked"
    if any(name.startswith(prefix) for prefix in policy.forbidden_attribute_prefixes):
        return (
            f"Access to '{name}' is blocked: writing files is not "
            "available to caller code"
        )
    return None


def _screened_attrcall(node: ast.AST, policy: SecurityPolicy) -> bool:
    """Is *node* an `attrcall('name', ...)` whose literal passes the screen?

    The shape is judged as strictly as the name: the first positional argument
    must be the literal, nothing may arrive as `name=` or `**kwds` (a runtime
    dict is a runtime string), and further arguments are ordinary values the
    validator sees on their own. Anything else falls through to the standing
    refusal of `attrcall`, message unchanged.
    """
    if not (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "attrcall"
    ):
        return False
    if not node.args or any(keyword.arg in (None, "name") for keyword in node.keywords):
        return False
    first = node.args[0]
    if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
        return False
    return attrcall_attribute_violation(first.value, policy) is None


def _raise_violation(
    message: str, *, code: str | None, policy: SecurityPolicy | None
) -> None:
    formatted = format_violation(message, code)
    if (policy or SECURITY_POLICY).log_violations:
        LOGGER.warning("Blocked Sage code: %s", formatted)
    raise SecurityViolation(message)


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


def _permitted_chain_nodes(module: ast.Module, policy: SecurityPolicy) -> set[int]:
    """Node ids inside a chain that is a permitted star-export spelling.

    `ast.walk` visits every node of `sage.rings.ideal.Katsura`, so the whole
    chain being permitted is not enough on its own: the walker also reaches the
    prefixes `sage.rings.ideal` and `sage.rings`, and the root `sage`, none of
    which is a listed module, and the reach rule would refuse the expression on
    one of those instead. This collects the prefixes and the root so the rule
    can skip exactly them.

    Only a chain that is permitted **in full** contributes, and each prefix is
    exempted only where it occurs inside such a chain -- `id()` of the node,
    not the spelling. So `sage.rings.ideal` written on its own is still the
    module object and still refused, and `sage.rings.ideal.Katsura.attr`, whose
    maximal chain is not listed, is refused on that maximal node.
    """
    permitted: set[int] = set()
    for node in ast.walk(module):
        if not isinstance(node, ast.Attribute):
            continue
        if not _star_export_spelling(node, policy):
            continue
        # The root is a Name -- `_star_export_spelling` established that -- so
        # this walks prefixes down to it and adds every one.
        current: ast.expr = node.value
        while isinstance(current, ast.Attribute):
            permitted.add(id(current))
            current = current.value
        permitted.add(id(current))
    return permitted


def _star_export_spelling(node: ast.Attribute, policy: SecurityPolicy) -> bool:
    """Is this dotted chain the long spelling of a permitted star export?

    `from sage.rings.ideal import *` is already permitted, and binds `Katsura`
    -- the module screened clean as a whole, so every public name in it is
    ordinary mathematics (`star_exports.py`). `sage.rings.ideal.Katsura` names
    the *same object* by a longer path, so permitting it grants nothing the
    star import does not already grant. One table authorizes both spellings,
    which is what keeps them from drifting apart.

    Deliberately exact, and everything about it fails closed:

    - The chain must end in a screened NAME. `sage.rings.ideal` on its own is
      the module object, and handing a caller one is the pivot items 61/62/63
      exist to prevent, so it stays refused.
    - Anything hanging off the name is a different, unlisted prefix:
      `sage.rings.ideal.Katsura.foo` asks whether `sage.rings.ideal.Katsura` is
      a listed module, which it is not.
    - A module the screen has not passed is simply absent, so
      `sage.misc.persist.unpickle_global` -- item 79's escape -- is refused by
      the same code path that permits `Katsura`, with no separate denylist to
      keep in step.
    """
    current: ast.expr = node
    while isinstance(current, ast.Attribute):
        current = current.value
    if not isinstance(current, ast.Name):
        # `f().sage.rings.ideal.Katsura` has the right segments and the wrong
        # root: `attribute_segments` omits a root that is not a Name, so the
        # chain reads as `sage.rings.ideal.Katsura` while `.sage` is an
        # attribute of whatever the call returned. Requiring a Name root is
        # what ties the spelling to the module it claims to name.
        return False
    # An Attribute rooted at a Name always yields at least two segments, so
    # `segments[:-1]` is never empty and needs no guard.
    segments = attribute_segments(node)
    names = policy.star_export_modules.get(".".join(segments[:-1]))
    return names is not None and segments[-1] in names


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
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            bound.add(node.id)
        # `ast.Del` is deliberately NOT here. Deleting a name is the opposite
        # of creating one, and counting it as a binding handed the caller the
        # allowlist exemption for free: `if False: del eval` followed by
        # reading `eval` validated, because `_bound_names` walks unreachable code
        # -- item 37's trap, which was closed for the `sage` root and left open
        # for every other name. Measured over the denied set, the spelling
        # unlocked thirteen names (REVIEW_ACTIONS 90). None of them reached
        # execution, because the namespace scrub and the restricted builtins
        # are the second lock and both held, but the first lock is supposed to
        # hold too.
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


@dataclass(frozen=True)
class _ValidationContext:
    """What the node rules may read about the snippet as a whole.

    Computed once by `validate_module` before the walk. Every rule only reads
    it; none of them changes anything, which is what lets them run one at a
    time in a fixed order.
    """

    policy: SecurityPolicy
    code: str | None
    bound: set[str]
    withheld_names: frozenset[str] | set[str]
    exempt_module_names: set[int]
    assigned_here: set[str]
    permitted_chain_nodes: set[int]
    called_names: set[int]
    injects_names: bool


def _refuse_import(node: ast.Import | ast.ImportFrom, ctx: _ValidationContext) -> None:
    """Refuse an import statement unless the policy allows imports."""
    policy = ctx.policy
    code = ctx.code
    if not policy.allow_imports:
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
        # A `from <vetted> import a, b` is permitted when every name is on
        # the module's screened list -- the star expansion above produces
        # exactly this, and a caller may also write it out. A name the
        # screen dropped is not on the list, so spelling out a dirty member
        # of an otherwise-listed module does not smuggle it in.
        star_permitted = (
            isinstance(node, ast.ImportFrom)
            and node.module in policy.star_export_modules
            and all(
                alias.name in policy.star_export_modules[node.module]
                for alias in node.names
            )
        )
        if not star_permitted and not all(
            _is_allowed_import(mod, policy) for mod in modules
        ):
            # Say what to do instead. Gemini opens numerical work with
            # `import numpy as np` or `from sage.all import *`, was told only
            # that imports are disabled, and did not recover across three
            # cases -- while the same questions passed on a client that
            # happened not to write the line. The namespace already holds
            # everything the import was for, which is a fix the caller can
            # act on; "disabled" is not.
            advice = next(
                (found for found in (import_alternative(mod) for mod in modules)
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


def _refuse_global_statement(node: ast.Global, ctx: _ValidationContext) -> None:
    """Refuse a ``global`` statement."""
    policy = ctx.policy
    code = ctx.code
    if policy.forbid_global_stmt:
        _raise_violation(
            "Global statements are not permitted in Sage executions",
            code=code,
            policy=policy,
        )


def _refuse_nonlocal_statement(node: ast.Nonlocal, ctx: _ValidationContext) -> None:
    """Refuse a ``nonlocal`` statement."""
    policy = ctx.policy
    code = ctx.code
    if policy.forbid_nonlocal_stmt:
        _raise_violation(
            "Nonlocal statements are not permitted in Sage executions",
            code=code,
            policy=policy,
        )


# Dunder access is the shortest path out of the sandbox:
# ().__class__.__bases__[0].__subclasses__() reaches subprocess.Popen,
# and __builtins__ reaches __import__ by attribute or by subscript.
# Blocking the whole namespace closes both in one rule.
def _refuse_dunder_attribute(node: ast.Attribute, ctx: _ValidationContext) -> None:
    """Refuse a dunder attribute."""
    policy = ctx.policy
    code = ctx.code
    if _is_dunder(node.attr):
        _raise_violation(
            f"Access to dunder attribute '{node.attr}' is blocked",
            code=code,
            policy=policy,
        )


def _refuse_dunder_name(node: ast.Name, ctx: _ValidationContext) -> None:
    """Refuse a dunder name, except the preparser's own temporaries."""
    policy = ctx.policy
    code = ctx.code
    if _is_dunder(node.id) and not _is_preparser_temp(node):
        _raise_violation(
            f"Access to dunder name '{node.id}' is blocked",
            code=code,
            policy=policy,
        )


def _refuse_dunder_subscript(node: ast.Subscript, ctx: _ValidationContext) -> None:
    """Refuse a subscript whose key is a dunder string, e.g. d['__builtins__'].

    A subscript key is a Constant, not a Name or Attribute, so no other rule
    inspects it: `d['__builtins__']` reads Python internals with none of them
    firing. That is the step from a namespace dict -- anything that hands one
    back -- to the real builtins (REVIEW_ACTIONS 101). Dunder keys are internals
    access, never mathematics, so this refuses the class regardless of what the
    base evaluates to. The attribute and name forms are refused by their own
    rules; this is the subscript form.
    """
    key = node.slice
    if isinstance(key, ast.Constant) and isinstance(key.value, str) and _is_dunder(key.value):
        _raise_violation(
            f"Access to dunder key '{key.value}' is blocked",
            code=ctx.code,
            policy=ctx.policy,
        )


def _refuse_unoffered_name(node: ast.Name, ctx: _ValidationContext) -> None:
    """Refuse reading a name that is neither offered nor the caller's own."""
    policy = ctx.policy
    code = ctx.code
    bound = ctx.bound
    withheld_names = ctx.withheld_names
    exempt_module_names = ctx.exempt_module_names
    called_names = ctx.called_names
    injects_names = ctx.injects_names
    if (
        policy.enforce_name_allowlist
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
        equivalent = native_equivalent(node.id)
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
        # The first sentence is the rule the corpus sweep keys on; what
        # follows it is advice, and the best advice is the spelling that
        # works. A name Sage never had gets that; anything else gets the
        # two honest possibilities.
        spelling = sage_spelling(node.id)
        _raise_violation(
            f"'{node.id}' is not a name this server offers. "
            + (f"SageMath spells it {spelling}." if spelling else
               "If it is a typo, check the spelling; if it is a SageMath "
               "function that should be available, it needs to be added to "
               "the allowlist"),
            code=code,
            policy=policy,
        )


# Reaching the attribute is the capability; calling it is one thing you
# can do next. Guarding only `Call(func=Attribute(...))` meant
# `f = latex.has_file; f(payload)` passed, and each of those spellings
# ran a shell on 10.9. That gap was as old as the list itself -- `popen`
# and `rmtree` were reachable the same way.
def _refuse_forbidden_attribute(node: ast.Attribute, ctx: _ValidationContext) -> None:
    """Refuse a forbidden attribute, called or not."""
    policy = ctx.policy
    code = ctx.code
    if node.attr in policy.forbidden_attribute_names:
        _raise_violation(
            f"Access to forbidden attribute '{node.attr}' is blocked",
            code=code,
            policy=policy,
        )


# A forbidden module is forbidden entirely. Requiring the attribute to
# ALSO be on a list of eighteen names meant os.system was blocked while
# os.listdir, os.environ and os.chmod were not -- and the README claimed
# subprocess.*, pathlib.* and socket.* were blocked when none of them were.
def _refuse_forbidden_attribute_chain(node: ast.Attribute, ctx: _ValidationContext) -> None:
    """Refuse reaching into a call-only name, a forbidden module or a forbidden parent."""
    policy = ctx.policy
    code = ctx.code
    bound = ctx.bound
    assigned_here = ctx.assigned_here
    permitted_chain_nodes = ctx.permitted_chain_nodes
    # Call-only names: the name itself is offered, reaching into it is
    # not. Checked on the immediate parent, so `latex.anything` is
    # refused while `latex(expr)` and a caller's own `latex` are not.
    if (
        isinstance(node.value, ast.Name)
        and node.value.id in policy.call_only_names
        and node.value.id not in assigned_here
    ):
        _raise_violation(
            f"'{node.value.id}' may be called but not reached into: "
            f"{node.value.id}(expr) builds a string, while its attributes "
            "run a LaTeX toolchain",
            code=code,
            policy=policy,
        )
    segments = attribute_segments(node)
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
    if (
        segments
        and segments[0] in policy.forbidden_attribute_roots
        and not _star_export_spelling(node, policy)
        and id(node) not in permitted_chain_nodes
    ):
        # Checked before anything else, and regardless of what the
        # caller bound: a caller-owned alias for the root was item 52's
        # escape, and the root here is offered anyway.
        raise SecurityViolation(reach_refusal(segments))
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
                # Only five forbidden parents are ALSO ordinary methods
                # on a mathematical object -- trace, sh, operator, pari,
                # oeis (`A.trace()`, `(x+y).operator()`, `E.pari()`).
                # Every other one -- os, sys, subprocess, socket, shutil,
                # pathlib, persist, cython, warnings, builtins, ... -- has
                # no method meaning at all, so a terminal one is a module
                # reference WHATEVER the root is. The old rule waved it
                # through whenever the root was not offered, on the theory
                # that a non-allowlisted root meant `<expr>.method`. That
                # is false when the root is a bound *module object*:
                # `dirichlet.free_module_element.sage.env.os` reached the
                # real os module with `os` as the terminal, past this very
                # branch, and `alias.system('id')` then ran a shell (item
                # 61). The star-export screen no longer lets a module bind
                # to a caller name, but the validator refuses the pivot
                # too now -- the object should not be reachable either.
                if segment in _TERMINAL_METHOD_NAMES:
                    # A plain object.method -- one or two segments -- or a
                    # longer method-on-method chain not rooted at an
                    # offered module name. The genuine module path
                    # `sage.misc.trace` / `sage.misc.sh` (rooted at the
                    # offered `sage`, three-plus segments) still falls
                    # through to the refusal below.
                    module_path = len(segments) >= 2 and root in policy.allowed_names
                    if len(segments) <= 2 or not module_path:
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


def _refuse_deleting_a_provided_name(node: ast.Name, ctx: _ValidationContext) -> None:
    """Refuse deleting a name this server provides."""
    policy = ctx.policy
    code = ctx.code
    if isinstance(node.ctx, ast.Del):
        # You may delete what you brought, not what the server provided.
        #
        # Deleting differs from assigning, which is why shadowing is fine
        # and this is not: `Integer = 1` replaces the name with the
        # caller's own value, while `del Integer` removes it from a
        # namespace that persists across calls. The Sage preparser rewrites
        # every integer literal to `Integer(...)`, so `del Integer` makes
        # `2 + 2` fail for the rest of the session -- verified against a
        # real worker, and about as confusing a failure as this server can
        # produce. `del x` breaks the predefined symbols the tools and
        # `evaluate_sage` are documented to agree on (`symbols.py`).
        #
        # A name the caller created is theirs to delete, and a name that
        # was never there raises NameError as it always did.
        if policy.enforce_name_allowlist and (
            node.id in policy.allowed_names or node.id in PREDEFINED_SYMBOLS
        ):
            restore = (
                f", and {node.id} = var('{node.id}') restores the symbol"
                if node.id in PREDEFINED_SYMBOLS
                else ""
            )
            _raise_violation(
                f"Deleting '{node.id}' is not permitted: it is a name this "
                "server provides, and the session keeps its namespace "
                "between calls, so removing it would break later work. "
                f"Assign to it instead if you want your own value{restore}",
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
def _refuse_forbidden_name_reference(node: ast.Name, ctx: _ValidationContext) -> None:
    """Refuse reading a forbidden root, function or module by name."""
    policy = ctx.policy
    code = ctx.code
    bound = ctx.bound
    exempt_module_names = ctx.exempt_module_names
    if isinstance(node.ctx, ast.Load):
        # A root whose tree cannot be traversed has no business being read
        # either: what comes back is a module object, and handing a caller
        # one is the pivot items 61/62/63 exist to prevent. Reading it bare
        # buys nothing anyway -- every attribute of it is refused above --
        # so this closes the invariant rather than trading anything for it.
        if (
            node.id in policy.forbidden_attribute_roots
            and id(node) not in exempt_module_names
        ):
            _raise_violation(
                f"Reaching into the '{node.id}' module is not permitted; "
                "name the function directly",
                code=code,
                policy=policy,
            )
        # A screened `attrcall('degree')` exempts its own func node here,
        # the way `operator` is exempted inside `operator.le`.
        if node.id in policy.forbidden_call_names and id(node) not in exempt_module_names:
            equivalent = native_equivalent(node.id)
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
def _refuse_forbidden_function_attribute(node: ast.Attribute, ctx: _ValidationContext) -> None:
    """Refuse a forbidden function reached as an attribute."""
    policy = ctx.policy
    code = ctx.code
    if (
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
def _refuse_persistence_attribute(node: ast.Attribute, ctx: _ValidationContext) -> None:
    """Refuse the attributes that write files (save, dump, export, write, ...)."""
    policy = ctx.policy
    code = ctx.code
    if any(
        node.attr.startswith(prefix) for prefix in policy.forbidden_attribute_prefixes
    ):
        _raise_violation(
            f"Access to '{node.attr}' is blocked: writing files is not "
            "available to caller code",
            code=code,
            policy=policy,
        )


def _refuse_forbidden_call(node: ast.Call, ctx: _ValidationContext) -> None:
    """Refuse calling a forbidden function or attribute."""
    policy = ctx.policy
    code = ctx.code
    exempt_module_names = ctx.exempt_module_names
    func = node.func
    if (
        isinstance(func, ast.Name)
        and func.id in policy.forbidden_call_names
        and id(func) not in exempt_module_names
    ):
        equivalent = native_equivalent(func.id)
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


# The node rules, by the AST type each one guards. Within a type the order is the
# order the rules were written in, which decides the first refusal a snippet
# with several faults is given; test_every_node_rule_is_registered checks that
# none is left out.
_NODE_RULES: dict[type[ast.AST], tuple[Callable[[Any, _ValidationContext], None], ...]] = {
    ast.Import: (_refuse_import,),
    ast.ImportFrom: (_refuse_import,),
    ast.Global: (_refuse_global_statement,),
    ast.Nonlocal: (_refuse_nonlocal_statement,),
    ast.Attribute: (
        _refuse_dunder_attribute,
        _refuse_forbidden_attribute,
        _refuse_forbidden_attribute_chain,
        _refuse_forbidden_function_attribute,
        _refuse_persistence_attribute,
    ),
    ast.Name: (
        _refuse_dunder_name,
        _refuse_unoffered_name,
        _refuse_deleting_a_provided_name,
        _refuse_forbidden_name_reference,
    ),
    ast.Subscript: (_refuse_dunder_subscript,),
    ast.Call: (_refuse_forbidden_call,),
}


def validate_module(
    module: ast.Module,
    *,
    code: str | None = None,
    policy: SecurityPolicy | None = None,
    extra_allowed_names: frozenset[str] | set[str] = frozenset(),
    withheld_names: frozenset[str] | set[str] = frozenset(),
    session_injects_names: bool = False,
) -> None:
    """Validate *module* against the configured security policy.

    ``withheld_names`` are names that exist in the worker's namespace but are
    not offered to callers. They are refused whatever else authorizes them,
    because a caller's *binding* must authorize a name the caller creates and
    not one that is already there holding something else. Binding is judged
    statically -- `leaked = smuggled(); smuggled = None` binds `smuggled` for
    the whole module -- so without this rule the read at the start is
    authorized while the name still holds the preloaded object.

    ``session_injects_names`` says an *earlier* snippet in this session ran a
    name-injecting call. The worker never passes it -- it records the names the
    injection actually created and hands them in as ``extra_allowed_names`` --
    but a static observer judging one snippet at a time (the doctest sweep)
    cannot run anything, so it asks for the same suspension the injecting
    snippet itself gets. Only the allowlist half is suspended; the withheld
    rule holds regardless.
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
    # `sage` is a Name node too, and the rule that refuses reading the root
    # bare would refuse `sage.rings.ideal.Katsura` before the attribute rule
    # decided the chain was a permitted star export. Only the root of such a
    # chain is exempted, so a bare `sage` -- or a root under any other chain --
    # stays refused; this is the `operator.le` treatment, for the same reason.
    # Names the caller bound to a value of its OWN -- an assignment, a def, a
    # parameter -- as opposed to a name an import brought in. The distinction
    # only matters for `call_only_names`, and it matters absolutely: `latex =
    # 1` gives the caller their own object, whose attributes are theirs, while
    # `from <module> import *` binds the REAL `latex` and would hand back the
    # attribute surface the call-only rule exists to close.
    #
    # That was not hypothetical. `sage.schemes.toric.fano_variety` is on the
    # curated star-export list and re-exports `latex`, so
    # `from sage.schemes.toric.fano_variety import *` followed by
    # `latex.engine` returned the real bound method (REVIEW_ACTIONS 92).
    assigned_here: set[str] = set()
    for node in ast.walk(module):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            assigned_here.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            assigned_here.add(node.name)
        elif isinstance(node, ast.arg):
            assigned_here.add(node.arg)

    permitted_chain_nodes = _permitted_chain_nodes(module, policy)
    exempt_module_names |= permitted_chain_nodes
    # The `attrcall` in `attrcall('degree')` earns the same treatment when its
    # literal passes the attribute screen: that one call is permitted, and the
    # bare name -- `f = attrcall`, the aliasing that defeats name rules -- stays
    # refused because only the screened call's own Name node is exempted.
    exempt_module_names |= {
        id(node.func)
        for node in ast.walk(module)
        if _screened_attrcall(node, policy)
    }

    # Names in call position, so a refusal can tell `r("'abc'")` apart from a
    # radius called `r`.
    called_names = {
        id(node.func)
        for node in ast.walk(module)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    # Does this snippet -- or, for a static observer, an earlier snippet in the
    # same session -- ask a Sage object to put names into the namespace?
    injects_names = session_injects_names or injects_session_names(module)

    ctx = _ValidationContext(
        policy=policy,
        code=code,
        bound=bound,
        withheld_names=withheld_names,
        exempt_module_names=exempt_module_names,
        assigned_here=assigned_here,
        permitted_chain_nodes=permitted_chain_nodes,
        called_names=called_names,
        injects_names=injects_names,
    )

    # One walk, and for each node only the rules for its type, in the order they
    # are listed in _NODE_RULES. A node has exactly one type, so the rules that can
    # fire on it -- and so the first refusal a snippet gets -- are the same as when
    # this was a single loop of `if isinstance(node, ...)` blocks.
    for node in ast.walk(module):
        for rule in _NODE_RULES.get(type(node), ()):
            rule(node, ctx)

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
