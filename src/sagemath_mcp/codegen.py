"""Building and validating the Sage code the tools generate.

Every helper tool works the same way: take caller parameters, build a Sage
snippet around them, and run it. This module is that machinery -- the prelude,
the literal encoding, the validation gates and the numeric guards -- kept apart
from the tool definitions so it can be read and tested on its own.

The gates matter more than they look. Generated code runs under
``trusted_policy()``, which re-permits ``sage_eval`` because the templates are
built on it, so any caller string interpolated into a template without passing
through ``_encode_literal``, ``_validated_expression`` or
``_validated_identifier`` is arbitrary code execution (review item 18).
"""

from __future__ import annotations

import ast
import functools
import io
import json
import re
import textwrap
import tokenize
from collections.abc import Iterable
from dataclasses import replace

from fastmcp.exceptions import ToolError

from .allowlist import ALLOWED_CALLER_NAMES
from .security import (
    _GREEK_NAMES,
    _SYMBOL_SHAPE,
    SECURITY_POLICY,
    SecurityViolation,
    validate_module,
)
from .symbols import PREDEFINED_SYMBOLS


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
_EQUALS_NOT_COMPARISON = re.compile(r"(?<![=<>!])=(?!=)")


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
# the real builtins are reachable. `eval('__import__("os").system("id")')` ran a
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
    )
    # Attribute-position only: these guard *methods* -- `has_file`, `save_image`,
    # `write_to_eps`, `.gp()`, `.eval()` -- reached through an object. The AST
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
      `#`, so `1 # eval("x") = __import__("os").system("id")` validated as the
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


