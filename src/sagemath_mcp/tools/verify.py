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
fragment gate (`_validated_expression`, via `_encode_literal`) as every other
tool parameter before it is interpolated into trusted generated code.
"""

from __future__ import annotations

import ast
import io
import textwrap
import tokenize
from fractions import Fraction
from typing import Annotated

from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import Field

from .. import runtime
from ..app import mcp
from ..codegen import (
    _EQUALS_NOT_COMPARISON,
    _encode_literal,
    _evaluate_structured,
    _sage_prelude,
    _validated_expression,
)
from ..models import VerifyClaimResult
from ..session import DEFAULT_SESSION_NAME
from ..text import SESSION_ARG_DESC as _SESSION_ARG_DESC
from .hints import COMPUTES

_VERDICTS = frozenset({"proved", "refuted", "supported", "undecided"})

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
    bare predicate like `is_prime(7)` has no sides and is left to whole-claim
    evaluation (its inputs are inspected via `_predicate_operand_sources`).
    """
    candidate = _EQUALS_NOT_COMPARISON.sub("==", claim)
    try:
        node = ast.parse(candidate, mode="eval").body
    except SyntaxError:
        return (None, None, None)
    if isinstance(node, ast.Compare) and len(node.ops) == 1:
        op = _AST_COMPARE_OPS.get(type(node.ops[0]))
        if op is not None:
            # Slice the ORIGINAL substrings, never ast.unparse: `^` is Python
            # bit-xor (looser than +/-/*), so unparsing `x^2 - 2*x + 1` yields
            # `x ^ (2 - 2*x + 1)` -- the wrong expression once Sage's preparser
            # reads `^` as a power. The claim is whitespace-folded to one line,
            # so column offsets index it directly.
            return (
                candidate[node.left.col_offset : node.left.end_col_offset],
                candidate[node.comparators[0].col_offset : node.comparators[0].end_col_offset],
                op,
            )
    return (None, None, None)


def _predicate_operand_sources(claim: str) -> list[str]:
    """Operand sources for a claim that is *not* a top-level comparison.

    A bare predicate collapses to a Boolean that cannot reveal its own
    provenance -- `(RR(1)+RR(1)/10^20-RR(1)).is_zero()` returns True by rounding,
    with no comparison sides for the ladder to inspect, so it was proved exact.
    The exactness check reads the predicate's inputs from the source instead: the
    receiver and arguments of a top-level call (`X.is_zero()` -> `[X]`,
    `is_prime(n)` -> `[n]`), otherwise the whole expression. Empty when the claim
    IS a comparison -- that path already inspects its two sides.
    """
    candidate = _EQUALS_NOT_COMPARISON.sub("==", claim)
    try:
        node = ast.parse(candidate, mode="eval").body
    except SyntaxError:
        return []
    def _src(sub: ast.AST) -> str:
        # Original substring, not ast.unparse -- see _comparison_sides on why `^`
        # cannot survive a round-trip through the Python AST.
        return candidate[sub.col_offset : sub.end_col_offset]

    if isinstance(node, ast.Compare):
        return []
    if isinstance(node, ast.Call):
        sources: list[str] = []
        if isinstance(node.func, ast.Attribute):
            sources.append(_src(node.func.value))
        sources.extend(_src(a) for a in node.args if not isinstance(a, ast.Starred))
        return sources or [_src(node)]
    return [_src(node)]


