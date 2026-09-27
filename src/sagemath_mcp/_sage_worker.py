"""Subprocess worker that executes SageMath code with persistent state."""

from __future__ import annotations

import ast
import contextlib
import io
import json
import os
import sys
import time
import traceback
from types import SimpleNamespace
from typing import Any

from sagemath_mcp import scrub_catalog
from sagemath_mcp._artifacts import ALLOWED_CALLER_NAMES
from sagemath_mcp.imports import rewrite_permitted_imports
from sagemath_mcp.policy import SECURITY_POLICY, trusted_policy
from sagemath_mcp.refusals import native_equivalent
from sagemath_mcp.security import (
    _bound_names,
    _looks_like_an_undeclared_symbol,
    attrcall_attribute_violation,
    check_source_length,
    injects_session_names,
    normalize_caller_code,
    validate_module,
)
from sagemath_mcp.symbols import PREDEFINED_SYMBOLS

PURE_PYTHON = os.getenv("SAGEMATH_MCP_PURE_PYTHON") == "1"
STARTUP_CODE = os.getenv("SAGEMATH_MCP_STARTUP", "from sage.all import *")


_STARTUP_ERROR: str | None = None

# Names the caller bound in code that passed validation.
#
# NOT the namespace diff, which is what this used to be. Diffing trusts anything
# the namespace gained, and `lazy_import('os', 'system')` gains a binding to
# os.system without reading a single forbidden name: call one created it, call two
# read it back as "the caller's own", and ran a shell. Recording what validated
# code *statically bound* closes that for every such primitive, including ones
# nobody has found yet -- a name only becomes trusted by appearing as a target in
# code the policy already approved.
_CALLER_BOUND_NAMES: set[str] = set()
# Snapshot of what the namespace held before any caller code ran.
_WITHHELD_NAMES: frozenset[str] = frozenset()


def _guarded_attrcall(name: object, *args: Any, **kwds: Any) -> Any:
    """Sage's `attrcall`, behind the attribute screen.

    The screen is the same function the validator applies to the literal
    (`attrcall_attribute_violation`), so the static and runtime judgements
    cannot drift apart. For a permitted name the real `attrcall` answers, with
    its full REPL semantics -- sort keys, mapping over families, equality; the
    pure-Python harness gets a closure that does the one thing tests need.
    """
    reason = attrcall_attribute_violation(name)
    if reason is not None:
        raise ValueError(f"Blocked attrcall: {reason}")
    if PURE_PYTHON:
        def _call(obj: Any) -> Any:
            return getattr(obj, name)(*args, **kwds)

        return _call
    from sage.misc.call import attrcall as _sage_attrcall

    return _sage_attrcall(name, *args, **kwds)


def _noop_set_verbose(*args: Any, **kwargs: Any) -> None:
    """`set_verbose` offered to caller code as a harmless no-op.

    The real one lives in `sage.misc.verbose`, scrubbed by provenance because a
    sibling (`set_verbose_files`) writes to a caller-chosen path. `set_verbose`
    itself only sets a global chattiness level, which has no surface over MCP --
    results come back as strings and progress is the streaming tool's job. It is
    offered as a no-op so a doctest that opens with `set_verbose(2)` runs instead
    of being refused for setup noise. See REVIEW_ACTIONS item 64.
    """
    return None


# Callables offered to caller code in place of a scrubbed Sage global. The scrub
# removes them by name, so they are (re)installed AFTER it -- at startup and
# after every reseal. Without the re-install `attrcall` silently stopped working
# after the first specialised-tool call, which reseals the namespace.
_CALLER_SHIMS: dict[str, Any] = {
    "attrcall": _guarded_attrcall,
    "set_verbose": _noop_set_verbose,
}
# Of those, the names a caller may READ freely, bare and in any position.
# `attrcall` is deliberately NOT here: it is refused bare and permitted only as a
# screened literal call (item 59), so it stays subject to deny-by-default.
# `set_verbose` is harmless, so it is offered outright.
_OFFERED_SHIM_NAMES: frozenset[str] = frozenset({"set_verbose"})


def _install_caller_shims(ns: dict[str, Any]) -> None:
    """Put the caller shims back after a scrub has removed them."""
    for name, shim in _CALLER_SHIMS.items():
        ns[name] = shim