def _validated_expression(text: str) -> str:
    """Check a caller-supplied fragment before it is embedded in generated code.

    The helper tools wrap caller input in sage_eval("<text>"). The AST validator
    sees only a string constant there, so until this existed the entire
    specialised tool surface evaluated caller code unchecked:
    calculate_expression("__import__('os').getuid()") returned the container uid.

    Validating the fragment as an expression in its own right closes that, and
    is what makes the trusted worker path in _evaluate_structured safe.

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
        equation = _EQUALS_NOT_COMPARISON.sub("==", stripped)
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


def _encode_literal(value: str | Iterable) -> str:
    if isinstance(value, str):
        _validated_expression(value)
    elif isinstance(value, (list, tuple)):
        for item in value:
            if isinstance(item, str):
                _validated_expression(item)
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
# (item 56). `_validated_expression` folds newlines out before this runs, so
# this is defence in depth rather than the only guard.
_NAMED_GRAPH_RE = re.compile(r"^(?P<name>[A-Za-z_]\w*)\s*(?P<call>\(.*\))?$")


def _declare_free_symbols(*sources: str | None) -> str:
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


# Beyond 2^53 a JSON number is no longer exactly representable as an IEEE
# double, which is what JavaScript-based MCP clients parse numbers into.
# JavaScript's Number.MAX_SAFE_INTEGER. 2^53 itself is NOT safe as an inbound
# value: 2^53 + 1 rounds to exactly 2^53, so a client that meant either sends the
# same digits and the server cannot tell them apart. The boundary has to be the
# largest integer whose neighbours are also representable.
_EXACT_JSON_INT_LIMIT = 2**53 - 1


def _exact_int(value: int | str | float, name: str) -> int:
    """Coerce a tool argument to an exact integer, refusing lossy input.

    A float here means the value already went through a double. 10^30 arrives
    as 1000000000000000019884624838656, and next_prime() on that returns a
    perfectly plausible wrong answer -- the failure mode is a wrong number, not
    an error, which is why this rejects rather than rounds.
    """
    if isinstance(value, bool):  # bool is an int subclass; never meant here
        raise ToolError(f"'{name}' must be an integer, got a boolean")
    if isinstance(value, str):
        text = value.strip().replace("_", "")
        try:
            return int(text, 10)
        except ValueError:
            raise ToolError(f"'{name}' is not a decimal integer: {value!r}") from None
    if isinstance(value, float):
        if not value.is_integer():
            raise ToolError(f"'{name}' must be a whole number, got {value!r}")
        return _reject_if_inexact(int(value), name)
    # An int is not automatically safe. A JavaScript client rounds the value
    # BEFORE serialising and then emits the rounded digits as a JSON integer, so
    # the float branch above is never reached: 10^30 arrives as the int
    # 1000000000000000019884624838656 and looks perfectly ordinary.
    return _reject_if_inexact(int(value), name)


def _reject_if_inexact(value: int, name: str) -> int:
    """Refuse any JSON-borne number too large to have survived a double."""
    if abs(value) > _EXACT_JSON_INT_LIMIT:
        raise ToolError(
            f"'{name}' is larger than 2^53, where JSON numbers stop being exact: "
            "a JavaScript-based client will already have rounded it before sending. "
            f'Pass it as a decimal string instead, for example "{value}".'
        )
    return value


def _exact_matrix_entries(rows, name: str):
    """Return *rows* with integer entries kept exact.

    The schemas took `float`, so an exact integer was rounded to a double before
    Sage ever saw it: matrix(SR, [[9007199254740993]]) became
    matrix(SR, [[9007199254740992.0]]) and the determinant was quietly wrong.
    Integers and decimal strings now stay integers; genuine floats stay floats.
    """
    converted = []
    for row in rows:
        if not isinstance(row, (list, tuple)):
            raise ToolError(f"'{name}' must be a list of rows")
        out = []
        for entry in row:
            if isinstance(entry, bool):
                raise ToolError(f"'{name}' entries must be numbers, got a boolean")
            if isinstance(entry, float):
                out.append(entry)          # a float was asked for; keep it
            else:
                out.append(_exact_int(entry, name))
        converted.append(out)
    return converted


def _check_matrix(rows: list[list[float]], name: str) -> None:
    """Reject shapes Sage would only complain about obscurely, or not at all.

    An empty matrix is the dangerous one: Sage treats [] as the 0x0 matrix and
    reports its determinant as 1.0, which looks like a real answer.
    """
    if not rows or not all(isinstance(row, (list, tuple)) for row in rows):
        raise ToolError(f"'{name}' must be a non-empty list of rows")
    if not rows[0]:
        raise ToolError(f"'{name}' rows must be non-empty")
    width = len(rows[0])
    if any(len(row) != width for row in rows):
        widths = sorted({len(row) for row in rows})
        raise ToolError(
            f"'{name}' rows must all have the same length; found lengths {widths}"
        )


def _normal_parameters(parameters: list[float]) -> tuple[float, float]:
    """Return (mu, sigma) for the documented [mu, sigma] parameter list."""
    if len(parameters) >= 2:
        return float(parameters[0]), float(parameters[1])
    if len(parameters) == 1:
        # A single parameter is the standard deviation, matching how the
        # previous implementation treated a one-element list.
        return 0.0, float(parameters[0])
    return 0.0, 1.0


def _distribution_mean(distribution: str, parameters: list[float]) -> float:
    """Analytic mean for the supported continuous distributions."""
    p = [float(v) for v in parameters]
    if distribution == "normal":
        return _normal_parameters(p)[0]
    if distribution == "exponential":
        # Sage parameterises RealDistribution('exponential', mu) by the mean.
        return p[0] if p else 1.0
    if distribution == "uniform":
        if len(p) < 2:
            raise ToolError("uniform requires parameters [a, b]")
        return (p[0] + p[1]) / 2
    if distribution == "chi_squared":
        return p[0] if p else 1.0
    if distribution == "student_t":
        nu = p[0] if p else 1.0
        if nu <= 1:
            raise ToolError("student_t mean is undefined for degrees of freedom <= 1")
        return 0.0
    if distribution == "beta":
        if len(p) < 2:
            raise ToolError("beta requires parameters [a, b]")
        return p[0] / (p[0] + p[1])
    if distribution == "gamma":
        if len(p) < 2:
            raise ToolError("gamma requires parameters [shape, scale]")
        return p[0] * p[1]
    raise ToolError(f"No analytic mean available for distribution '{distribution}'")


def _distribution_variance(distribution: str, parameters: list[float]) -> float:
    """Analytic variance for the supported continuous distributions."""
    p = [float(v) for v in parameters]
    if distribution == "normal":
        return _normal_parameters(p)[1] ** 2
    if distribution == "exponential":
        mu = p[0] if p else 1.0
        return mu**2
    if distribution == "uniform":
        if len(p) < 2:
            raise ToolError("uniform requires parameters [a, b]")
        return (p[1] - p[0]) ** 2 / 12
    if distribution == "chi_squared":
        return 2 * (p[0] if p else 1.0)
    if distribution == "student_t":
        nu = p[0] if p else 1.0
        if nu <= 2:
            raise ToolError("student_t variance is undefined for degrees of freedom <= 2")
        return nu / (nu - 2)
    if distribution == "beta":
        if len(p) < 2:
            raise ToolError("beta requires parameters [a, b]")
        a, b = p[0], p[1]
        return a * b / ((a + b) ** 2 * (a + b + 1))
    if distribution == "gamma":
        if len(p) < 2:
            raise ToolError("gamma requires parameters [shape, scale]")
        return p[0] * p[1] ** 2
    raise ToolError(f"No analytic variance available for distribution '{distribution}'")


def _exactify_large_ints(value):
    """Return *value* with JSON-unsafe integers rendered as decimal strings.

    The input guard was only half the problem. Results travel back as JSON
    numbers, and a JavaScript-based MCP client parses those as IEEE doubles:
    bell(30) = 846749014511809332450147 reached the Claude CLI as
    846749014511809388871680 and was shown as the answer. Nothing errored; the
    number was simply wrong, which is the worst way for this to fail.

    Above 2^53 the exact value is therefore sent as a string, mirroring what the
    input side already demands for the same reason. Smaller integers keep their
    type, so ordinary results are unchanged.
    """
    if isinstance(value, bool):
        return value                      # bool is an int subclass
    if isinstance(value, int):
        return str(value) if abs(value) > _EXACT_JSON_INT_LIMIT else value
    if isinstance(value, dict):
        return {key: _exactify_large_ints(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_exactify_large_ints(item) for item in value]
    return value


async def _evaluate_structured(
    session, code: str, timeout_seconds: float | None = None
) -> object:
    """Run a snippet this server generated.

    trusted=True permits sage_eval, which every helper template is built on.
    That is only safe because the caller-supplied fragments interpolated into
    the template are validated separately by _validated_expression before they
    get here -- otherwise the helpers would be an unguarded path straight past
    the AST policy, which is exactly what they were.
    """
    try:
        worker_result = await session.evaluate(
            code,
            want_latex=False,
            capture_stdout=False,
            timeout_seconds=timeout_seconds,
            trusted=True,
        )
    except TimeoutError as exc:
        # Same translation as evaluate_sage: every tool should report a timeout
        # as a tool error with the deadline in it, not a bare TimeoutError.
        raise ToolError(str(exc)) from exc
    if worker_result.result is None:
        return None
    try:
        parsed = ast.literal_eval(worker_result.result)
    except Exception:
        return worker_result.result
    return _exactify_large_ints(parsed)


# A plain Python identifier. Variable names are interpolated into generated code
# inside single quotes, so anything else can close the literal and append code.
_PLAIN_IDENTIFIER_RE = re.compile(r"^[A-Za-z_]\w*$")


def _validated_identifier(name: str, parameter: str) -> str:
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


# Symbol-shaped names SageMath already defines, which must never be turned into
# a fresh variable: `e` is Euler's number, `I` the imaginary unit, and `gamma`,
# `zeta`, `beta`, `psi`, `sigma`, `eta` and `tau` are functions. Auto-declaring
# any of them would shadow real mathematics with an empty symbol.
# The Greek alphabet as single characters, which is how a physicist writes it.
# `_GREEK_NAMES` covers the spelled-out forms (`alpha`, `omega`); these are the
# letters themselves, and `str.isalpha()` calls them letters while
# `_SYMBOL_SHAPE` -- deliberately `^[a-zA-Z]_?\d?$` -- does not.
_GREEK_LETTERS = frozenset(
    "\u03b1\u03b2\u03b3\u03b4\u03b5\u03b6\u03b7\u03b8\u03b9\u03ba\u03bb\u03bc"
    "\u03bd\u03be\u03bf\u03c0\u03c1\u03c2\u03c3\u03c4\u03c5\u03c6\u03c7\u03c8"
    "\u03c9"
    "\u0391\u0392\u0393\u0394\u0395\u0396\u0397\u0398\u0399\u039a\u039b\u039c"
    "\u039d\u039e\u039f\u03a0\u03a1\u03a3\u03a4\u03a5\u03a6\u03a7\u03a8\u03a9"
    "\u03d1\u03d5\u03d6\u03f1\u03f5"
)

# Symbol-shaped names SageMath already defines, which must never be turned into
# a fresh variable: `e` is Euler's number, `I` the imaginary unit, and `gamma`,
# `zeta`, `beta`, `psi`, `sigma`, `eta` and `tau` are functions. So are five of
# the Greek letters -- capital gamma, zeta, pi, sigma and psi -- which is why
# the letters are
# filtered through the allowlist rather than trusted wholesale. Declaring any of
# them would shadow real mathematics with an empty symbol.
_SYMBOL_SHAPED_ALREADY_OFFERED = frozenset(
    name for name in ALLOWED_CALLER_NAMES
    if _SYMBOL_SHAPE.match(name) or name in _GREEK_NAMES or name in _GREEK_LETTERS
)
_DECLARABLE_GREEK_LETTERS = _GREEK_LETTERS - set(ALLOWED_CALLER_NAMES)


def _sage_prelude(extra_locals: Iterable[str] | None = None) -> str:
    names = list(PREDEFINED_SYMBOLS)
    if extra_locals:
        # Every name lands inside a quoted string in the generated prelude, so
        # validate here rather than at each of the 33 call sites.
        names.extend(_validated_identifier(n, "variable") for n in extra_locals)
    locals_list = ", ".join(f"'{n}'" for n in dict.fromkeys(names))
    excluded = ", ".join(f"'{n}'" for n in sorted(_SYMBOL_SHAPED_ALREADY_OFFERED))
    greek = ", ".join(
        f"'{n}'" for n in sorted(_GREEK_NAMES | _DECLARABLE_GREEK_LETTERS)
    )
    return textwrap.dedent(
        rf"""
        from sage.all import *
        from sage.all import sage_eval

        class _SymbolLocals(dict):
            # SageMath declares a variable when it *parses a string* into the
            # symbolic ring -- `SR("a*b + a")` creates `a` and `b` -- and not
            # when it runs code, where `w + 1` is a NameError. These tools take
            # a mathematical expression as a string, which is SR's contract, so
            # they behave like SR.
            #
            # Narrower than SR in one way that matters. SR will invent any
            # identifier: `SR("sinn(x)")` returns `sinn(x)` and `SR("pi2*2")`
            # returns `2*pi2`, so a typo becomes a symbol and the caller gets a
            # confident wrong answer. Only symbol-shaped names are declared here
            # -- a letter with an optional index, or a Greek name -- so `a`,
            # `b`, `w` and `x_2` are variables and `sinn`, `foobar` and `pi2`
            # are still errors.
            #
            # The Greek alphabet is here as letters as well as names, because
            # that is how a physicist writes it -- but only the letters
            # SageMath does not already define: five of them are its gamma,
            # zeta, pi, sigma and psi, and shadowing those was a real
            # regression before the allowlist filtered them out.
            #
            # KeyError rather than a symbol is the important branch: it is what
            # lets the lookup fall through to the namespace, so `matrix`, `QQ`
            # and `sin` resolve normally.
            _excluded = frozenset([{excluded}])
            _greek = frozenset([{greek}])

            def __missing__(self, name):
                if name in self._excluded or name.startswith('_'):
                    raise KeyError(name)
                shaped = name in self._greek
                if not shaped:
                    body = name.replace('_', '', 1) if '_' in name[1:] else name
                    # ASCII, mirroring `_SYMBOL_SHAPE` on the Python side: a
                    # letter, then an optional underscore and digit. Python's
                    # `isalpha()` is true for the Greek letters too,
                    # so without the ascii test this declared a fresh symbol
                    # for SageMath's own pi and turned `pi.n()` into "cannot
                    # evaluate symbolic expression numerically". Two
                    # implementations of one rule, disagreeing. The Greek
                    # letters come back through the set above, filtered.
                    head = body[:1]
                    shaped = (
                        len(body) <= 2 and head.isascii() and head.isalpha()
                        and (len(body) == 1 or body[1:].isdigit())
                    )
                if not shaped:
                    raise KeyError(name)
                created = var(name)
                self[name] = created
                return created

        _locals = _SymbolLocals({{name: var(name) for name in [{locals_list}]}})
        """
    )
