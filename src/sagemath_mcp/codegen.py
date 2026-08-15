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
import io
import json
import re
import textwrap
import tokenize
from collections.abc import Iterable
from dataclasses import replace

from fastmcp.exceptions import ToolError

from .security import SECURITY_POLICY, SecurityViolation, validate_module
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
_FRAGMENT_POLICY = replace(SECURITY_POLICY, enforce_name_allowlist=False)


def _screen_unparseable_fragment(fragment: str) -> None:
    """Reject forbidden names in a fragment that would not parse.

    Full AST validation needs a parse tree. When there is none, screen the token
    stream instead: a name is a name whatever surrounds it, and this is the last
    gate before the fragment is interpolated into trusted, sage_eval'd code.
    """
    forbidden = set(_FRAGMENT_POLICY.forbidden_call_names) | set(
        _FRAGMENT_POLICY.forbidden_attribute_parents
    )
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(fragment).readline))
    except (tokenize.TokenError, IndentationError) as exc:
        raise ToolError(
            f"Could not read {fragment!r} as an expression: {exc}"
        ) from exc
    for token in tokens:
        if token.type != tokenize.NAME:
            continue
        if token.string in forbidden or (
            token.string.startswith("__") and token.string.endswith("__")
        ):
            raise ToolError(
                f"Rejected by the security policy: reference to "
                f"'{token.string}' is blocked"
            )


def _validated_expression(text: str) -> str:
    """Check a caller-supplied fragment before it is embedded in generated code.

    The helper tools wrap caller input in sage_eval("<text>"). The AST validator
    sees only a string constant there, so until this existed the entire
    specialised tool surface evaluated caller code unchecked:
    calculate_expression("__import__('os').getuid()") returned the container uid.

    Validating the fragment as an expression in its own right closes that, and
    is what makes the trusted worker path in _evaluate_structured safe.
    """
    if not isinstance(text, str):
        return text
    stripped = text.strip()
    if not stripped:
        return text
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
                return text
        else:
            _screen_unparseable_fragment(stripped)
            return text
    try:
        validate_module(
            ast.Module(body=[ast.Expr(value=parsed.body)], type_ignores=[]),
            code=stripped,
            policy=_FRAGMENT_POLICY,
        )
    except SecurityViolation as exc:
        raise ToolError(f"Rejected by the security policy: {exc}") from exc
    return text


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
# parameterised one such as "CompleteGraph(4)".
_NAMED_GRAPH_RE = re.compile(r"^(?P<name>[A-Za-z_]\w*)\s*(?P<call>\(.*\))?$", re.DOTALL)


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


def _sage_prelude(extra_locals: Iterable[str] | None = None) -> str:
    names = list(PREDEFINED_SYMBOLS)
    if extra_locals:
        # Every name lands inside a quoted string in the generated prelude, so
        # validate here rather than at each of the 33 call sites.
        names.extend(_validated_identifier(n, "variable") for n in extra_locals)
    locals_list = ", ".join(f"'{n}'" for n in dict.fromkeys(names))
    return textwrap.dedent(
        f"""
        from sage.all import *
        from sage.all import sage_eval
        _locals = {{name: var(name) for name in [{locals_list}]}}
        """
    )