def _auto_declarable_symbols(
    module: ast.Module, offered: frozenset[str] | set[str], withheld: frozenset[str] | set[str]
) -> frozenset[str]:
    """Symbol-shaped free names evaluate_sage should declare, not refuse.

    SageMath's SR declares a symbol when it parses one out of a string --
    `SR("a*b")` creates `a` and `b` -- and the specialised tools follow that
    contract. `evaluate_sage` runs real Python, where `w + 1` is a NameError, and
    so refused these with "declare it first with var('w')". This closes that gap
    for the same narrow, typo-guarded shape the tools use: a letter with an
    optional index, or a Greek name (`w`, `x_2`, `k1`, `alpha`). `sinn`, `foobar`
    and every multi-letter name stay refused, so a typo is still an error, not a
    silent empty symbol.

    A name already offered -- allowlisted, a session variable, a shim, or bound
    in this snippet -- is left alone, so a caller who set `w = 5` earlier keeps
    it. A withheld name is never declared: it holds something real. And a name
    that is *called* and has a native equivalent keeps its redirect -- `r` is a
    radius as a bare symbol but the R interface as `r(...)`, exactly the
    distinction the validator already draws.
    """
    called = {
        id(node.func)
        for node in ast.walk(module)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    result: set[str] = set()
    for node in ast.walk(module):
        if not (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)):
            continue
        name = node.id
        if name in offered or name in withheld:
            continue
        if not _looks_like_an_undeclared_symbol(name):
            continue
        if id(node) in called and native_equivalent(name) is not None:
            continue
        result.add(name)
    return frozenset(result)


def _declare_symbols(namespace: dict[str, Any], names: frozenset[str]) -> None:
    """Bind each auto-declarable symbol as `var(name)`, unless already present.

    Session state wins: a name the caller already assigned is not overwritten
    with a symbol. Uses the namespace's own `var`, so the pure-Python harness
    (which has none) simply skips -- the feature is Sage's.
    """
    var = namespace.get("var")
    if var is None:
        return
    for name in names:
        if name not in namespace:
            with contextlib.suppress(Exception):
                namespace[name] = var(name)


def _build_namespace() -> dict[str, Any]:
    # NOTE: Each worker keeps its own global namespace. We allow a single
    # preload statement so sessions can bootstrap Sage or the lightweight math
    # shim used during testing. By seeding __builtins__ explicitly we avoid
    # inheriting ambient globals from the worker process.
    global _STARTUP_ERROR
    ns: dict[str, Any] = {"__builtins__": __builtins__}
    # Sage's `inject_variable` -- and through it `inject_shorthands` and every
    # other route into "the main global namespace" -- writes to
    # `get_main_globals()`, which walks the stack for the frame whose
    # `__name__` is `__main__`. In the REPL the user's namespace is `__main__`;
    # here the walk used to end in this script's own globals, so injections
    # printed their "Defining s" lines and landed where no session could read
    # them. Stamping the namespace is Sage's own fix: the doctest runner does
    # exactly this to its test namespace (`sage/doctest/forker.py`).
    ns["__name__"] = "__main__"
    preload = "from math import *" if PURE_PYTHON else STARTUP_CODE
    if preload:
        try:
            # The preload needs real builtins: importing sage.all uses
            # __import__, open and more. Restrict only afterwards, so user code
            # never sees them.
            exec(preload, ns)
            _STARTUP_ERROR = None
        except Exception as exc:
            _STARTUP_ERROR = f"Startup code failed: {exc}"
            print(
                json.dumps({"ok": False, "startup_error": _STARTUP_ERROR}),
                file=sys.stderr,
            )
    ns["__builtins__"] = _restricted_builtins()
    _strip_forbidden_modules(ns)
    _strip_dangerous_sage_names(ns)
    # The scrub removed Sage's `attrcall` with the rest of `sage.misc.call`,
    # because a runtime string defeats every attribute rule. What returns under
    # the name screens its string against those same rules first -- so the
    # validator can permit the literal spelling SageMath's own doctests use 155
    # times, and even code that somehow reached the object with a computed
    # string gets a ValueError, not a file. Installed with the other shims.
    _install_caller_shims(ns)
    if not PURE_PYTHON:
        # Sage's REPL predefines x and importing sage.all does not even provide
        # that. The other three are this server's own convention, matching the
        # prelude the specialised tools have always used -- see symbols.py for
        # why exactly these four and no more.
        for symbol in PREDEFINED_SYMBOLS:
            if symbol not in ns:
                with contextlib.suppress(Exception):
                    ns[symbol] = ns["SR"].var(symbol)
    _CALLER_BOUND_NAMES.clear()      # a fresh namespace has no caller names in it
    global _WITHHELD_NAMES
    _WITHHELD_NAMES = _withheld_names(ns)
    return ns


def _strip_dangerous_sage_names(ns: dict[str, Any]) -> int:
    """Remove Sage helpers that execute, compile, fetch or write.

    Uses the baked-in list: this runs at every worker start, and re-deriving it
    there cost more than the protection was worth. The lists are read through
    the `scrub_catalog` module at call time, not bound at import, so what a test
    puts there is what the strip removes.
    """
    removed = 0
    denied = (*scrub_catalog.DANGEROUS_SAGE_NAME_LIST, *scrub_catalog.DANGEROUS_BARE_NAMES)
    for name in denied:
        if name in ns:
            del ns[name]
            removed += 1
    # And from `sage.all`, which is where sage_eval looks. See
    # _strip_from_sage_all: without this the whole denylist is decorative on
    # every path that goes through a generated template.
    if not PURE_PYTHON:
        with contextlib.suppress(Exception):
            _strip_from_sage_all(denied)
    return removed


