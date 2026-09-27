# The proof ladder behind `verify_claim`, as the Sage code it is.
#
# Everything below the marker line is sent to the worker verbatim, after the
# prelude and a data header that `tools/verify.py` builds from gated values:
#
#     _text, _lhs_src, _rhs_src, _op_src   the claim and its sides, each passed
#                                          through `encode_literal`
#     _probe_srcs                          the exactness probes, likewise
#     _nsamples, _prec                     ints
#
# Nothing a caller wrote is interpolated here, so this file is ordinary source
# that ruff lints and the `^` rule checks: it runs as plain Python under
# `trusted_policy()`, NOT through the preparser, so `^` would be XOR.
#
# It lived as a 440-line f-string in `verify_claim` until the 2026-09 refactor
# (REFACTOR_PLAN.md step 2); the text sent to Sage did not change.

# The names the ladder reads without defining, bound to placeholders for the
# linter only: everything above the marker stays on this side. The data header binds the
# first seven, the prelude binds `_locals`, and the rest are Sage globals in
# the worker namespace. A name used below and missing here is a typo, and
# ruff says so.
_text = ...
_lhs_src = ...
_rhs_src = ...
_op_src = ...
_probe_srcs = ...
_nsamples = ...
_prec = ...
_locals = ...
sage_eval = ...
operator = ...
assumptions = ...
ZZ = ...
QQ = ...
SR = ...
AA = ...
QQbar = ...
RealIntervalField = ...
ComplexIntervalField = ...

# --- sent to Sage from the next line ---
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
        # No parent and not a Python number or container: a function, a
        # module, a symbolic constant, a string -- none of which is a
        # machine float. (An inexact NUMBER always has a parent whose
        # ring answers is_exact(), or is a Python float caught above.)
        return False
    if _p is SR:
        return _symbolic_is_inexact(_v)
    try:
        return not _p.is_exact()
    except Exception:
        # `parent()` did not return a ring with a usable `is_exact()`
        # (a symbolic function's parent is its own class, for instance).
        # That is not a machine-number field, so the value is not inexact.
        return False
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
# Exactness is judged from the claim's INPUTS, not its collapsed value: a
# Boolean's type says nothing about how it was produced, so
# `(...).is_zero()`, `... == True` and `(lambda: ...)()` all hid their
# rounding. Evaluate every value-bearing sub-expression and flag any that
# is (or contains) a machine number; the inexact leaf is found wherever
# it sits. A sub-expression that cannot be evaluated on its own (a
# comprehension target, a lambda parameter) is skipped -- it says nothing
# about exactness -- rather than qualifying every claim that has one.
_inexact_operands = False
for _s in _probe_srcs:
    try:
        if _is_inexact(sage_eval(_s, locals=_locals)):
            _inexact_operands = True
            break
    except Exception:
        continue
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
            _point = {}
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
_payload = ({'error': _bad} if _bad is not None else {
    'verdict': _verdict,
    'method': _method,
    'evidence': _evidence,
    'assumptions': _assumption_list,
    'samples': _used_samples,
    'precision_bits': _used_prec,
})
_payload
