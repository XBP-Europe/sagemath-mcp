"""The claim-checking primitive: independently re-verify a stated claim.

One of the tool modules imported by :mod:`sagemath_mcp.server` for its
registration side effect.

`verify_claim` exists for the dominant failure mode of models doing
mathematics: confident wrong algebra. The model states a claim and this server
re-checks it through a ladder -- Sage's symbolic prover, the exact difference,
exact arithmetic over the algebraic fields when the claim is constant, then
certified interval arithmetic and numeric sampling over the free variables.

Two rules keep the verdicts honest, and both live in the generated ladder:

* The prover returning ``False`` means *not proved*, never *false*. ``refuted``
  requires an exact decision or an exhibited counterexample, and interval
  evidence is always a certified enclosure, not a floating-point comparison.
* ``supported`` always carries its evidence -- sample count and precision --
  never a bare confidence number.

Security-wise this adds no new surface: the claim string passes the same
fragment gate (`validated_expression`, via `encode_literal`) as every other
tool parameter before it is interpolated into trusted generated code.
"""

from __future__ import annotations

import ast
import io
import tokenize
from fractions import Fraction
from importlib.resources import files
from typing import Annotated

from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import Field

from .. import runtime
from ..app import mcp
from ..gates import EQUALS_NOT_COMPARISON, encode_literal, validated_expression
from ..models import VerifyClaimResult
from ..prelude import sage_prelude
from ..session import DEFAULT_SESSION_NAME
from ..text import SESSION_ARG_DESC as _SESSION_ARG_DESC
from ..transport import evaluate_structured
from .hints import COMPUTES

_VERDICTS = frozenset({"proved", "refuted", "supported", "undecided"})

# The ladder itself is Sage code in its own file, where it can be linted and
# read; only what follows the marker line is sent (sage_code/verify_ladder.py).
_LADDER_MARK = "# --- sent to Sage from the next line ---\n"
_LADDER = (
    files("sagemath_mcp").joinpath("sage_code", "verify_ladder.py")
    .read_text(encoding="utf-8")
    .split(_LADDER_MARK, 1)[1]
)

# Python's truth-assembly vocabulary. Each of these makes *evaluation* call
# bool() on a symbolic relation -- `not (x == y)`, `x > 0 and x < 1`,
# `0 < x < 1`, a ternary's condition, an explicit bool()/all()/any() -- and
# bool() on a relation is the prover, whose False means "not proved". Letting
# Python fold that into the claim's value would report "not proved" as *false*,
# the exact dishonesty this tool exists to avoid. So a claim is one comparison,
# syntactically.
_TRUTH_ASSEMBLY_MESSAGE = (
    "state one comparison per claim: 'and', 'or', 'not', chained comparisons, "
    "conditionals and bool()/all()/any() are decided by Python's bool(), which "
    "silently treats 'not proved' as False. Verify each part as its own claim."
)


def _exact_decimal_literals(claim: str) -> str:
    """Rewrite decimal literals as the exact rationals they denote.

    `0.1 + 0.2 == 0.3` is true of the decimals and false of the 53-bit doubles
    they become before any comparison runs -- and the first review of this tool
    caught it answering about the doubles while calling the evidence "exact":
    that claim came back refuted, and `1.0 + 1e-20 == 1.0` came back proved
    because the increment rounded away before the comparison. Raising interval
    precision afterwards cannot recover digits already lost, so exactness has
    to be preserved *before* evaluation: `0.1` is read as 1/10, the digits the
    caller actually wrote, and the bool path really is exact at any precision
    the ladder later needs. Complex literals (`1.5j`) are left alone -- j is
    not a symbol this rewrite can honestly rationalise.

    The claim arrives folded to one line and gate-validated, and both gate
    paths tokenize it in full, so `generate_tokens` cannot fail here.
    """
    tokens = list(tokenize.generate_tokens(io.StringIO(claim).readline))
    rewritten = claim
    for token in reversed(tokens):
        if token.type != tokenize.NUMBER:
            continue
        lowered = token.string.lower()
        if lowered.endswith("j") or lowered.startswith("0x"):
            continue
        if "." not in lowered and "e" not in lowered:
            continue  # an integer is already exact
        value = Fraction(token.string.replace("_", ""))
        exact = (
            f"({value.numerator})"
            if value.denominator == 1
            else f"({value.numerator}/{value.denominator})"
        )
        rewritten = rewritten[: token.start[1]] + exact + rewritten[token.end[1]:]
    return rewritten


_AST_COMPARE_OPS = {
    ast.Eq: "==",
    ast.NotEq: "!=",
    ast.Lt: "<",
    ast.LtE: "<=",
    ast.Gt: ">",
    ast.GtE: ">=",
}


