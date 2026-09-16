# Tool-surface measurement

Does the 40-tool catalogue earn its keep? The same tool-forcing cases
(`tests/cli_integration/extended_cases.py`, answers impractical without a
CAS) run through real CLI clients in three arms: no MCP server registered,
the server narrowed on the wire to `evaluate_sage` plus the session and
diagnostic tools (the proxy hides everything else from `tools/list` and
refuses it on `tools/call`), and the full catalogue. Produced by
`make tool-surface`; never CI-gated -- it measures the clients as much as
the server.

- Generated: 2026-09-16
- Cases: 37 across domains: coding_theory, combinatorics, elliptic_curves, group_theory, linear_algebra, number_theory, numerics, open_problems, physics, session
- Clients: claude, codex, gemini
- Two tiers. The **standard** tier (23 cases) was written in 2025 to be
  impractical without a CAS and is kept as the historical baseline; the **hard**
  tier (14 cases) was added 2026-09-16 because frontier clients now answer the
  standard one from recall. Only the hard tier separates the arms on
  correctness. The hard-tier numbers below are Claude only — Codex had no
  credits and Gemini was not re-run — so read them as one client, not three.
- Statuses: ✓ correct · ⚠ wrong-confident · ∅ declined · ○ answered without a
  qualifying tool call · ✗ server error · ⏱ timeout · ⛔ cut off by the
  provider (spend/usage limit), which is counted under *Other*, not against
  the arm
- The no-server arm is enforced or observed per client: Claude Code runs with
  `--tools ""` (no built-in tools at all); Gemini runs without `--yolo` and
  its own statistics report every tool it attempted; Codex cannot be denied a
  shell, so its `--json` event stream is scanned for `command_execution`. Any
  such use shows up in the *Tool calls* column of that arm, which should read 0.

## Headline

| Arm | Client | Correct | Wrong-confident | Declined | No tool call | Other | Tool calls | Median s |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| No server (reasoning only) | claude | **25/35 (71%)** | 9 | 0 | 0 | 1 | 0 | 10 |
| No server (reasoning only) | codex | **21/21 (100%)** | 0 | 0 | 0 | 0 | 0 | 14 |
| No server (reasoning only) | gemini | **18/21 (85%)** | 3 | 0 | 0 | 0 | 0 | 41 |
| No server (reasoning only) | **all** | **64/77 (83%)** | 12 | 0 | 0 | 1 | 0 | 19 |
| Core tools (evaluate_sage + session) | claude | **35/37 (94%)** | 0 | 0 | 0 | 2 | 44 | 19 |
| Core tools (evaluate_sage + session) | codex | **17/23 (73%)** | 0 | 0 | 5 | 1 | 20 | 29 |
| Core tools (evaluate_sage + session) | gemini | **15/23 (65%)** | 0 | 0 | 0 | 8 | 61 | 22 |
| Core tools (evaluate_sage + session) | **all** | **67/83 (80%)** | 0 | 0 | 5 | 11 | 125 | 21 |
| Full catalogue (40 tools) | claude | **36/37 (97%)** | 0 | 0 | 0 | 1 | 44 | 18 |
| Full catalogue (40 tools) | codex | **0/23 (0%)** | 0 | 0 | 0 | 23 | 0 | 10 |
| Full catalogue (40 tools) | gemini | **19/23 (82%)** | 0 | 0 | 0 | 4 | 53 | 24 |
| Full catalogue (40 tools) | **all** | **55/83 (66%)** | 0 | 0 | 0 | 28 | 97 | 15 |

Arms with provider cut-offs (⛔): full/codex. They stay in the table above but are **excluded from every comparison below**, which only counts client-cases both arms actually measured.

**Full catalogue minus core tools: +5 correct** over 60 client-cases measured in both (50/60 (83%) → 55/60 (91%)).
**Core tools (evaluate_sage + session) minus no server: -1 correct** over 77 client-cases measured in both (64/77 (83%) → 63/77 (81%)). In the server arms a correct answer only counts with a successful qualifying tool call, so this delta measures integration friction as much as mathematics.
**Full catalogue (40 tools) minus no server: +8 correct** over 56 client-cases measured in both (43/56 (76%) → 51/56 (91%)). In the server arms a correct answer only counts with a successful qualifying tool call, so this delta measures integration friction as much as mathematics.
The no-server arm was wrong-confident **12** times and declined 0 times in 77 client-cases.

## By tier (all clients)

The standard tier was written in 2025 to be impractical without a CAS; the hard tier exists because frontier clients now answer it from recall. A tier that separates the arms is one where the no-server column is low.

| Tier | No server (reasoning only) | Core tools (evaluate_sage + session) | Full catalogue (40 tools) |
| --- | ---: | ---: | ---: |
| hard | 4/14 (28%) | 14/14 (100%) | 14/14 (100%) |
| standard | 60/63 (95%) | 53/69 (76%) | 41/69 (59%) |

## By domain (all clients)