def _reseal_namespace(ns: dict[str, Any], introduced: frozenset[str] = frozenset()) -> None:
    """Re-apply the startup scrub, and re-take the withheld snapshot.

    The generated prelude runs `from sage.all import *` in this same persistent
    namespace, which puts back every name the startup scrub removed. That was
    remote code execution: `unpickle_global` is guarded by the scrub alone --
    unlike `cython` or `pari`, which the AST rules refuse by name -- so after
    any specialised tool call it was reachable again by a caller who had bound
    the name in dead code.

    Sealing at startup is therefore not enough; the namespace has to be resealed
    whenever something has run that could have repopulated it. Caller-created
    names are left alone: they are the point of a stateful session, and they
    cannot reintroduce a scrubbed helper, because caller code cannot import.
    """
    _strip_forbidden_modules(ns)
    _strip_dangerous_sage_names(ns)
    # The scrub removes the shims by name (`attrcall`, `set_verbose` are on the
    # denylist), so put them back -- otherwise they work at startup and vanish
    # after the first specialised-tool call, which reseals.
    _install_caller_shims(ns)
    # A name trusted code introduced is not the caller's, whatever they bound
    # earlier. Without this a caller can reserve the templates' internals in
    # dead code -- `if False: _fig = 1` -- and collect the objects a later tool
    # call builds under them. Diffing the namespace is sound used this way: to
    # distrust what appeared, never to trust it.
    _CALLER_BOUND_NAMES.difference_update(introduced)
    global _WITHHELD_NAMES
    _WITHHELD_NAMES = frozenset(
        name for name in ns
        if name not in ALLOWED_CALLER_NAMES
        and name not in _CALLER_BOUND_NAMES
        and name not in _OFFERED_SHIM_NAMES
    )


def _strip_from_sage_all(names: Any) -> int:
    """Remove names from `sage.all` itself, not only from the worker namespace.

    The scrub protects caller code, which runs `exec` against the worker
    namespace. It does *not* protect a tool's fragment, because every generated
    template is built on `sage_eval` -- and `sage_eval` resolves against
    `sage.all`'s own globals, never consulting the namespace it was handed. So
    with the namespace scrubbed clean, this still returned the real function:

        sage_eval('unpickle_global')   -> cython_function_or_method

    and the same for `cython`, `sh`, `attrcall`, `os` and `maxima_calculus`.
    Every name the denylist removes was reachable that way. Nothing was
    *exploitable*: a caller string reaching a template must first pass
    `validated_expression`, which enforces the allowlist. But that made the
    gate the only lock on that path rather than the second, and this file's
    whole model is that the object should not be there either.

    Process-local and deliberate: this worker exists to run untrusted
    mathematics, so its own copy of `sage.all` has no business holding a shell.
    """
    import sage.all

    removed = 0
    for name in names:
        if name in _TRUSTED_TEMPLATE_IMPORTS:
            continue
        if name in sage.all.__dict__:
            del sage.all.__dict__[name]
            removed += 1
    return removed


# What generated code imports from `sage.all` by name, and must keep finding
# there. `sage_eval` is on the denylist -- it comes from `sage.misc.sage_eval`,
# which the scrub removes wholesale -- and every template is built on it, so
# stripping it from the module broke all 31 Sage-backed tools at once. The
# templates import it explicitly under the trusted policy; callers cannot,
# because `sage_eval` is a forbidden call name for them and no import of theirs
# survives validation.
_TRUSTED_TEMPLATE_IMPORTS = frozenset({"sage_eval", "preparse", "sage_input", "latex"})


def _strip_forbidden_modules(ns: dict[str, Any]) -> None:
    """Drop module objects the policy forbids from the user namespace.

    `from sage.all import *` binds os, sys and friends as ordinary globals, so
    `m = os` handed caller code the real module. The validator now refuses to
    read those names, and this makes the object unreachable even if it does.

    One module survives, and only in pieces. `operator` stays a forbidden parent
    -- `m = operator` is refused, and so is every attribute of it -- except for
    the arithmetic and comparison functions named in
    `SecurityPolicy.allowed_module_attributes`, which the validator lets through
    one at a time. Keeping the object in the namespace is what makes those
    spellings resolve; keeping the module forbidden is what makes everything
    else about it, including anything a future Python adds, refused by default.
    """
    permitted = {module for module, _ in SECURITY_POLICY.allowed_module_attributes}
    forbidden = [
        name for name in SECURITY_POLICY.forbidden_attribute_parents
        if name not in permitted
    ]
    for name in forbidden:
        ns.pop(name, None)
    if not PURE_PYTHON:
        with contextlib.suppress(Exception):
            _strip_from_sage_all(forbidden)


