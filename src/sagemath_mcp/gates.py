"""The gates between a caller's string and the Sage code a tool generates.

Every helper tool interpolates caller parameters into a Sage template, and
generated code runs under ``trusted_policy()``, which re-permits ``sage_eval``
because the templates are built on it. So any caller string that reaches a
template without passing through ``encode_literal``, ``validated_expression``
or ``validated_identifier`` is arbitrary code execution (review item 18). A
structural test in tests/test_generated_code_lint.py enforces it.
"""

from __future__ import annotations

import ast
import functools
import io
import json
import re
import tokenize
from collections.abc import Iterable
from dataclasses import replace

from fastmcp.exceptions import ToolError

from .security import (
    SECURITY_POLICY,
    SecurityViolation,
    validate_module,
)


def _normalize_source(value):
    """Collapse whitespace in strings destined for sage_eval.

    Every tool here evaluates its input as a *single* expression, so an
    embedded newline is a syntax error ("2 +\\n2" fails). Clients are language
    models, which wrap and indent freely, so runs of whitespace are folded to a
    single space. evaluate_sage does not pass through here: it takes real
    multi-line code and keeps its newlines.
    """
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value).strip()
    if isinstance(value, (list, tuple)):
        return [_normalize_source(item) for item in value]
    return value


# A single "=" that is not part of ==, <=, >= or !=. Sage accepts it as an
# equation; Python does not accept it as an expression at all.
EQUALS_NOT_COMPARISON = re.compile(r"(?<![=<>!])=(?!=)")


# Tool parameters are validated with the allowlist OFF and every other rule ON.
#
# A fragment is not arbitrary code: it is interpolated into a template where the
# names resolve in a specific context -- `HammingCode(GF(2), 3)` inside `codes.`,
# `PetersenGraph` inside `graphs.`, `y` among the symbols the prelude declares.
# Judging those against the caller allowlist would refuse the tools' own
# documented inputs. Imports, forbidden names, the attribute rules and the
# persistence prefixes all still apply.
#
# `eval`, `vars`, `locals` and `input` are re-added to the forbidden call names
# here, and this is not symmetry: they were removed from the caller policy on
# the argument that they "reach nothing" -- absent from the restricted builtins,
# the worker namespace and the allowlist. NONE of that holds on this path. The
# allowlist is off, and the fragment is not run in the worker namespace at all:
# it is handed to sage_eval, which resolves against sage.all's own globals, where
# the real builtins are reachable. `eval` of `'__import__("os").system("id")'` ran a
# shell through calculate_expression exactly this way, and `locals()["__builtins
# __"]["eval"]` is the same reach without naming eval. The scrub cannot cover
# them -- they are builtins, not sage.all names -- so the gate must. See item 54.
_FRAGMENT_POLICY = replace(
    SECURITY_POLICY,
    enforce_name_allowlist=False,
    forbidden_call_names=(
        *SECURITY_POLICY.forbidden_call_names,
        "eval",
        "vars",
        "locals",
        "input",
    ),
)


def _refuse_scrubbed_names(parsed: ast.Expression, source: str) -> None:
    """Refuse a fragment that names something the worker's scrub removes.

    Kept here rather than in `validate_module`, and that is the whole design
    decision. Trusted templates and caller fragments both run under a policy
    with the allowlist switched off -- the template needs to read its own
    `_locals`, the fragment needs to name what the template puts in scope -- so
    a rule written inside the validator cannot tell them apart, and one written
    outside the allowlist check refused the templates' own variables. The
    fragment is the only one of the two that a caller wrote, so the rule belongs
    at the fragment gate.
    """
    withheld = _names_the_scrub_removes()
    for node in ast.walk(parsed):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            if node.id in withheld:
                raise ToolError(
                    f"Rejected by the security policy: '{node.id}' is not a name "
                    f"this server offers"
                )
            # A backstop for the leaf-as-attribute shape this Name walk misses.
            # `sage.all.unpickle_global` reaches a scrubbed name as a `.attr`,
            # invisible above, and rode past the gate on the strength of the
            # sage.all scrub alone. No tool parameter traverses the `sage`
            # module -- callers write `matrix`, `integrate`, `codes.HammingCode`
            # directly -- so refusing a `sage`-rooted chain closes the shape
            # independently of what the scrub happens to contain. Rooted on
            # `sage` rather than on the leaf name, because `load` and `save` are
            # in the scrub set and are also ordinary method names.
            if node.id == "sage":
                raise ToolError(
                    "Rejected by the security policy: reaching into the 'sage' "
                    "module is not permitted here; name the function directly"
                )


