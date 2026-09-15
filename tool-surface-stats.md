# Tool-surface measurement

Does the 40-tool catalogue earn its keep? The same tool-forcing cases
(`tests/cli_integration/extended_cases.py`, answers impractical without a
CAS) run through real CLI clients in three arms: no MCP server registered,
the server narrowed on the wire to `evaluate_sage` plus the session and
diagnostic tools (the proxy hides everything else from `tools/list` and
refuses it on `tools/call`), and the full catalogue. Produced by
`make tool-surface`; never CI-gated -- it measures the clients as much as
the server.

- Generated: 2026-09-15
- Cases: 23 across domains: coding_theory, combinatorics, elliptic_curves, linear_algebra, number_theory, numerics, open_problems, physics, session
- Clients: claude, codex, gemini
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
| No server (reasoning only) | claude | **21/21 (100%)** | 0 | 0 | 0 | 0 | 0 | 9 |
| No server (reasoning only) | codex | **21/21 (100%)** | 0 | 0 | 0 | 0 | 0 | 14 |
| No server (reasoning only) | gemini | **18/21 (85%)** | 3 | 0 | 0 | 0 | 0 | 41 |
| No server (reasoning only) | **all** | **60/63 (95%)** | 3 | 0 | 0 | 0 | 0 | 19 |
| Core tools (evaluate_sage + session) | claude | **21/23 (91%)** | 0 | 0 | 0 | 2 | 30 | 20 |
| Core tools (evaluate_sage + session) | codex | **17/23 (73%)** | 0 | 0 | 5 | 1 | 20 | 29 |
| Core tools (evaluate_sage + session) | gemini | **15/23 (65%)** | 0 | 0 | 0 | 8 | 61 | 22 |
| Core tools (evaluate_sage + session) | **all** | **53/69 (76%)** | 0 | 0 | 5 | 11 | 111 | 23 |
| Full catalogue (40 tools) | claude | **22/23 (95%)** | 0 | 0 | 0 | 1 | 30 | 21 |
| Full catalogue (40 tools) | codex | **0/23 (0%)** | 0 | 0 | 0 | 23 | 0 | 10 |
| Full catalogue (40 tools) | gemini | **19/23 (82%)** | 0 | 0 | 0 | 4 | 53 | 24 |
| Full catalogue (40 tools) | **all** | **41/69 (59%)** | 0 | 0 | 0 | 28 | 83 | 18 |

Arms with provider cut-offs (⛔): full/codex. They stay in the table above but are **excluded from every comparison below**, which only counts client-cases both arms actually measured.

**Full catalogue minus core tools: +5 correct** over 46 client-cases measured in both (36/46 (78%) → 41/46 (89%)).
**Core tools (evaluate_sage + session) minus no server: -11 correct** over 63 client-cases measured in both (60/63 (95%) → 49/63 (77%)). In the server arms a correct answer only counts with a successful qualifying tool call, so this delta measures integration friction as much as mathematics.
**Full catalogue (40 tools) minus no server: -2 correct** over 42 client-cases measured in both (39/42 (92%) → 37/42 (88%)). In the server arms a correct answer only counts with a successful qualifying tool call, so this delta measures integration friction as much as mathematics.
The no-server arm was wrong-confident **3** times and declined 0 times in 63 client-cases.

## By domain (all clients)

| Domain | No server (reasoning only) | Core tools (evaluate_sage + session) | Full catalogue (40 tools) |
| --- | ---: | ---: | ---: |
| coding_theory | 3/3 (100%) | 3/3 (100%) | 2/3 (66%) |
| combinatorics | 5/6 (83%) | 5/6 (83%) | 4/6 (66%) |
| elliptic_curves | 3/3 (100%) | 3/3 (100%) | 2/3 (66%) |
| linear_algebra | 3/3 (100%) | 3/3 (100%) | 2/3 (66%) |
| number_theory | 4/6 (66%) | 6/6 (100%) | 4/6 (66%) |
| numerics | 12/12 (100%) | 8/12 (66%) | 5/12 (41%) |
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

