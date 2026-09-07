# Outcome benchmark

Does the model get more mathematics right when it can run Sage, versus
reasoning alone? Two arms over the fixed case set in `benchmarks/cases.json`,
every answer scored for *mathematical equivalence* in the SageMath 10.9
container (not string-matched). Produced by
`benchmarks/outcome_benchmark.workflow.js`.

- Generated: 2026-09-07
- Cases: 24 across tiers: arithmetic, competition, advanced, compute-heavy, infeasible
- Subject model (under test): `haiku`; scoring judge: `sonnet`
- This is as much a measurement of the subject model as of the server; a
  stronger model closes the gap on its own. Never CI-gated.

## Headline

| Arm | Correct | Wrong-confident | Refused | Sage calls |
| --- | ---: | ---: | ---: | ---: |
| Reasoning only | 17/24 (71%) | 1 | 6 | 0 |
| With Sage compute | 24/24 (100%) | 0 | 0 | 37 |

**Delta: +7** answers correct with Sage compute (17/24 (71%) → 24/24 (100%)).

## By tier

| Tier | Reasoning only | With Sage | Delta |
| --- | ---: | ---: | ---: |
| arithmetic | 4/4 (100%) | 4/4 (100%) | 0 |
| competition | 5/5 (100%) | 5/5 (100%) | 0 |
| advanced | 5/5 (100%) | 5/5 (100%) | 0 |
| compute-heavy | 3/5 (60%) | 5/5 (100%) | +2 |
| infeasible | 0/5 (0%) | 5/5 (100%) | +5 |

## Per problem

A ✗ in *Reasoning only* that is ✓ *With Sage* is the value the server adds;
a wrong-confident cell (⚠) is the failure mode `verify_claim` exists for.

| ID | Tier | Reasoning only | With Sage |
| --- | --- | :---: | :---: |
| A1 | arithmetic | ✓ | ✓ |
| A2 | arithmetic | ✓ | ✓ |
| A3 | arithmetic | ✓ | ✓ |
| A4 | arithmetic | ✓ | ✓ |
| B1 | competition | ✓ | ✓ |
| B2 | competition | ✓ | ✓ |
| B3 | competition | ✓ | ✓ |
| B4 | competition | ✓ | ✓ |
| B5 | competition | ✓ | ✓ |
| C1 | advanced | ✓ | ✓ |
| C2 | advanced | ✓ | ✓ |
| C3 | advanced | ✓ | ✓ |
| C4 | advanced | ✓ | ✓ |
| C5 | advanced | ✓ | ✓ |
| D1 | compute-heavy | ✓ | ✓ |
| D2 | compute-heavy | ✓ | ✓ |
| D3 | compute-heavy | ⚠ wrong | ✓ |
| D4 | compute-heavy | — (refused) | ✓ |
| D5 | compute-heavy | ✓ | ✓ |
| E1 | infeasible | — (refused) | ✓ |
| E2 | infeasible | — (refused) | ✓ |
| E3 | infeasible | — (refused) | ✓ |
| E4 | infeasible | — (refused) | ✓ |
| E5 | infeasible | — (refused) | ✓ |

## Method and honest limits

- The two arms are the **same model**; one is told to reason unaided, the
  other to compute and verify with Sage. The delta is the lift from having
  the CAS in the loop.
- The compute arm runs Sage **directly** (`docker exec ... sage -c`), so it
  bypasses this server -- its tool selection, input validation, handles and
  verifier. So the result supports *Sage computation helps this model on these
  cases*, not yet *this server's design improves outcomes*. Measuring through
  the MCP interface with enforced tool permissions is the intended next step.
- *Reasoning only* is **prompt-enforced**: the agent is told not to execute
  anything and self-reports zero tool calls. It is not hard tool-gated. The
  rigorous three-arm version (no-tools / `evaluate_sage`-only / full
  catalogue, with real gating) is a planned `tests/cli_integration` harness --
  a follow-up under the CLI nightlies, not something that runs today.
- Answers are scored by an **independent** Sage-backed step, so a plausible
  wrong answer is caught, not accepted on its wording.
- Small, fixed, seeded case set: this is a directional signal a run can
  reproduce, not a leaderboard number. Grow `benchmarks/cases.json` to
  tighten it.
