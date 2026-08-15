# Roadmap

This document tracks planned improvements to the SageMath MCP server, organized by priority and effort. The goal is to strengthen the server's position as a universal mathematics MCP server that enables LLMs to perform any symbolic or discrete mathematical operation.

**Current state (v0.5.0):** 37 MCP tools (31 Sage-backed, 6 infrastructure) covering calculus, algebra, linear algebra, ODEs, number theory, combinatorics, graph theory, group theory, elliptic curves, coding theory, boolean algebra, polynomial rings, geometry, probability, vector calculus, statistics, 2D/3D plotting, numeric root-finding, and incremental streaming. As of 2026-08-15 the suites pass 667 unit tests at 100% statement and branch coverage, 764 against a real SageMath 10.9 runtime, and 27/27 of the extended CLI cases across Claude, Gemini and Codex. Counts are a snapshot; the coverage floor is the part CI enforces.

Integration coverage now includes every tool exercised against the examples in its own
documentation, and a syntax matrix over the input spellings each tool must accept. Both
run in CI, which had previously reported the integration job as passing while running
nothing at all.

**Caller code moved to deny-by-default in this window.** A name is refused unless
the generated allowlist offers it or the caller's own code bound it. That closed
a run of bypasses which shared one shape — a name nobody had thought to forbid —
and it changes what callers may do: no imports, no external CAS interfaces, no
`show`/`latex`/`html`, and `x, y, z, t` predefined where Sage predefines only
`x`. See `SECURITY.md` for the model and `CHANGELOG.md` for the breaking
details. It also created a new risk in the opposite direction — refusing
legitimate mathematics — which `tests/test_math_coverage.py` exists to catch.

---

## Open work

The live queue is [TODO.md](TODO.md); this section says only what shape it is in.

The 2026-08-13 review and the security rounds that followed are all recorded in
[REVIEW_ACTIONS.md](REVIEW_ACTIONS.md) — 34 items, each with its reproduction,
fix and regression test. Every one is closed except the account-side half of
item 7: the Smithery and Glama submissions need repository-owner access.

- [ ] Smithery: connect the repository at smithery.ai/new (reads the committed `smithery.yaml`) — needs owner access
- [ ] Glama: claim the auto-indexed listing — needs owner access
- [ ] Cut 0.5.1. Security fixes and a user-visible behaviour change are unreleased while 0.5.0 is the live version.

## Letting more legitimate mathematics through (measured 2026-08-15)

Running SageMath's own doctests through the validator — 432,878 examples,
`tests/test_sage_doctest_corpus.py` — accepts 98.59% of what is in scope. The
5,266 refusals were categorised by whether the security justification holds
(REVIEW_ACTIONS.md items 45 and 46), and everything that failed that test has
been fixed.

What remains is that breakdown read the other way round: not *is this refusal
justified* but *what would it take for this mathematics to work?* Five items
came out of it, each with the count that motivates it and each reproduced
against SageMath 10.9 — `nonlocal` and `global`, room for a pasted matrix,
run-time names from `inject_variables()`, refusal messages that name the native
equivalent, and executing the corpus rather than only validating it. They are in
[TODO.md](TODO.md) with the detail.

Deliberately *not* among them: the external CAS interfaces (2,153 refusals),
whose mathematics is reachable in-process and tested to be; the 538 uses of
Sage's internal spellings for mathematics that has a public one; and the
evaluation primitives, which stay refused whatever the namespace holds. Those
are boundaries, not gaps.

## Competitive position (surveyed 2026-08-13)

### The SageMath MCP field