# Builtins that are dangerous in this context and have no place in a maths
# expression. The AST policy blocks these names too; removing them from the
# namespace is the backstop for when it misses a spelling -- as it did for
# `f = open`, which the validator only caught in call position.
_DENIED_BUILTINS = frozenset(
    {
        "open",
        "eval",
        "exec",
        "compile",
        "input",
        "breakpoint",
        "globals",
        "locals",
        "vars",
        "memoryview",
        "help",
        "exit",
        "quit",
    }
)

# __import__ is NOT in that list, and removing it was tried and reverted.
# Item 18 escalated through it, so denying it looks right -- but Sage needs it
# from this namespace: with it removed, Singular's polynomial string formatting
# raises KeyError('__import__') from inside sage.libs.singular, and that is
# Cython internals rather than anything the caller wrote. The defence against
# item 18 is therefore the validation gate on every string that reaches a
# trusted template, not the namespace backstop, which cannot cover this name.


def _restricted_builtins() -> dict[str, Any]:
    """Builtins for user code: everything except the dangerous handful.

    The AST policy blocks these names too; removing them from the namespace is
    what still holds when the policy cannot see the code at all -- which is the
    case for any string handed to sage_eval at runtime.
    """
    source = __builtins__ if isinstance(__builtins__, dict) else vars(__builtins__)
    return {name: value for name, value in source.items() if name not in _DENIED_BUILTINS}


# Runtime errors with a Sage-specific cause a model does not know, and the fix.
#
# Each row is (exception type, a substring of its message, the hint). They were
# collected by watching models fail: the 2026-09-15 tool-surface measurement
# lost cases to every one of them, and a model that reads "'float' object has no
# attribute 'n'" retries with another `.n()` because it does not know that a
# `numerical_integral` result is a Python float. The hint is appended to the
# message the model reads; the type and traceback are untouched. Matching is on
# the message text and the type only, so the same table serves the real worker
# and the pure-Python one. Nothing here can hide an error: a hint is added,
# never substituted.
_RUNTIME_HINTS: tuple[tuple[str, str, str], ...] = (
    ("AttributeError", "'float' object has no attribute 'n'",
     "this is a Python float (numerical_integral results, float(...) and RDF "
     "arithmetic produce them) and has no .n(); wrap it: N(value) or RR(value)"),
    ("AttributeError", "'int' object has no attribute 'n'",
     "this is a Python int (len(), range() and indices produce them) and has no "
     ".n(); wrap it: N(value) or Integer(value)"),
    ("TypeError", "to a rational",
     "QQ('...') and Rational('...') do not parse decimal or scientific notation; "
     "use RR('6.62607015e-34') or RealField(200)('...') for more digits, then "
     "QQ(...) if a rational is wanted"),
    ("TypeError", "cannot approximate to a precision of",
     "the value is a 53-bit machine float (RDF, float, or a numerical_integral "
     "result) and more digits cannot be recovered from it; compute at the "
     "precision you need from the start: N(exact_expression, digits=...) or "
     "RealField(200)(...)"),
    ("TypeError", "RealNumber' object is not callable", "NUMBER_CALLED"),
    ("TypeError", "RealLiteral' object is not callable", "NUMBER_CALLED"),
    ("TypeError", "RealDoubleElement_gsl' object is not callable", "NUMBER_CALLED"),
    ("TypeError", "Integer' object is not callable", "NUMBER_CALLED"),
    ("TypeError", "Rational' object is not callable", "NUMBER_CALLED"),
    ("TypeError", "'float' object is not callable", "NUMBER_CALLED"),
    ("TypeError", "'int' object is not callable", "NUMBER_CALLED"),
    ("SyntaxError", "unexpected character after line continuation character",
     "a stray backslash: usually a newline that arrived as the two characters "
     "backslash and n (double-escaped by the client), or a shell-style line "
     "continuation; send real newlines"),
)

# One hint shared by every "a number is not a function" row above.
_NUMBER_CALLED_HINT = (
    "a number is not a function: write multiplication explicitly (2*x, not 2(x)), "
    "and check that a variable has not shadowed the function you meant (a "
    "session that ran `sum = 0` has no sum() until reset)"
)


def _hint_for(exc: BaseException) -> str | None:
    """The hint for *exc*, or None when the error is not one of the known ones."""
    kind = exc.__class__.__name__
    text = str(exc)
    for exc_type, needle, hint in _RUNTIME_HINTS:
        if kind == exc_type and needle in text:
            return _NUMBER_CALLED_HINT if hint == "NUMBER_CALLED" else hint
    return None