@functools.cache
def _names_the_scrub_removes() -> frozenset[str]:
    """The names a fragment may not use, because nothing else stops it.

    Tool parameters are validated without the allowlist -- they legitimately
    name what a template puts in scope, `codes.HammingCode` inside `codes.` --
    so the denylist is what guards them. Some names were never on the denylist
    because the *namespace scrub* removed them instead, and the scrub cannot
    reach a fragment: `sage_eval` evaluates "in namespace of sage.all plus
    locals", never in the worker's namespace. That gap ran a shell:

        calculate_expression("unpickle_global('os','system')('id > /tmp/x')")

    So the fragment policy withholds exactly what the scrub removes -- no more,
    because refusing the whole allowlist would cost the tools mathematics they
    are meant to do.
    """
    from ._sage_worker import _DANGEROUS_BARE_NAMES, _DANGEROUS_SAGE_NAME_LIST

    return frozenset(_DANGEROUS_SAGE_NAME_LIST) | frozenset(_DANGEROUS_BARE_NAMES)


def _screen_unparseable_fragment(fragment: str) -> None:
    """Reject forbidden names in a fragment that would not parse.

    Full AST validation needs a parse tree. When there is none, screen the token
    stream instead: a name is a name whatever surrounds it, and this is the last
    gate before the fragment is interpolated into trusted, sage_eval'd code.
    """
    # This screen mirrors, token by token, the two kinds of check `validate_
    # module` (security.py) makes on the parseable path -- and the split is
    # load-bearing. The AST path refuses some names in *any* position (on both
    # `ast.Name` and `ast.Attribute`) and others *only* as an attribute (on
    # `node.attr`). A token screen has no tree, so it distinguishes the two by
    # the one signal it does have: an attribute NAME is preceded by a `.`.
    #
    # All-position: call names (`sage_eval`, `open`, ...) and attribute parents
    # (`os`, `pari`, ...) are dangerous read bare or dotted, so they are refused
    # wherever they appear.
    always_forbidden = (
        set(_FRAGMENT_POLICY.forbidden_call_names)
        | set(_FRAGMENT_POLICY.forbidden_attribute_parents)
        # And the roots whose tree may not be traversed at all (item 81). The
        # AST path refuses `sage.misc.latex.png(...)`; without this, the same
        # chain wrapped in Sage-only syntax -- `[sage.misc.latex.png(1,'x')..1]`
        # -- did not parse, fell through to this screen, and was accepted by
        # both gates. It then reached `sage_eval` under the trusted policy,
        # where `[X..1]` preparses to `ellipsis_range(X, ...)` and calls X.
        # The screen mirrors the AST path; this is the third set it has to
        # mirror (item 83).
        | set(_FRAGMENT_POLICY.forbidden_attribute_roots)
    )
    # Attribute-position only: these guard *methods* -- `has_file`, `save_image`,
    # `write_to_eps`, `.gp()`, `.eval` -- reached through an object. The AST
    # path fires them on `node.attr` alone; as a bare name each is either
    # harmless (a `NameError` at runtime -- there is no global `has_file`) or
    # already covered above (`save`/`dumps` are call names). Applying them to
    # every NAME instead rejected ordinary variables a caller may hold in a
    # Sage-only-syntax fragment -- `save_point`, `dump_total`, `export_matrix` --
    # which the parseable path accepts, so the gate must match it here.
    attribute_forbidden = (
        set(_FRAGMENT_POLICY.forbidden_attribute_names)
        | set(_FRAGMENT_POLICY.forbidden_attribute_only_names)
    )
    attribute_prefixes = _FRAGMENT_POLICY.forbidden_attribute_prefixes
    # The names the worker's scrub removes, which the parseable path refuses via
    # `_refuse_scrubbed_names`. Without them here, wrapping a scrubbed name in
    # Sage-only syntax the Python parser rejects routed it through this screen
    # instead and slipped past -- a narrower gate for exactly the inputs that
    # avoid the wider one. A caller may reclaim one as their own generator target
    # (`R.<a,b> = QQ[]`), so `bound` below overrides this set: a scrubbed name is
    # unreachable at runtime (stripped from the namespace), so rescuing it is
    # safe -- a live method like `has_file` is refused above and is never here.
    scrubbed = _names_the_scrub_removes()
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(fragment).readline))
    except (tokenize.TokenError, IndentationError) as exc:
        raise ToolError(
            f"Could not read {fragment!r} as an expression: {exc}"
        ) from exc

    # A name declared as a generator target -- `R.<a, b> = QQ[]`, the syntax
    # that put us on this unparseable path in the first place -- is the caller
    # binding their own, exactly as `_bound_names` treats an assignment in the
    # AST path. So `R` is theirs to name even though the reals `R` is scrubbed,
    # while `gp` and `unpickle_global`, which no one declares as a ring, stay
    # refused. Detected as NAME `.` `<`.
    bound: set[str] = set()
    for first, dot, angle in zip(tokens, tokens[1:], tokens[2:], strict=False):
        if (
            first.type == tokenize.NAME
            and dot.type == tokenize.OP and dot.string == "."
            and angle.type == tokenize.OP and angle.string == "<"
        ):
            bound.add(first.string)

    for index, token in enumerate(tokens):
        if token.type != tokenize.NAME:
            continue
        name = token.string
        # tokenize emits no whitespace tokens, so the previous token is the
        # syntactic predecessor: a `.` before this NAME makes it an attribute.
        preceded_by_dot = (
            index > 0
            and tokens[index - 1].type == tokenize.OP
            and tokens[index - 1].string == "."
        )
        rejected = (
            name in always_forbidden
            or (name.startswith("__") and name.endswith("__"))
            # A generator target rescues a scrubbed name, nothing else.
            or (name in scrubbed and name not in bound)
            or (
                preceded_by_dot
                and (name in attribute_forbidden or name.startswith(attribute_prefixes))
            )
        )
        if rejected:
            raise ToolError(
                f"Rejected by the security policy: reference to '{name}' is blocked"
            )


