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
import textwrap
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
    _reject_truth_assembly(claim)
    code = (
        _sage_prelude()
        + textwrap.dedent(
            f"""
        _text = {_encode_literal(claim)}
        _nsamples = {int(samples)}
        _prec = {int(precision_bits)}
        try:
            _claim = sage_eval(_text, locals=_locals)
        except SyntaxError:
            _sides = _text.split('=')
            if len(_sides) != 2:
                raise
            _claim = (sage_eval(_sides[0].strip(), locals=_locals)
                      == sage_eval(_sides[1].strip(), locals=_locals))
        _verdict = None
        _method = None
        _evidence = None
        _bad = None
        _used_samples = None
        _used_prec = None
        if isinstance(_claim, bool):
            _verdict = 'proved' if _claim else 'refuted'
            _method = 'exact_comparison'
            _evidence = ('the claim evaluates to ' + str(_claim)
                         + ' under exact evaluation')
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
                        _evidence = 'SageMath proves the relation symbolically'
                except Exception:
                    pass
            if _verdict is None and _is_eq:
                try:
                    if ((_lhs - _rhs).simplify_full()).is_zero():
                        _verdict = 'proved'
                        _method = 'exact_difference'
                        _evidence = '(lhs - rhs).simplify_full() is exactly zero'
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
                                         + ' bits that excludes zero')
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
                                                 + ': lhs - rhs is exactly zero there')
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
                                         + str(_prec) + ' bits')
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
                                     'found')
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
        _payload = ({{'error': _bad}} if _bad is not None else {{
            'verdict': _verdict,
            'method': _method,
            'evidence': _evidence,
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
        samples=payload.get("samples"),
        precision_bits=payload.get("precision_bits"),
    )