def _error_payload(exc: BaseException, stdout_value: str) -> dict[str, Any]:
    """The failure response for *exc*: type, message (with a hint when one is
    known), traceback and whatever stdout was produced before it."""
    message = str(exc)
    hint = _hint_for(exc)
    if hint:
        message = f"{message}. Hint: {hint}."
    return {
        "ok": False,
        "stdout": stdout_value,
        "error": {
            "type": exc.__class__.__name__,
            "message": message,
            "traceback": traceback.format_exc(),
        },
    }


def _format_result(value: Any) -> str:
    """Render a result the way the Sage REPL renders it.

    `repr` stacks a sequence of matrices one after another; Sage lays them out
    side by side, in columns, and that is what its own doctests record:

        (
        [1 0]  [0 1]  [0 0]  [0 0]
        [0 0], [0 0], [1 0], [0 1]
        )

    The difference is not cosmetic for a server whose entire output is text --
    a basis of eight 3x3 matrices is 32 lines one way and 4 the other. It was
    found by executing SageMath's doctests rather than by reading them, and it
    was the only class of disagreement left in that suite.

    Sage's own `format_list` does it, so nothing here reimplements the layout:
    it returns the tall form when the entries are tall and plain `repr`
    otherwise, so `[1, 2, 3]` is untouched. The formatter lives in
    `sage.repl.display`, which callers do not get -- this is the worker
    importing it internally, as it already does for `latex` when a tool asks
    for LaTeX.
    """
    if not PURE_PYTHON and isinstance(value, (list, tuple)) and value:
        try:
            if _wants_tall_layout(value):
                from sage.repl.display.util import format_list

                return format_list(value)
        except Exception:
            pass
    return repr(value)


def _wants_tall_layout(sequence: Any) -> bool:
    """Sage's own condition for laying a sequence out in columns.

    Not every multi-line repr gets the treatment, and guessing which do was
    wrong twice: a list of morphisms has a multi-line repr and Sage prints it
    stacked, while a list of matrices gets columns. The rule is in
    `sage.repl.display.fancy_repr.TallListRepr` and it is an opt-in -- an
    element, or the parent it comes from, has to say it is ascii art:

        o._repr_option('ascii_art')            # the element says so
        o.parent()._repr_option('element_ascii_art')   # its parent does

    MatrixSpace sets the second; morphisms set neither. Reading that rather
    than approximating it is the difference between matching SageMath's
    doctests and inventing a third layout.
    """
    for element in sequence:
        for probe in (
            lambda o: o._repr_option("ascii_art"),
            lambda o: o.parent()._repr_option("element_ascii_art"),
        ):
            try:
                if probe(element):
                    return True
            except (AttributeError, TypeError):
                continue
    return False


def _latex(result: Any) -> str | None:
    if result is None:
        return None
    try:
        if PURE_PYTHON:
            # Optional sympy support for nicer formatting during tests/dev.
            from sympy import latex as sympy_latex  # type: ignore

            return sympy_latex(result)  # pragma: no cover - requires sympy
        from sage.all import latex as sage_latex  # type: ignore

        return sage_latex(result)
    except Exception:  # pragma: no cover - best effort only
        return None


def _preparse(code: str) -> str:
    """Turn caller code into the Python that Sage's own REPL would run.

    Without this the tool advertised "SageMath code" and executed plain Python:
    `2^3` was 1 rather than 8, `K.<a> = NumberField(...)` was a syntax error, and
    integer literals were machine ints rather than Sage Integers. The specialised
    tools have always preparsed, via sage_eval, so the two paths disagreed about
    the language they accepted.

    Caller code only. Server-generated templates are already plain Python -- a
    lint keeps `^` out of them -- and preparsing them would change their meaning.
    """
    code = normalize_caller_code(code)
    if PURE_PYTHON:
        return code
    try:
        from sage.repl.preparse import preparse
    except Exception:  # pragma: no cover - no Sage in this interpreter
        return code
    return preparse(code)


def _withheld_names(ns: dict[str, Any]) -> frozenset[str]:
    """Names present at startup that callers are not offered.

    Under the default startup this is only dunders, because the allowlist is
    generated from exactly this namespace. It stops being only dunders the
    moment anything else puts a name here -- a custom `SAGEMATH_MCP_STARTUP`,
    or a Sage upgrade landing before the allowlist is regenerated -- and those
    names must stay unreachable rather than becoming reachable to any caller who
    happens to assign to them.

    Taken once, before any caller code runs. Recomputing it per call would sweep
    up the caller's own variables: they live in this same namespace, so `total`
    would be withheld on the call after the one that created it.
    """
    return frozenset(
        n for n in ns
        if n not in ALLOWED_CALLER_NAMES and n not in _OFFERED_SHIM_NAMES
    )