def _reject_statement_smuggling(text: str) -> None:
    """Refuse a fragment that carries more than the single expression it claims.

    Two shapes turned one interpolation slot into several statements once the
    fragment reached the template:

    * A comment. `ast.parse` and the token screen both discard everything after
      `#`, so `1 # <anything> = __import__("os").system("id")` validated as the
      literal `1` -- and then `solve_equation`'s runtime `_eq_str.split('=')`
      handed the hidden right-hand side to sage_eval as code (item 55).
    * A `;`. `group_operation` interpolates a fragment at statement position, so
      `SymmetricGroup(5); _z = plot(sin(x)).save_image('/path')` became two real
      statements, the second writing a caller-chosen file (item 56).

    A newline is not refused here -- it is folded to a space by _normalize_source
    below, which is what lets a wrapped single expression through -- and folding
    plus this check leaves no way to reach a second statement: juxtaposition
    (`A B`) is a syntax error the template rejects, and `;` is gone.
    """
    try:
        tokens = tokenize.generate_tokens(io.StringIO(text).readline)
        for token in tokens:
            if token.type == tokenize.COMMENT:
                raise ToolError(
                    "Rejected by the security policy: a comment is not permitted "
                    "in an expression"
                )
            if token.type == tokenize.OP and token.string == ";":
                raise ToolError(
                    "Rejected by the security policy: ';' is not permitted in an "
                    "expression"
                )
    except (tokenize.TokenError, IndentationError):
        # Not tokenizable as-is (unbalanced brackets in Sage-only syntax, say):
        # the parse/screen path below refuses or accepts it on its own terms.
        return


def validated_expression(text: str) -> str:
    """Check a caller-supplied fragment before it is embedded in generated code.

    The helper tools wrap caller input in sage_eval("<text>"). The AST validator
    sees only a string constant there, so until this existed the entire
    specialised tool surface evaluated caller code unchecked:
    calculate_expression("__import__('os').getuid()") returned the container uid.

    Validating the fragment as an expression in its own right closes that, and
    is what makes the trusted worker path in evaluate_structured safe.

    The value returned is the whitespace-folded fragment, not the caller's raw
    text: `group_operation` and friends interpolate it verbatim, so a fragment
    that reaches here with an embedded newline must leave here without one, or
    the newline becomes a statement break in the template (item 56). Folding
    also validates exactly what runs -- `sage_eval` sees the folded string too.
    """
    if not isinstance(text, str):
        return text
    folded = _normalize_source(text)
    stripped = folded.strip()
    if not stripped:
        return text
    _reject_statement_smuggling(stripped)
    try:
        parsed = ast.parse(stripped, mode="eval")
    except SyntaxError:
        # Returning the fragment unvalidated here made "unparseable" a way to
        # skip validation entirely, since it is then interpolated into sage_eval
        # under the trusted policy. But rejecting outright is wrong too: the
        # documented equation form "x^2 - 1 = 0" is deliberately not a Python
        # expression. So try the Sage spelling first, and screen whatever is
        # left at token level rather than waving it through.
        equation = EQUALS_NOT_COMPARISON.sub("==", stripped)
        if equation != stripped:
            try:
                parsed = ast.parse(equation, mode="eval")
            except SyntaxError:
                _screen_unparseable_fragment(stripped)
                return folded
        else:
            _screen_unparseable_fragment(stripped)
            return folded
    try:
        _refuse_scrubbed_names(parsed, stripped)
        validate_module(
            ast.Module(body=[ast.Expr(value=parsed.body)], type_ignores=[]),
            code=stripped,
            policy=_FRAGMENT_POLICY,
        )
    except SecurityViolation as exc:
        raise ToolError(f"Rejected by the security policy: {exc}") from exc
    return folded