| Domain | No server (reasoning only) | Core tools (evaluate_sage + session) | Full catalogue (40 tools) |
| --- | ---: | ---: | ---: |
| coding_theory | 3/3 (100%) | 3/3 (100%) | 2/3 (66%) |
| combinatorics | 5/7 (71%) | 6/7 (85%) | 5/7 (71%) |
| elliptic_curves | 4/5 (80%) | 5/5 (100%) | 4/5 (80%) |
| group_theory | 1/1 (100%) | 1/1 (100%) | 1/1 (100%) |
| linear_algebra | 4/5 (80%) | 5/5 (100%) | 4/5 (80%) |
| number_theory | 5/13 (38%) | 13/13 (100%) | 11/13 (84%) |
| numerics | 12/13 (92%) | 9/13 (69%) | 6/13 (46%) |
| open_problems | 15/15 (100%) | 15/15 (100%) | 10/15 (66%) |
| physics | 15/15 (100%) | 6/15 (40%) | 8/15 (53%) |
| session | n/a | 4/6 (66%) | 4/6 (66%) |

## Per case

One cell per (arm, client). A ✓ in *core* next to a ✓ in *full* is a case the
helpers did not decide; a ○/⚠ in *core* against a ✓ in *full* is the value
a dedicated tool added.

| Case | Domain | none/claude | none/codex | none/gemini | core/claude | core/codex | core/gemini | full/claude | full/codex | full/gemini |
| --- | --- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `ext-coding-hamming` | coding_theory | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ⛔ | ✓ |
| `ext-comb-bell` | combinatorics | ✓ | ✓ | ⚠ | ✓ | ✓ | ✓ | ✓ | ⛔ | ✓ |
| `ext-comb-partitions` | combinatorics | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ | ✓ | ⛔ | ✓ |
| `ext-ec-conductor` | elliptic_curves | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ⛔ | ✓ |
| `ext-la-determinant` | linear_algebra | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ⛔ | ✓ |
| `ext-nt-factorial-mod` | number_theory | ✓ | ✓ | ⚠ | ✓ | ✓ | ✓ | ✓ | ⛔ | ✓ |
| `ext-nt-next-prime` | number_theory | ✓ | ✓ | ⚠ | ✓ | ✓ | ✓ | ✓ | ⛔ | ✓ |
| `ext-num-basel-truncated` | numerics | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ⛔ | ✗ |
| `ext-num-hilbert-exact` | numerics | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ | ✓ | ⛔ | ✗ |
| `ext-num-kepler` | numerics | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ | ✓ | ⛔ | ✓ |
| `ext-num-planck-integral` | numerics | ✓ | ✓ | ✓ | ✗ | ✓ | ✗ | ✗ | ⛔ | ✓ |
| `ext-open-amicable` | open_problems | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ⛔ | ✓ |
| `ext-open-bsd-rank` | open_problems | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ⛔ | ✓ |
| `ext-open-collatz-record` | open_problems | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ⛔ | ✓ |
| `ext-open-prime-gap` | open_problems | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ⛔ | ✓ |
| `ext-open-twin-primes` | open_problems | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ⛔ | ✓ |
| `ext-phys-anharmonic` | physics | ✓ | ✓ | ✓ | ✓ | ○ | ✗ | ✓ | ⛔ | ✓ |
| `ext-phys-bessel-zero` | physics | ✓ | ✓ | ✓ | ✗ | ○ | ✗ | ✓ | ⛔ | ✗ |
| `ext-phys-mercury` | physics | ✓ | ✓ | ✓ | ✓ | ○ | ✗ | ✓ | ⛔ | ✓ |
| `ext-phys-schrodinger-fd` | physics | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ⛔ | ✗ |
| `ext-phys-wien-peak` | physics | ✓ | ✓ | ✓ | ✓ | ✗ | ✗ | ✓ | ⛔ | ✓ |
| `ext-session-named` | session |  |  |  | ✓ | ○ | ✓ | ✓ | ⛔ | ✓ |
| `ext-session-state` | session |  |  |  | ✓ | ○ | ✓ | ✓ | ⛔ | ✓ |
| `hard-comb-partitions` | combinatorics | ⚠ |  |  | ✓ |  |  | ✓ |  |  |
| `hard-ec-conductor` | elliptic_curves | ✓ |  |  | ✓ |  |  | ✓ |  |  |
| `hard-ec-order` | elliptic_curves | ⚠ |  |  | ✓ |  |  | ✓ |  |  |
| `hard-group-order` | group_theory | ✓ |  |  | ✓ |  |  | ✓ |  |  |
| `hard-la-determinant` | linear_algebra | ⚠ |  |  | ✓ |  |  | ✓ |  |  |
| `hard-la-hilbert` | linear_algebra | ✓ |  |  | ✓ |  |  | ✓ |  |  |
| `hard-nf-class-number` | number_theory | ⚠ |  |  | ✓ |  |  | ✓ |  |  |
| `hard-nt-bernoulli` | number_theory | ⚠ |  |  | ✓ |  |  | ✓ |  |  |
| `hard-nt-discrete-log` | number_theory | ⚠ |  |  | ✓ |  |  | ✓ |  |  |
| `hard-nt-fibonacci` | number_theory | ⚠ |  |  | ✓ |  |  | ✓ |  |  |
| `hard-nt-nth-prime` | number_theory | ⚠ |  |  | ✓ |  |  | ✓ |  |  |
| `hard-nt-semiprime` | number_theory | ⚠ |  |  | ✓ |  |  | ✓ |  |  |
| `hard-nt-sigma` | number_theory | ✓ |  |  | ✓ |  |  | ✓ |  |  |
| `hard-num-convergent` | numerics | ⏱ |  |  | ✓ |  |  | ✓ |  |  |