def _split_code(
    code: str, trusted: bool = False,
    session_names: frozenset[str] | set[str] = frozenset(),
    withheld: frozenset[str] = frozenset(),
) -> SimpleNamespace:
    """Return the executable and tail expression chunks for *code*.

    *trusted* selects the policy for code this server generated itself, which
    needs sage_eval. Caller-supplied code never sets it.
    """

    if not trusted:
        # The caller's own length first, so the number in the message is the one
        # they can measure.
        check_source_length(code)
        code = _preparse(code)
    # Validate what will actually run: the preparsed source, not what was typed.
    # Before parsing, not after: the parser gives up on a long enough snippet
    # and reports a RecursionError, which tells the caller nothing they can act
    # on and leaves the length limit decorative.
    # And again on what will actually be parsed: the preparser can expand a
    # snippet under the limit into one far over it, and the parser gives up with
    # a RecursionError that tells the caller nothing.
    check_source_length(code, after_preparse=not trusted)
    module = ast.parse(code, mode="exec", type_comments=True)
    # NOTE: validate_module enforces our safety policy before compiling. This
    # runs once per request, keeping the execution fast while guarding against
    # disallowed imports/constructs early.
    policy = trusted_policy() if trusted else SECURITY_POLICY
    if not trusted:
        # Drop the imports that would change nothing -- an unused reflex line, a
        # name the namespace already holds -- *before* validating, so that what
        # is checked is still exactly what runs. The rewrite only removes
        # imports and binds names already offered, so it can never widen what
        # the validator then sees.
        module = rewrite_permitted_imports(
            module, offered=ALLOWED_CALLER_NAMES, policy=policy
        )
    # Symbol-shaped free names evaluate_sage would otherwise refuse are declared
    # as symbols instead (caller code only -- generated templates have the
    # allowlist off and declare their own). Computed before validation and handed
    # in as allowed, so the validator that used to refuse them now passes them,
    # and _execute binds each as var(name) before running.
    auto_symbols: frozenset[str] = frozenset()
    if not trusted:
        offered = (
            set(session_names)
            | set(_OFFERED_SHIM_NAMES)
            | set(ALLOWED_CALLER_NAMES)
            | _bound_names(module)
        )
        auto_symbols = _auto_declarable_symbols(module, offered, withheld)
    # The offered shims (`set_verbose`) are readable like an allowlisted name;
    # they live in the namespace as no-ops, not on the generated allowlist, so
    # they are offered here instead. `attrcall` is not among them -- it stays a
    # screened-call-only exemption.
    validate_module(
        module, code=code, policy=policy,
        extra_allowed_names=frozenset(session_names) | _OFFERED_SHIM_NAMES | auto_symbols,
        withheld_names=withheld,
    )
    bound_here: frozenset[str] = frozenset()
    if trusted:
        # Every name generated code binds belongs to it, whether the binding
        # creates the name or replaces one the caller had. Read statically,
        # because a namespace diff sees only the first kind.
        bound_here = frozenset(_bound_names(module))
    else:
        # Approved, so what it binds is readable on later calls in this session
        # -- except a name that is already live and not offered, which the
        # caller is shadowing rather than creating. An auto-declared symbol is
        # the caller's from now on too: the var() binding persists in the
        # namespace, so the session should keep offering the name.
        _CALLER_BOUND_NAMES.update((_bound_names(module) | auto_symbols) - withheld)
    # `A.inject_variables()` creates names while the snippet runs. The validator
    # lets the snippet read them; this tells _execute to find out what they were,
    # so the *next* call can read them too -- which is what makes a session a
    # session rather than a sequence of snippets.
    injects = injects_session_names(module)
    ast.fix_missing_locations(module)
    # `bound_here` rides along so _execute can hand it to the reseal.
    if module.body and isinstance(module.body[-1], ast.Expr):
        prefix = ast.Module(
            body=list(module.body[:-1]),
            type_ignores=list(getattr(module, "type_ignores", [])),
        )
        tail = ast.Expression(body=module.body[-1].value)
        ast.fix_missing_locations(prefix)
        ast.fix_missing_locations(tail)
        return SimpleNamespace(bound_here=bound_here, prefix=prefix, tail=tail,
                               is_expr=True, injects=injects, auto_symbols=auto_symbols)
    return SimpleNamespace(bound_here=bound_here, prefix=module, tail=None,
                           is_expr=False, injects=injects, auto_symbols=auto_symbols)


class _StreamingStdout(io.StringIO):
    """Captures stdout while emitting each completed line as it is produced.

    The worker answers one JSON response per request, so a caller previously saw
    nothing until the computation finished -- the streaming tool split the output
    only after awaiting the whole evaluation. Emitting line events on the same
    channel lets the parent forward progress while the computation is still
    running.
    """

    def __init__(self, msg_id: str, sink) -> None:
        super().__init__()
        self._msg_id = msg_id
        self._sink = sink          # the real stdout, captured before redirection
        self._pending = ""

    def write(self, text: str) -> int:  # type: ignore[override]
        written = super().write(text)   # keep the full text for the final response
        self._pending += text
        while "\n" in self._pending:
            line, self._pending = self._pending.split("\n", 1)
            self._emit(line)
        return written

    def flush(self) -> None:  # type: ignore[override]
        if self._pending:
            self._emit(self._pending)
            self._pending = ""

    def _emit(self, line: str) -> None:
        print(
            json.dumps({"type": "stdout", "id": self._msg_id, "text": line}),
            file=self._sink,
            flush=True,
        )