def encode_literal(value: str | Iterable) -> str:
    if isinstance(value, str):
        validated_expression(value)
    elif isinstance(value, (list, tuple)):
        for item in value:
            if isinstance(item, str):
                validated_expression(item)
    return json.dumps(_normalize_source(value))


# Identifiers in a bound or point, e.g. the "a" in an integral up to a.
_IDENTIFIER_RE = re.compile(r"\b([A-Za-z_]\w*)\b")


# A bare index-style name such as n, k, N or x1.
_SHORT_NAME_RE = re.compile(r"^[A-Za-z]\d*$")


# Single-letter names that are constants in Sage, not free variables.
_PROTECTED_CONSTANTS = frozenset({"e", "i", "I"})


# A named graph from Sage's catalogue: "PetersenGraph", "PetersenGraph()" or a
# parameterised one such as "CompleteGraph(4)". No re.DOTALL: `.` must not span
# a newline, so a smuggled second statement cannot ride inside the call group
# (item 56). `validated_expression` folds newlines out before this runs, so
# this is defence in depth rather than the only guard.
NAMED_GRAPH_RE = re.compile(r"^(?P<name>[A-Za-z_]\w*)\s*(?P<call>\(.*\))?$")


def declare_free_symbols(*sources: str | None) -> str:
    """Code that declares any unknown identifier in *sources* as a symbol.

    A bound may legitimately be symbolic -- integrating to "a", or summing to
    "n" -- but the prelude only declares x, y, z, t plus the tool's own
    variable, so anything else raised "name 'a' is not defined".

    Names Sage already defines are left alone. Declaring them would shadow the
    real object and break the very inputs that do work today: var('oo') would
    turn infinity into an ordinary symbol, and the same applies to pi, e, I and
    every function name such as sin or sqrt.
    """
    names: set[str] = set()
    for source in sources:
        if source:
            names.update(_IDENTIFIER_RE.findall(source))
    if not names:
        return ""
    # Short names win over anything Sage happens to define, because Sage's
    # namespace collides with ordinary index names: "n" and "N" are
    # numerical_approx, so summing to n resolved the bound to a function rather
    # than a symbol. The true constants are the exception and must never be
    # shadowed -- e is Euler's number, and i and I are the imaginary unit.
    forced = sorted(
        name for name in names if _SHORT_NAME_RE.match(name) and name not in _PROTECTED_CONSTANTS
    )
    # Longer names keep the conservative check, so sin, sqrt, pi, oo, gamma and
    # every other spelled-out Sage object continues to mean what it says.
    conditional = sorted(names.difference(forced))

    # Emitted as a single physical line. These snippets are interpolated into
    # templates that are then passed through textwrap.dedent, and a multi-line
    # block would arrive unindented, destroying the common prefix dedent relies
    # on ("unexpected indent" at import time).
    parts = ["import sage.all as _sage_ns"]
    if forced:
        parts.append(f"_locals.update({{_n: var(_n) for _n in {forced!r} if _n not in _locals}})")
    if conditional:
        parts.append(
            f"_locals.update({{_n: var(_n) for _n in {conditional!r} "
            "if _n not in _locals and not hasattr(_sage_ns, _n)})"
        )
    return "; ".join(parts)


# A plain Python identifier. Variable names are interpolated into generated code
# inside single quotes, so anything else can close the literal and append code.
_PLAIN_IDENTIFIER_RE = re.compile(r"^[A-Za-z_]\w*$")


def validated_identifier(name: str, parameter: str) -> str:
    """Reject anything that is not a bare identifier.

    Cheaper and stricter than parsing: a variable name has exactly one legal
    shape, and this closes the quoted-interpolation route in one place.
    """
    if not isinstance(name, str) or not _PLAIN_IDENTIFIER_RE.match(name.strip()):
        raise ToolError(
            f"Rejected by the security policy: '{parameter}' must be a plain "
            f"identifier, got {name!r}"
        )
    return name.strip()