def _comparison_sides(claim: str) -> tuple[str | None, str | None, str | None]:
    """The two operands and operator of the claim's single top-level comparison.

    Returned as source strings so the generated code can evaluate each side
    *once*, inspect its exactness, and build the comparison from those retained
    values -- rather than re-evaluating the source after the collapsed Boolean
    has already thrown the operands away. `RR(1) + RR(1)/10^20 == RR(1)`
    evaluates to True by floating-point rounding; with the sides the ladder sees
    both live in an inexact field and refuses the exact verdict. Only a single
    comparison is handled (the truth-assembly gate guarantees at most one); a
    bare predicate like `is_prime(7)` has no sides and is evaluated whole. Either
    way, exactness is judged from `_exactness_probe_sources`, not from this.
    """
    candidate = EQUALS_NOT_COMPARISON.sub("==", claim)
    try:
        node = ast.parse(candidate, mode="eval").body
    except SyntaxError:
        return (None, None, None)
    if isinstance(node, ast.Compare) and len(node.ops) == 1:
        op = _AST_COMPARE_OPS.get(type(node.ops[0]))
        if op is not None:
            # The ORIGINAL source of each side, never ast.unparse: `^` is Python
            # bit-xor (looser than +/-/*), so unparsing `x^2 - 2*x + 1` yields
            # `x ^ (2 - 2*x + 1)`, the wrong expression once Sage's preparser
            # reads `^` as a power. `get_source_segment`, not raw column slicing:
            # AST offsets count UTF-8 bytes while `str` slices count characters,
            # so a claim in Greek letters (two bytes per char) sliced mid-symbol.
            return (
                ast.get_source_segment(candidate, node.left),
                ast.get_source_segment(candidate, node.comparators[0]),
                op,
            )
    return (None, None, None)


def _exactness_probe_sources(claim: str) -> list[str]:
    """Every value-bearing sub-expression of the claim, as source strings.

    Exactness is a property of a claim's INPUTS, and a Boolean result hides them:
    `_is_inexact` can only see that the value is a `bool` and calls it exact, so
    `(RR(1)+RR(1)/10^20-RR(1)).is_zero()` -- and, once a comparison collapses,
    `... == True` or `(lambda: ...)()` -- were reported as exact proofs though
    they rest on rounding. Adding `== True` cannot increase certainty.

    So instead of trusting the collapsed value, the ladder evaluates each
    sub-expression the claim is built from and asks whether any is (or contains)
    a machine number. The inexact leaf (`RR(1)`) is a sub-expression of all three
    cases above -- inside the receiver, inside the lambda body -- so it is found
    regardless of how the Boolean was assembled. Exact claims are unaffected:
    every sub-expression of `sin(x)^2 + cos(x)^2 == 1` is exact.

    Sources come from `get_source_segment` (UTF-8-byte offsets vs character
    slices, and `^` must not round-trip -- see `_comparison_sides`), deduplicated.
    """
    candidate = EQUALS_NOT_COMPARISON.sub("==", claim)
    try:
        tree = ast.parse(candidate, mode="eval")
    except SyntaxError:
        return []
    # Value expressions that can introduce or carry a number. Booleans
    # (`ast.BoolOp`) are excluded as containers -- their operands are visited on
    # their own -- and names/constants are cheap to re-check.
    value_nodes = (
        ast.Call, ast.Attribute, ast.BinOp, ast.UnaryOp, ast.Subscript,
        ast.Name, ast.Constant, ast.List, ast.Tuple, ast.Set, ast.Dict,
    )
    sources: list[str] = []
    seen: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, value_nodes):
            segment = ast.get_source_segment(candidate, node)
            if segment and segment not in seen:
                seen.add(segment)
                sources.append(segment)
    return sources


def _reject_truth_assembly(claim: str) -> None:
    """Refuse a claim whose truth Python would assemble out of bool().

    Checked syntactically, before evaluation, on the same equation rewrite the
    fragment gate uses (so `x^2 - 1 = 0` still parses). A claim the rewrite
    still cannot parse is left to sage_eval, whose preparser owns Sage-only
    spellings; nothing bool()-shaped survives tokenisation as one of those.
    """
    candidate = EQUALS_NOT_COMPARISON.sub("==", claim)
    try:
        parsed = ast.parse(candidate, mode="eval")
    except SyntaxError:
        return
    for node in ast.walk(parsed):
        offending = (
            isinstance(node, (ast.BoolOp, ast.IfExp))
            or (isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not))
            or (isinstance(node, ast.Compare) and len(node.ops) > 1)
            or (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in {"bool", "all", "any"}
            )
        )
        if offending:
            raise ToolError(_TRUTH_ASSEMBLY_MESSAGE)