| Project | Stars | Language | Tools | Session model | Last push |
|---------|------:|----------|------:|---------------|-----------|
| **this project** | **12** | Python | **37** | Subprocess per client, named workspaces, interrupt | active |
| [GaloisHLee/mcp-server-sagemath](https://github.com/GaloisHLee/mcp-server-sagemath) | 11 | TypeScript | 3 | Explicitly stateless | 2025-12 |
| [sanshanjianke/scicompute-mcp](https://github.com/sanshanjianke/scicompute-mcp) | 4 | Python | multi-backend | Persistent | 2026-04 |
| [justice8096/sagemath-mcp-server](https://github.com/justice8096/sagemath-mcp-server) | 1 | — | 10 | — | 2026-05 |
| [szeider/mcp-sage](https://github.com/szeider/mcp-sage) | 1 | Python | 5 | Jupyter kernel, named multi-session | 2026-08 |

The adjacent market is roughly five times larger and is where attention actually goes:
[mcp-wolframalpha](https://github.com/akalaric/mcp-wolframalpha) (84),
[sympy-mcp](https://github.com/sdiehl/sympy-mcp) (79),
[wolframalpha-llm-mcp](https://github.com/Garoth/wolframalpha-llm-mcp) (55),
[mathematica-mcp](https://github.com/AbhiRawat4841/mathematica-mcp) (44),
[fermat-mcp](https://github.com/abhiphile/fermat-mcp) (20).

### Where this project leads

- **Security posture under repair.** The configurable AST validator is useful
  defence in depth against accidental misuse, but review items 1-3 show that it
  is not currently an adversarial sandbox. Do not treat sandboxing as a competitive
  differentiator until the bypass tests and container hardening are complete.
- **Tool surface.** 37 against 3, 5 and 10 for the SageMath peers.
- **Verification.** 496 unit and 575 real-runtime tests (2026-08-14); peer test coverage is largely
  invisible.
- **Documentation.** 1218 README lines against 481, 284, 187 and 89.
- **Operations.** Helm chart, Cosign-signed images, monitoring resource, health endpoint.
  No peer ships this.
- **Distribution.** On PyPI with signed releases. Notably sympy-mcp, the most-starred
  symbolic server, is not on PyPI at all.

### Where this project is behind

1. **Worker transport.** szeider/mcp-sage drives Sage through the Jupyter kernel
   protocol rather than raw subprocess management, citing "reliable prompt detection,
   clean separation of stdout / stderr / return values, native interrupt support, and
   robust multi-line input". Those are precisely the problems this project solved by
   hand, and a framing bug in that hand-rolled layer surfaced as recently as v0.4.0.
2. ~~**Interrupt versus restart.**~~ Closed by `interrupt_sage_session`.
3. ~~**One session per client.**~~ Closed by `start` / `list` / `stop_sage_session`.
4. **Install friction.** `uvx mcp-sage` runs with no install via PEP 723 inline
   dependencies. This project needs a local SageMath or a ~3 GB image.
5. **Academic anchor.** Their server is cited in a NeSy 2026 paper. This project has no
   equivalent reference.

---

## Explicitly not planned

**More tools.** At 37 the surface already exceeds every peer. The gaps that matter are
distribution and session ergonomics, not coverage.

---

## Design notes worth remembering

Kept because each one cost a debugging session and none is obvious from the code.

- **`interrupt` deliberately does not take the session lock.** The evaluation
  being interrupted holds it, so waiting would deadlock until the computation
  everyone is trying to stop finishes on its own.
- **The worker's `except Exception` did not catch `KeyboardInterrupt`**, which is
  a `BaseException`. Without handling it explicitly the worker exited and took
  the namespace with it — defeating the point of interrupting rather than
  cancelling.
- **FastMCP's `mount`/`import_server` prefix tool names.** Composing the `tools/`
  package that way would rename every tool a client has configured, which is why
  the modules decorate against a shared `mcp` object instead.
- **Jupyter kernel transport was prototyped and rejected** (2026-08-13): stock
  ipykernel executes code the AST policy blocks, so it would need a permanent
  custom kernel, and startup cost 1010 ms against 463 ms. The measurements and
  the debugger finding are in
  [`prototypes/jupyter_transport/FINDINGS.md`](prototypes/jupyter_transport/FINDINGS.md).

## Niche domains — no further dedicated tools planned

These are reachable through `evaluate_sage`, which documents them in its own
description. Dedicated tools are not planned: the problems are too varied for a
single interface, or Sage is not the right instrument.

| Domain | Access via `evaluate_sage` | Why no dedicated tool |
|--------|---------------------------|----------------------|
| Tensor operations | Sage tensor module with index notation | Very specialized |
| Category theory | Limited Sage support | Out of Sage's scope |
| Unit conversion | External `units` package | Domain-specific |
| Curve fitting | Limited in Sage (scipy is better) | Wrong tool for the job |

Five domains that were once on this list — graph theory, group theory, elliptic
curves, coding theory and boolean algebra — did get dedicated tools
(`graph_operation`, `group_operation`, `elliptic_curve_operation`,
`coding_theory_operation`, `boolean_algebra_operation`).

## Completed work

Not listed here. Every shipped change is in [CHANGELOG.md](CHANGELOG.md) with
its release, and the reasoning behind the security work is in
[REVIEW_ACTIONS.md](REVIEW_ACTIONS.md). This file previously carried four
sections of ticked boxes that duplicated both and went stale — one of them still
listed five domains as having no dedicated tool when all five had shipped.