# The JSON protocol's private stream, populated by _shield_protocol_stream()
# when running as the actual worker process. None means "not shielded" -- the
# in-process test harness -- and the protocol falls back to sys.stdout.
_PROTOCOL: Any = None


def _protocol_stream() -> Any:
    return _PROTOCOL if _PROTOCOL is not None else sys.stdout


def _shield_protocol_stream() -> None:
    """Move the JSON protocol off descriptor 1.

    The parent reads protocol responses from the worker's descriptor 1 with
    readline(). redirect_stdout() rebinds only Python's sys.stdout -- a child
    process a Sage internal forks, or a C library writing to the descriptor
    directly, still lands mid-JSON-line and desyncs every request after it.
    So the pipe is duplicated to a private descriptor for the protocol, and
    descriptor 1 is pointed at stderr: raw writes surface as logged worker
    noise instead of framing corruption. Called from the entrypoint only --
    in-process tests must not have their own descriptors rewired.
    """
    global _PROTOCOL
    sys.stdout.flush()
    _PROTOCOL = os.fdopen(os.dup(1), "w", buffering=1, encoding="utf-8")
    os.dup2(2, 1)


def _execute(
    code: str,
    want_latex: bool,
    capture_stdout: bool,
    namespace: dict[str, Any],
    trusted: bool = False,
    stream_id: str | None = None,
) -> dict[str, Any]:
    if _STARTUP_ERROR:
        return {
            "ok": False,
            "stdout": "",
            "error": {
                "type": "StartupError",
                "message": _STARTUP_ERROR,
                "traceback": "",
            },
        }
    # stream_id turns the buffer into one that also emits line events.
    if capture_stdout and stream_id is not None:
        stdout_buffer: io.StringIO | None = _StreamingStdout(stream_id, _protocol_stream())
    elif capture_stdout:
        stdout_buffer = io.StringIO()
    else:
        stdout_buffer = None
    start = time.perf_counter()

    try:
        compiled = _split_code(
            code, trusted=trusted, session_names=_CALLER_BOUND_NAMES,
            withheld=_WITHHELD_NAMES,
        )
    except Exception as exc:
        return _error_payload(exc, stdout_buffer.getvalue() if stdout_buffer else "")

    before_trusted = frozenset(namespace) if trusted else frozenset()
    before_execution = set(namespace) if compiled.injects and not trusted else set()
    # Declare the symbol-shaped free names the validator approved, so `w + 1`
    # runs instead of raising NameError. Session state is preserved: a name the
    # caller already assigned is not overwritten.
    _declare_symbols(namespace, getattr(compiled, "auto_symbols", frozenset()))
    try:
        with contextlib.redirect_stdout(stdout_buffer or io.StringIO()):
            exec(compile(compiled.prefix, "<sagecell>", "exec"), namespace)
            if isinstance(stdout_buffer, _StreamingStdout):
                stdout_buffer.flush()   # emit a trailing line with no newline
            result_obj = None
            result_type = "statement"
            if compiled.is_expr and compiled.tail is not None:
                result_obj = eval(compile(compiled.tail, "<sagecell>", "eval"), namespace)
                result_type = "expression"
        if compiled.injects and not trusted:
            # Only for a snippet that *asked* for an injection, and only for
            # names that were not there before it ran. A namespace diff is not
            # trusted in general -- `lazy_import('os', 'system')` gains a
            # binding without reading a forbidden name, which is why
            # _CALLER_BOUND_NAMES is built from the AST -- so this is gated on
            # the caller having written the call, and `lazy_import` itself is
            # scrubbed from the namespace and refused by name.
            _CALLER_BOUND_NAMES.update(set(namespace) - before_execution)
        stdout_value = stdout_buffer.getvalue() if stdout_buffer else ""
        if result_obj is not None and not trusted:
            # `_` is the previous result, as in every REPL Sage ships. It was
            # refused 694 times across SageMath's own doctests -- `_.parent()`,
            # `_.simplify()` -- and never for a security reason: this worker
            # simply never bound it. A session that keeps variables between
            # calls can keep this one. Caller code only: a tool's generated
            # snippet must not move it, or `_` would mean whichever helper the
            # model happened to call in between.
            namespace["_"] = result_obj
            _CALLER_BOUND_NAMES.add("_")
        result_repr = None if result_obj is None else _format_result(result_obj)
        latex_repr = _latex(result_obj) if result_obj is not None and want_latex else None
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        return {
            "ok": True,
            "result_type": result_type,
            "result": result_repr,
            "latex": latex_repr,
            "stdout": stdout_value,
            "elapsed_ms": elapsed_ms,
        }
    except KeyboardInterrupt:
        # SIGINT from the parent means "abandon this computation", not "die".
        # KeyboardInterrupt is a BaseException, so the handler below does not
        # catch it; without this the worker would exit and take the namespace
        # with it, which is exactly what interrupting is meant to avoid.
        return {
            "ok": False,
            "stdout": stdout_buffer.getvalue() if stdout_buffer else "",
            "error": {
                "type": "Interrupted",
                "message": "Computation interrupted; session state is preserved.",
                "traceback": "",
            },
        }
    except Exception as exc:
        return _error_payload(exc, stdout_buffer.getvalue() if stdout_buffer else "")


    finally:
        if trusted:
            # The prelude runs `from sage.all import *` in this namespace and
            # runs *first*, so a tool call that raises has already repopulated
            # it by the time it fails. Sealing only on the success path left
            # every failing call -- a singular matrix, a bad bound, an
            # interrupted computation -- holding the door open, and that was
            # remote code execution. KeyboardInterrupt is a BaseException, so
            # this has to be `finally` rather than a cleanup in `except`.
            # Two sources, because neither is complete on its own: the AST
            # catches an overwrite of a name the caller already had, and the
            # key diff catches what `from sage.all import *` brings in, which
            # no AST walk enumerates.
            _reseal_namespace(
                namespace,
                (frozenset(namespace) - before_trusted) | compiled.bound_here,
            )