@mcp.tool(annotations=COMPUTES, description="""\
Independently re-check a stated mathematical claim and report how far the \
evidence goes: proved, refuted, supported or undecided.

Use this to verify your own algebra before presenting it. The claim is a single \
comparison in Sage syntax -- an equality, an inequality, or anything that \
evaluates to True/False:

  integral(x^2/(e^x-1), x, 0, oo) == 2*zeta(3)
  sin(x)^2 + cos(x)^2 == 1
  pi < 22/7
  e^pi != pi^e

The check climbs a ladder: Sage's symbolic prover, the exact difference \
((lhs-rhs).simplify_full().is_zero()), exact arithmetic over QQbar/AA when the \
claim is constant, then certified interval arithmetic and numeric sampling over \
the free variables. Verdicts are honest by construction: 'proved' and 'refuted' \
are exact decisions ('refuted' always exhibits its counterexample or certified \
enclosure); 'supported' means the numeric evidence is consistent with the claim \
without proving it, and says how many samples at what precision; 'undecided' \
means every rung was inconclusive -- it never means false.

Exactness is never assumed. Decimal literals are read exactly (0.1 means 1/10, \
never the 53-bit double), and a comparison whose operands are machine floats \
(RR/RDF/CC, an .n() result) is reported as 'supported' over inexact numbers, \
never as an exact proof -- state it over ZZ/QQ/QQbar or symbolically for an \
exact verdict. The session's active assumptions (assume(x > 0), assume(x, \
'integer')) are honored: a sampled counterexample must lie inside the stated \
domain, and any verdict that relied on an assumption names it in the evidence.
""")
async def verify_claim(
    claim: Annotated[
        str,
        Field(
            description="The claim to check, as a single comparison, "
            "e.g. 'sin(x)**2 + cos(x)**2 == 1'"
        ),
    ],
    samples: Annotated[
        int,
        Field(
            description="Sample points per free variable sweep when the claim "
            "cannot be decided exactly",
            ge=1,
            le=64,
        ),
    ] = 12,
    precision_bits: Annotated[
        int,
        Field(
            description="Precision of the certified interval arithmetic behind "
            "numeric verdicts",
            ge=53,
            le=4096,
        ),
    ] = 128,
    timeout_seconds: Annotated[
        float | None,
        Field(
            description="Override the evaluation timeout in seconds",
            alias="timeout",
            validation_alias="timeout",
            serialization_alias="timeout",
            gt=0.0,
            default=None,
        ),
    ] = None,
    session: Annotated[str, Field(description=_SESSION_ARG_DESC)] = DEFAULT_SESSION_NAME,
    ctx: Context | None = None,
) -> VerifyClaimResult:
    runtime.require_context(ctx, "for stateful execution")
    if not claim or not claim.strip():
        raise ToolError(
            "'claim' must state a comparison, e.g. 'sin(x)**2 + cos(x)**2 == 1'"
        )
    sage_session = await runtime.session_for(ctx, session)
    claim = validated_expression(claim)
    rewritten = _exact_decimal_literals(claim)
    if rewritten != claim:
        # Validate exactly what runs, the same rule the fold follows. The
        # rewrite only inserts digits, parentheses and division, but the gate
        # judging anything other than the final text is how item 55 happened.
        claim = validated_expression(rewritten)
    _reject_truth_assembly(claim)
    lhs_src, rhs_src, op_src = _comparison_sides(claim)
    have_sides = lhs_src is not None and rhs_src is not None
    lhs_literal = encode_literal(lhs_src) if have_sides else "None"
    rhs_literal = encode_literal(rhs_src) if have_sides else "None"
    op_literal = encode_literal(op_src) if have_sides else "None"
    # Exactness is judged from the claim's inputs, not its collapsed value: every
    # value-bearing sub-expression is evaluated and checked, so a machine number
    # hidden inside a Boolean (a predicate, `== True`, a lambda) is still found.
    probe_srcs = _exactness_probe_sources(claim)
    probe_srcs_literal = "[" + ", ".join(encode_literal(s) for s in probe_srcs) + "]"
    header = "\n".join((
        f"_text = {encode_literal(claim)}",
        f"_lhs_src = {lhs_literal}",
        f"_rhs_src = {rhs_literal}",
        f"_op_src = {op_literal}",
        f"_probe_srcs = {probe_srcs_literal}",
        f"_nsamples = {int(samples)}",
        f"_prec = {int(precision_bits)}",
    ))
    code = sage_prelude() + "\n" + header + "\n" + _LADDER
    payload = await evaluate_structured(sage_session, code, timeout_seconds=timeout_seconds)
    if not isinstance(payload, dict):
        raise ToolError(f"SageMath returned an unexpected verification payload: {payload!r}")
    if "error" in payload:
        raise ToolError(payload["error"])
    verdict = payload.get("verdict")
    if verdict not in _VERDICTS:
        raise ToolError(f"SageMath returned an unexpected verdict: {payload.get('verdict')!r}")
    return VerifyClaimResult(
        claim=claim,
        verdict=verdict,
        method=payload.get("method"),
        evidence=payload.get("evidence"),
        assumptions=payload.get("assumptions") or [],
        samples=payload.get("samples"),
        precision_bits=payload.get("precision_bits"),
    )
