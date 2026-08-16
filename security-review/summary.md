# Security review summary — branch `fix/fragment-gate-and-monitoring-leak`

**Reviewed:** the pending changes on this branch (items 55–60 + the monitoring leak fix)
against `main`, at commit `0176c7e`. Findings verified live against SageMath 10.9 in the
`sage-mcp` container.

## Findings by severity

| Severity | Count |
|----------|-------|
| Critical | 1 |
| High / Medium / Low | 0 |

## Needs action this week

1. **F-001 (Critical) — Fix the star-import escape before this branch merges.** The new
   item-60 feature lets a single `evaluate_sage` call reach the real `os` module and run
   shell commands (`os.system` confirmed executing as uid 1001; `os.environ` readable). Two
   of the 13 curated modules re-export module objects (`dirichlet`, `time`) that the
   `_star_export_screen` provenance check cannot see, because module objects have no
   `__module__`. The one-line fix is to reject `types.ModuleType` exports in the screen and
   regenerate `star_exports.py`; add a regression test using the verified reproducer. This
   is a regression introduced by this branch — the feature does not exist on `main`.

## Systemic pattern (one root cause, not one ticket)

The escape is the intersection of two design assumptions that were each individually
reasonable and became false together:

- **The star-export screen trusts name + provenance, not capability.** The generator already
  concedes this (it hand-excludes `sage.libs.ecl` because `EclObject` evaluates Lisp). The
  module-object hole is the same shape: a value the screen approves whose *behaviour* it
  never examined. Keep `CANDIDATE_MODULES` minimal and treat each addition as a manual
  capability review.
- **The validator treats `X.os` under a non-allowlisted root as a benign method access.**
  True for a mathematical object, false for a module object. Any feature that lets caller
  code bind a module object to a name reopens the whole `os`/`sys`/`subprocess` surface. The
  attribute rule should refuse a forbidden parent as terminal whenever the root is a
  caller-bound import alias.

## Coverage and confidence

**High confidence, focused scope.** I read the entire branch diff, ran the pure-Python suite
(886 passed) and the Sage-backed security/integration/coverage suites (426 passed), and
executed my own adversarial reproducers end-to-end through the real worker. The other four
changes — the monitoring redaction, `attrcall` literal screening, the token-screen rework,
and `inject_shorthands` — were each probed and cleared. The residual, un-eliminated risk is
the capability-blindness of the star-export screen: the fix closes the confirmed
module-object class, but the curated list still rests on human judgement for every callable
it admits. No source files were modified during this review (`git status` clean).