def _protocol_error(kind: str, message: str, msg_id: object = None) -> dict[str, Any]:
    """The response for a frame that cannot be served."""
    return {"ok": False, "id": msg_id, "error": {"type": kind, "message": message}}


def _read_frame(line: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Parse one protocol line into `(frame, error)`.

    Exactly one of the two is set, or both are None for a blank line that the
    loop skips. Pure, so the whole malformed-input surface can be fuzzed
    without a subprocess (`fuzz/fuzz_protocol.py`).

    It exists because the checks it now performs were missing. The worker
    holds the session's entire namespace, so an uncaught exception here does
    not drop one request -- it discards every variable the caller has built
    and leaves the parent with a closed pipe and no reason. Two shapes did
    exactly that: any well-formed JSON that is not an object (`[].get` is an
    AttributeError), and an execute frame with no `code` (a KeyError). Frames
    come from `session.py`, so neither was reachable from a caller; both were
    one bug in that file away from a dead session (REVIEW_ACTIONS 91).
    """
    line = line.strip()
    if not line:
        return None, None
    try:
        message = json.loads(line)
    except (json.JSONDecodeError, RecursionError):
        return None, _protocol_error("JSONDecodeError", "Invalid JSON payload")
    if not isinstance(message, dict):
        return None, _protocol_error(
            "InvalidFrame", f"Expected a JSON object, got {type(message).__name__}"
        )
    if message.get("type") == "execute" and "code" not in message:
        return None, _protocol_error(
            "InvalidFrame", "An execute frame needs 'code'", message.get("id")
        )
    return message, None


def _main() -> int:
    namespace = _build_namespace()
    while True:
        try:
            raw = sys.stdin.readline()
        except KeyboardInterrupt:
            # An interrupt that lands while the worker is idle has nothing to
            # cancel. Swallow it and keep serving rather than exiting.
            continue
        if not raw:
            break
        message, error = _read_frame(raw)
        if error is not None:
            print(json.dumps(error), file=_protocol_stream(), flush=True)
            continue
        if message is None:
            continue
        msg_type = message.get("type")
        msg_id = message.get("id")

        if msg_type == "execute":
            response = _execute(
                code=message["code"],
                want_latex=bool(message.get("want_latex", False)),
                capture_stdout=bool(message.get("capture_stdout", True)),
                namespace=namespace,
                trusted=bool(message.get("trusted", False)),
                stream_id=msg_id if message.get("stream") else None,
            )
            response["id"] = msg_id
            print(json.dumps(response), file=_protocol_stream(), flush=True)
        elif msg_type == "reset":
            namespace = _build_namespace()
            print(json.dumps({"ok": True, "id": msg_id}), file=_protocol_stream(), flush=True)
        elif msg_type == "shutdown":
            print(json.dumps({"ok": True, "id": msg_id}), file=_protocol_stream(), flush=True)
            return 0
        else:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "id": msg_id,
                        "error": {
                            "type": "ValueError",
                            "message": f"Unsupported message type: {msg_type}",
                        },
                    }
                ),
                file=_protocol_stream(),
                flush=True,
            )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    _shield_protocol_stream()
    sys.exit(_main())
