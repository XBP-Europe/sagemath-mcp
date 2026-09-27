# Mutation-testing statistics

The mutation score of the AST security policy (`security.py`, `policy.py`,
`refusals.py`, `imports.py`). cosmic-ray applies each deliberate weakening
and runs the security suite; a
mutant is *killed* when a test fails, *survives* when they all pass. A high
score means the tests exercise the policy's logic, not just its lines. Never
CI-gated; run with `make mutation`.

- Generated: 2026-09-27 (after the 2026-09 refactor)
- Scope: `security.py`, `policy.py`, `refusals.py`, `imports.py` (allowlist.py
  is generated data, guarded by the Sage-agreement integration test instead)

| Metric | Value |
| --- | ---: |
| Mutants generated | 784 |
| Mutants run | 784 |
| Killed | 500 |
| Surviving | 284 |
| **Mutation score** | **63.78%** |
| Survival rate | 36.22% |

## Surviving mutants, by operator

Survivors are either genuine test gaps or *equivalent* mutants -- changes
that cannot alter behaviour. The largest class here is
`ReplaceBinaryOperator` on the `|` of an `X | None` type hint: under
`from __future__ import annotations` that annotation is a string that is
never evaluated, so no test can kill it.

| Operator | Surviving |
| --- | ---: |
| `ReplaceBinaryOperator_BitOr` | 220 |
| `NumberReplacer` | 28 |
| `ReplaceComparisonOperator` | 15 |
| `ReplaceBinaryOperator_Mul` | 4 |
| `AddNot` | 3 |
| `ReplaceContinueWithBreak` | 3 |
| `ReplaceTrueWithFalse` | 2 |
| `ExceptionReplacer` | 2 |
| `ReplaceFalseWithTrue` | 2 |
| `ReplaceAndWithOr` | 2 |
| `ReplaceOrWithAnd` | 2 |
| `ReplaceBinaryOperator_Sub` | 1 |

Excluding the 220 equivalent type-annotation mutants, the
effective mutation score is **88.65%** (500/564).

The remaining survivors are a mix: some are still near-equivalent (a
`== "s"` turned to `is "s"` compares interned strings the same way; a
`NumberReplacer` on a non-behavioural constant), and some are genuine
test gaps -- boolean-logic and boundary-comparison flips on branches the
suite reaches but does not pin from both sides. The genuine ones are the
actionable output; closing them is tracked in TODO.

Inspect any survivor with `cr-report mutation/security.sqlite --show-output`.