def _reject_truth_assembly(claim: str) -> None:
    """Refuse a claim whose truth Python would assemble out of bool().

    Checked syntactically, before evaluation, on the same equation rewrite the
    fragment gate uses (so `x^2 - 1 = 0` still parses). A claim the rewrite
    still cannot parse is left to sage_eval, whose preparser owns Sage-only
    spellings; nothing bool()-shaped survives tokenisation as one of those.
    """
    candidate = _EQUALS_NOT_COMPARISON.sub("==", claim)
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
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required for stateful execution")
    if not claim or not claim.strip():
        raise ToolError(
            "'claim' must state a comparison, e.g. 'sin(x)**2 + cos(x)**2 == 1'"
        )
    sage_session = await runtime.resolve_session(ctx.session_id, session)
    claim = _validated_expression(claim)
    rewritten = _exact_decimal_literals(claim)
    if rewritten != claim:
        # Validate exactly what runs, the same rule the fold follows. The
        # rewrite only inserts digits, parentheses and division, but the gate
        # judging anything other than the final text is how item 55 happened.
        claim = _validated_expression(rewritten)
    _reject_truth_assembly(claim)
    lhs_src, rhs_src, op_src = _comparison_sides(claim)
    have_sides = lhs_src is not None and rhs_src is not None
    lhs_literal = _encode_literal(lhs_src) if have_sides else "None"
    rhs_literal = _encode_literal(rhs_src) if have_sides else "None"
    op_literal = _encode_literal(op_src) if have_sides else "None"
    # For a bare predicate (no top-level comparison), the values to check for
    # exactness are the predicate's own operands, read from the source -- the
    # collapsed Boolean cannot reveal them. Encoded as literals like the sides.
    operand_srcs = _predicate_operand_sources(claim)
    operand_srcs_literal = "[" + ", ".join(_encode_literal(s) for s in operand_srcs) + "]"
    code = (
        _sage_prelude()
        + textwrap.dedent(
            f"""
        _text = {_encode_literal(claim)}
        _lhs_src = {lhs_literal}
        _rhs_src = {rhs_literal}
        _op_src = {op_literal}
        _operand_srcs = {operand_srcs_literal}
        _nsamples = {int(samples)}
        _prec = {int(precision_bits)}
        # When the claim is a single comparison, evaluate each side EXACTLY ONCE
        # and build the relation from those retained values -- so the exactness
        # check below inspects the very values the comparison used, not a second
        # evaluation of the source (which a non-deterministic function could make
        # disagree). Bare predicates have no sides and are evaluated whole.
        _lhs_v = _rhs_v = None
        if _lhs_src is not None:
            _lhs_v = sage_eval(_lhs_src, locals=_locals)
            _rhs_v = sage_eval(_rhs_src, locals=_locals)
            if _op_src == '==':
                _claim = (_lhs_v == _rhs_v)
            elif _op_src == '!=':
                _claim = (_lhs_v != _rhs_v)
            elif _op_src == '<':
                _claim = (_lhs_v < _rhs_v)
            elif _op_src == '<=':
                _claim = (_lhs_v <= _rhs_v)
            elif _op_src == '>':
                _claim = (_lhs_v > _rhs_v)
            else:
                _claim = (_lhs_v >= _rhs_v)
        else:
            try:
                _claim = sage_eval(_text, locals=_locals)
            except SyntaxError:
                _sides = _text.split('=')
                if len(_sides) != 2:
                    raise
                _claim = (sage_eval(_sides[0].strip(), locals=_locals)
                          == sage_eval(_sides[1].strip(), locals=_locals))
        def _symbolic_is_inexact(_e):
            # A symbolic expression is exact only if every numeric constant in it
            # is exact. Walk the tree; a leaf that wraps a machine number
            # (SR(RR(1)+...) carries a RealNumber) makes the whole expression
            # inexact. Wrapping an approximate value in SR does not launder it.
            try:
                _ops = _e.operands()
            except Exception:
                _ops = []
            if _ops:
                return any(_symbolic_is_inexact(_o) for _o in _ops)
            try:
                _obj = _e.pyobject()
            except (TypeError, AttributeError):
                return False  # a symbol or structural leaf, not a number
            if isinstance(_obj, (float, complex)):
                return True
            try:
                return not _obj.parent().is_exact()
            except AttributeError:
                # A symbolic constant (pi, e, euler_gamma, ...) has no parent and
                # is exact -- unlike the machine RealNumber that SR(1.0) carries.
                return False
        def _is_inexact(_v):
            # True when the value IS, or CONTAINS, a machine-precision number --
            # a Python float/complex, a value in an inexact ring (RR/RDF/CC/RIF),
            # an element of a list/tuple/set/dict that is, or a symbolic
            # expression carrying an approximate constant. Exactness is a
            # prerequisite for every proof path, so this is deliberately
            # conservative: a value whose provenance cannot be established
            # (no parent, not a container) is treated as inexact rather than
            # assumed exact.
            if isinstance(_v, bool):
                return False
            if isinstance(_v, (float, complex)):
                return True
            if isinstance(_v, int):
                return False
            if isinstance(_v, (list, tuple, set, frozenset)):
                return any(_is_inexact(_e) for _e in _v)
            if isinstance(_v, dict):
                # Keys take part in equality too -- a dict with an inexact key
                # and an exact value must still count -- so check both, not just
                # values.
                return any(_is_inexact(_e) for _e in _v.keys()) or any(
                    _is_inexact(_e) for _e in _v.values()
                )
            try:
                _p = _v.parent()
            except AttributeError:
                return True  # unknown provenance -> qualify, never prove
            if _p is SR:
                return _symbolic_is_inexact(_v)
            try:
                return not _p.is_exact()
            except Exception:
                return True
        def _domain_holds(_dom, _val):
            # Does a rational sample value lie in a declared domain?
            try:
                if _dom == 'integer':
                    return _val in ZZ
                if _dom == 'noninteger':
                    return _val not in ZZ
                if _dom == 'even':
                    return (_val in ZZ) and (ZZ(_val) % 2 == 0)
                if _dom == 'odd':
                    return (_val in ZZ) and (ZZ(_val) % 2 == 1)
                if _dom == 'rational':
                    return _val in QQ
                if _dom in ('real', 'noncomplex'):
                    return _val in QQ  # every sample value is a rational real
                if _dom == 'complex':
                    return True
            except Exception:
                return False
            return False  # an unrecognised domain cannot be confirmed
        def _point_admissible(_assumed, _point):
            # `getattr` and private attributes are unavailable to generated code,
            # so a domain declaration is read from its string form ("x is
            # integer") rather than its internals.
            _pt_names = dict((str(_k), _k) for _k in _point)
            for _a in _assumed:
                _s = str(_a)
                if ' is ' in _s:
                    _name, _, _dom = _s.partition(' is ')
                    _name = _name.strip()
                    _dom = _dom.strip()
                    if _name not in _pt_names:
                        continue  # constrains a variable this sample does not set
                    if not _domain_holds(_dom, _point[_pt_names[_name]]):
                        return False
                    continue
                # A relational assumption. Irrelevant if it shares no variable
                # with the sample; otherwise it must be confirmed to hold there.
                try:
                    _avars = set(_a.variables())
                except Exception:
                    _avars = set()
                if _avars and _avars.isdisjoint(_point):
                    continue
                try:
                    _sv = _a.subs(_point)
                    if (_sv is True) or (bool(_sv) is True):
                        continue
                    return False
                except Exception:
                    return False
            return True
        _inexact_operands = False
        try:
            if _lhs_src is not None:
                # A comparison: inspect the retained side values, the very ones
                # the relation above was built from -- not a second evaluation
                # of the source.
                _inexact_operands = _is_inexact(_lhs_v) or _is_inexact(_rhs_v)
            elif isinstance(_claim, bool):
                # A bare predicate (no comparison sides). The collapsed Boolean
                # cannot reveal its provenance, so inspect the predicate's own
                # operands, read from the source. No operands to check (an opaque
                # predicate) is itself unestablished provenance -> qualify.
                if _operand_srcs:
                    _inexact_operands = any(
                        _is_inexact(sage_eval(_s, locals=_locals)) for _s in _operand_srcs
                    )
                else:
                    _inexact_operands = True
            elif hasattr(_claim, 'is_relational') and _claim.is_relational():
                _inexact_operands = _is_inexact(_claim.lhs()) or _is_inexact(_claim.rhs())
        except Exception:
            _inexact_operands = True  # cannot establish exactness -> qualify, never prove
        _verdict = None
        _method = None
        _evidence = None
        _bad = None
        _used_samples = None
        _used_prec = None
        _assumed = assumptions()
        _anote = ''
        if _assumed:
            _anote = ("; under the session's active assumptions: "
                      + ', '.join(str(_a) for _a in _assumed))
        if _inexact_operands:
            # Exactness is a prerequisite for a proof, and it fails: an operand
            # is a machine-precision number, or contains one, or is an
            # approximate constant wrapped in a list or in SR. NO path may return
            # 'proved'/'refuted' here -- a floating-point comparison is a true
            # observation about machine numbers, not the exact identity this tool
            # advertises. A holding comparison is 'supported' (inexactness named),
            # a failing or undecidable one is 'undecided' (rounding could decide
            # it either way).
            _method = 'float_comparison'
            try:
                if isinstance(_claim, bool):
                    _decides = _claim
                elif (hasattr(_claim, 'is_relational') and _claim.is_relational()
                      and not _claim.variables()):
                    _decides = bool(_claim)
                else:
                    _decides = None  # free variables: not decidable to a Boolean
            except Exception:
                _decides = None
            if _decides is True:
                _verdict = 'supported'
                _evidence = ('holds under inexact machine-number (floating-point) '
                             'evaluation; not established as an exact identity. '
                             'State it over exact numbers (ZZ/QQ/QQbar or exact '
                             'symbolic constants) for an exact verdict' + _anote)
            elif _decides is False:
                _verdict = 'undecided'
                _evidence = ('does not hold under inexact machine-number evaluation, '
                             'which cannot exactly refute it -- rounding may have '
                             'decided the comparison' + _anote)
            else:
                _verdict = 'undecided'
                _evidence = ('the claim carries inexact machine numbers, so no exact '
                             'proof path applies; state it over exact numbers for a '
                             'decisive verdict' + _anote)
        elif isinstance(_claim, bool):
            _verdict = 'proved' if _claim else 'refuted'
            _method = 'exact_comparison'
            _evidence = ('the claim evaluates to ' + str(_claim)
                         + ' under exact evaluation' + _anote)
        elif not (hasattr(_claim, 'is_relational') and _claim.is_relational()):
            _bad = ('the claim must be a comparison (==, =, !=, <, <=, >, >=) or '
                    'evaluate to True/False; it evaluated to: ' + str(_claim))
        else:
            _op = _claim.operator()
            _lhs = _claim.lhs()
            _rhs = _claim.rhs()
            _is_eq = _op is operator.eq
            _is_ne = _op is operator.ne
            _vars = sorted(_claim.variables(), key=str)
            if not _is_ne:
                try:
                    if bool(_claim):
                        _verdict = 'proved'
                        _method = 'symbolic_prover'
                        _evidence = 'SageMath proves the relation symbolically' + _anote
                except Exception:
                    pass
            if _verdict is None and _is_eq:
                try:
                    if ((_lhs - _rhs).simplify_full()).is_zero():
                        _verdict = 'proved'
                        _method = 'exact_difference'
                        _evidence = ('(lhs - rhs).simplify_full() is exactly zero'
                                     + _anote)
                except Exception:
                    pass
            if _verdict is None and not _vars:
                try:
                    if _is_eq or _is_ne:
                        _same = QQbar(_lhs) == QQbar(_rhs)
                        _holds = _same if _is_eq else (not _same)
                    else:
                        _holds = bool(_op(AA(_lhs), AA(_rhs)))
                    _verdict = 'proved' if _holds else 'refuted'
                    _method = 'exact_algebraic'
                    _evidence = ('decided exactly over the algebraic numbers: '
                                 + str(_lhs) + ' versus ' + str(_rhs))
                except (TypeError, ValueError, NotImplementedError):
                    pass
            if _verdict is None and not _vars:
                try:
                    if _is_eq or _is_ne:
                        _C = ComplexIntervalField(_prec)
                        _enc = _C(_lhs) - _C(_rhs)
                    else:
                        _F = RealIntervalField(_prec)
                        _enc = _F(_lhs) - _F(_rhs)
                    _used_prec = _prec
                    if _is_eq or _is_ne:
                        if not _enc.contains_zero():
                            _verdict = 'refuted' if _is_eq else 'proved'
                            _method = 'certified_interval'
                            _evidence = ('lhs - rhs lies in ' + str(_enc)
                                         + ', a certified enclosure at ' + str(_prec)
                                         + ' bits that excludes zero')
                        elif _is_eq:
                            _verdict = 'supported'
                            _method = 'certified_interval'
                            _evidence = ('the certified enclosure of lhs - rhs at '
                                         + str(_prec) + ' bits contains zero: '
                                         + str(_enc) + '; equality is consistent '
                                         'but not proved')
                        else:
                            _verdict = 'undecided'
                            _method = 'certified_interval'
                            _evidence = ('the certified enclosure of lhs - rhs at '
                                         + str(_prec) + ' bits still contains zero')
                    else:
                        _strict = (_op is operator.lt) or (_op is operator.gt)
                        _flip = (_op is operator.gt) or (_op is operator.ge)
                        _d = -_enc if _flip else _enc
                        _holds = _d.upper() < 0 if _strict else _d.upper() <= 0
                        _fails = _d.lower() >= 0 if _strict else _d.lower() > 0
                        if _holds:
                            _verdict = 'proved'
                            _method = 'certified_interval'
                            _evidence = ('the certified enclosure at ' + str(_prec)
                                         + ' bits decides the inequality: '
                                         'lhs - rhs lies in ' + str(_enc))
                        elif _fails:
                            _verdict = 'refuted'
                            _method = 'certified_interval'
                            _evidence = ('the certified enclosure at ' + str(_prec)
                                         + ' bits decides against the inequality: '
                                         'lhs - rhs lies in ' + str(_enc))
                        elif not _strict:
                            _verdict = 'supported'
                            _method = 'certified_interval'
                            _evidence = ('the certified enclosure of lhs - rhs at '
                                         + str(_prec) + ' bits contains zero; the '
                                         'non-strict inequality is consistent but '
                                         'not proved')
                        else:
                            _verdict = 'undecided'
                            _method = 'certified_interval'
                            _evidence = ('the certified enclosure of lhs - rhs at '
                                         + str(_prec) + ' bits still contains zero')
                except (TypeError, ValueError, NotImplementedError):
                    pass
            if _verdict is None and _vars:
                _supporting = 0
                _skipped = 0
                _F = RealIntervalField(_prec)
                _C = ComplexIntervalField(_prec)
                for _i in range(_nsamples):
                    if _verdict is not None:
                        break
                    _point = {{}}
                    for _j, _v in enumerate(_vars):
                        _val = QQ(3 * _i + 2 * _j + 1) / QQ(2 + ((_i + _j) % 5))
                        if _i % 2 == 1:
                            _val = -_val
                        _point[_v] = _val
                    # Use a point only if its admissibility is established: every
                    # active assumption must be confirmed to hold there (or be
                    # irrelevant to it). A domain declaration like
                    # `assume(x, 'integer')` cannot be substituted, so ignoring
                    # it produced a false counterexample at x = 1/2 for
                    # `x != 1/2`; now an unconfirmable assumption makes the point
                    # inadmissible and the sweep converges to undecided rather
                    # than exhibiting a counterexample outside the stated domain.
                    if not _point_admissible(_assumed, _point):
                        _skipped += 1
                        continue
                    try:
                        _dv = (_lhs - _rhs).subs(_point)
                        _enc = _C(_dv) if (_is_eq or _is_ne) else _F(_dv)
                    except Exception:
                        _skipped += 1
                        continue
                    _at = ', '.join(str(_v) + ' = ' + str(_point[_v]) for _v in _vars)
                    if _is_eq:
                        if not _enc.contains_zero():
                            _verdict = 'refuted'
                            _method = 'numeric_sampling'
                            _evidence = ('counterexample at ' + _at + ': lhs - rhs '
                                         'lies in ' + str(_enc) + ', a certified '
                                         'enclosure at ' + str(_prec)
                                         + ' bits that excludes zero' + _anote)
                        else:
                            _supporting += 1
                    elif _is_ne:
                        if not _enc.contains_zero():
                            _supporting += 1
                        else:
                            try:
                                if _dv.simplify_full().is_zero():
                                    _verdict = 'refuted'
                                    _method = 'numeric_sampling'
                                    _evidence = ('counterexample at ' + _at
                                                 + ': lhs - rhs is exactly zero there'
                                                 + _anote)
                                else:
                                    _skipped += 1
                            except Exception:
                                _skipped += 1
                    else:
                        _strict = (_op is operator.lt) or (_op is operator.gt)
                        _flip = (_op is operator.gt) or (_op is operator.ge)
                        _d = -_enc if _flip else _enc
                        _holds = _d.upper() < 0 if _strict else _d.upper() <= 0
                        _fails = _d.lower() >= 0 if _strict else _d.lower() > 0
                        if _holds:
                            _supporting += 1
                        elif _fails:
                            _verdict = 'refuted'
                            _method = 'numeric_sampling'
                            _evidence = ('counterexample at ' + _at + ': lhs - rhs '
                                         'lies in ' + str(_enc) + ', certified at '
                                         + str(_prec) + ' bits' + _anote)
                        else:
                            _skipped += 1
                if _verdict is None:
                    _used_prec = _prec
                    if _supporting > 0:
                        _verdict = 'supported'
                        _method = 'numeric_sampling'
                        _used_samples = int(_supporting)
                        _evidence = ('holds at ' + str(_supporting) + ' of '
                                     + str(_nsamples) + ' sampled points, each '
                                     'checked with certified interval arithmetic '
                                     'at ' + str(_prec) + ' bits; no counterexample '
                                     'found' + _anote)
                    else:
                        _verdict = 'undecided'
                        _method = 'numeric_sampling'
                        _evidence = ('no sampled point could be evaluated '
                                     'decisively (' + str(_skipped) + ' of '
                                     + str(_nsamples) + ' skipped)')
        if _bad is None and _verdict is None:
            _verdict = 'undecided'
            _method = 'exhausted'
            _evidence = ('neither proved nor refuted: the symbolic prover, the '
                         'exact difference, exact algebraic arithmetic and the '
                         'certified numeric rungs were all inconclusive')
        # Attach the active assumptions centrally: a verdict that relied on them
        # must name them, and doing it here -- not in each rung -- is what keeps
        # a branch (the algebraic one did) from silently omitting them. Idempotent
        # for the rungs that already appended _anote.
        _assumption_list = [str(_a) for _a in _assumed]
        if _bad is None and _anote and _evidence is not None and _anote not in _evidence:
            _evidence = _evidence + _anote
        _payload = ({{'error': _bad}} if _bad is not None else {{
            'verdict': _verdict,
            'method': _method,
            'evidence': _evidence,
            'assumptions': _assumption_list,
            'samples': _used_samples,
            'precision_bits': _used_prec,
        }})
        _payload
        """
        )
    )
    payload = await _evaluate_structured(sage_session, code, timeout_seconds=timeout_seconds)
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
