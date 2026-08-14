# Roadmap

This document tracks planned improvements to the SageMath MCP server, organized by priority and effort. The goal is to strengthen the server's position as a universal mathematics MCP server that enables LLMs to perform any symbolic or discrete mathematical operation.

**Current state (v0.5.0):** 37 MCP tools (31 Sage-backed, 6 infrastructure) covering calculus, algebra, linear algebra, ODEs, number theory, combinatorics, graph theory, group theory, elliptic curves, coding theory, boolean algebra, polynomial rings, geometry, probability, vector calculus, statistics, 2D/3D plotting, numeric root-finding, and incremental streaming. As of 2026-08-14 the suites pass 496 unit tests at 100% statement and branch coverage, 575 against a real SageMath 10.9 runtime, and 27/27 of the extended CLI cases across Claude, Gemini and Codex. Counts are a snapshot; the coverage floor is the part CI enforces.

Integration coverage now includes every tool exercised against the examples in its own
documentation, and a syntax matrix over the input spellings each tool must accept. Both
run in CI, which had previously reported the integration job as passing while running
nothing at all.

---

## Open review actions

A review on 2026-08-13 found three release-blocking issues: the AST validator is
bypassable, the public security claims overstate the controls, and FastMCP's
default response cache breaks state and isolation across clients. It also found
correctness gaps in named-workspace cancellation, exact large integers, streaming,
persistence, workspace routing and version synchronization. All are tracked with
evidence, a suggested fix and a verification step in
[REVIEW_ACTIONS.md](REVIEW_ACTIONS.md).

**Status: fifteen of seventeen closed.** The validator took three rounds — direct
spellings, then aliases of forbidden functions (`f = open`), then aliases of
forbidden modules (`m = os`) — because each fix was checked only against the
payloads that motivated it. Item 4 (splitting `server.py`) is now done: 2327 lines became 162, with the
tools in a `tools/` package and the contract held byte-identical by a snapshot
test. Item 18, found later by an external review, was a genuine remote-execution
path through four unvalidated tool parameters and is closed. What remains is the
account-side half of item 7 — the Smithery and Glama submissions, which need
repository-owner access — and coverage on the newly isolated helpers.

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

## Planned — Tier 1: Distribution (done 2026-08-13)

Cheap, and the gap was embarrassing: the repository had no topics, no homepage, and a
typo in the one sentence GitHub indexes for search.

- [x] Fix the repository description, add a homepage, add 14 discovery topics
- [x] Add `server.json` and the `mcp-name` ownership marker for the official MCP registry
- [x] Automate registry publication from the release workflow using OIDC
  - **Not yet listed.** The job was added after the v0.4.0 tag, so it has never
    run; the registry returns no server for `io.github.XBP-Europe/sagemath-mcp`.
    The next tagged release is its first execution. A README badge claiming
    publication was removed for exactly this reason -- check the registry, not
    the workflow, before reinstating it.
- [ ] List on Smithery and Glama, as fermat-mcp does

At the time of the survey the only SageMath server in the official registry was
`io.github.justice8096/sagemath-mcp-server`, a one-star project with 10 tools. Registry
publication requires the ownership marker to be present in the *published* PyPI
description, so it takes effect from the first release after this change.

## Tier 2: Session ergonomics (shipped; corrective work open)

The two capabilities where a one-star project was genuinely ahead. Neither needed an
architectural change.

- [x] **Interrupt without restart.** `interrupt_sage_session` signals the worker, which
      turns the resulting KeyboardInterrupt into an `Interrupted` response and keeps its
      namespace. `cancel_sage_session` remains the escape hatch for a wedged worker.
- [x] **Named multi-sessions.** `start_sage_session`, `list_sage_sessions` and
      `stop_sage_session`, with workspace selection on raw evaluation and session
      controls. The default workspace keys on the bare scope.
- [x] **Correct named-session routing.** Cancellation must target the selected
      workspace, response ids must be verified, and specialized tools must expose
      the same `session` selector (review items 11 and 16).

Two details worth remembering. `interrupt` deliberately does not take the session lock:
the evaluation being interrupted holds it, so waiting would deadlock until the
computation everyone is trying to stop finishes on its own. And the worker's
`except Exception` did not catch `KeyboardInterrupt`, which is a `BaseException` — without
handling it explicitly the worker exited and took the namespace with it, defeating the
purpose.

## Tier 3: Jupyter kernel transport — prototyped, not adopted (2026-08-13)

Prototyped under `prototypes/jupyter_transport/`; see its `FINDINGS.md`. **Recommendation
is not to adopt now**, on evidence rather than taste.

The motivating benefits were already banked by cheaper means. Interrupt with state
preservation shipped in Tier 2 using plain SIGINT. The framing failure was fixed by
sizing the stream limit to 8 MiB. Multi-line input already worked. Of the four advantages
szeider/mcp-sage cites, only "ZMQ framing has no arbitrary ceiling" is still outstanding,
against our large one.

What the prototype established:

- A Jupyter kernel listens on five local TCP ports. A second client holding only the
  connection file executed `import os; os.getuid()` against a stock kernel — so
  client-side validation would be **advisory only**.
- **IPython's `ast_transformers` cannot serve as the gate.** A transformer that raises is
  not a veto: IPython warns, runs the original code anyway, and unregisters the
  transformer.
- Keeping the sandbox therefore requires subclassing the kernel and validating in
  `do_execute`. That works and closes the bypass, but means owning a kernel subclass and
  tracking ipykernel internals indefinitely.
- Startup goes from 463 ms to 1010 ms, on a path users wait for.
- The threat model worsens: today a worker has no listening socket, so a same-user
  process cannot reach another session. With kernels it can, even if only with validated
  code.

Revisit for **capability**, not robustness: kernels emit `display_data` with `image/png`
and `text/latex` natively, which is exactly what the plot tools hand-roll today, and
`plot3d_expression` had to sample a surface by hand because `Graphics3d` has no
in-memory export. Notebook interoperability and multi-language kernels are the other
reasons that would justify the move.

## Explicitly not planned

**More tools.** At 37 the surface already exceeds every peer. The gaps that matter are
distribution and session ergonomics, not coverage.

---

## Completed — Phase 1 (High-Value Helper Tools)

- [x] **`symbolic_sum`** — symbolic summation and products with sum/product toggle
- [x] **`combinatorics_operation`** — binomial, permutations, combinations, partitions, factorial, catalan, fibonacci, bell
- [x] **`plot3d_expression`** — 3D surface plots as base64-encoded PNG

## Completed — Phase 2 (Medium-Value Helper Tools)

- [x] **`distribution_operation`** — probability distributions (normal, exponential, poisson, chi_squared, student_t, uniform, beta, gamma) with pdf/cdf/quantile/mean/variance/sample operations
- [x] **`find_root`** — numeric root-finding in an interval (complements symbolic `solve_equation`)
- [x] **`plot_multi_expression`** — overlay multiple functions in a single 2D plot
- [x] **`vector_calculus_operation`** — gradient, divergence, curl, laplacian

## Completed — Phase 3 (Enrichment)

- [x] **Enriched `evaluate_sage` description** — 14 domain examples (was 8): added symbolic sums, Laplace/inverse Laplace transforms, modular arithmetic, vector calculus, numeric root finding, recurrence relations
- [x] **HTTP `/health` endpoint** — returns `{"status": "ok", "version": "...", "active_sessions": N}` for Kubernetes liveness/readiness probes (Starlette route on HTTP transports)
- [x] **`evaluate_sage_streaming`** — shipped first as a facade that replayed captured stdout after completion; now streams each line as it is produced (see the entry below).
- [x] **True incremental streaming** — the worker emits a stdout event per completed line while execution is running, and the session dispatches them as they arrive (review item 13).
- [x] **Disk-backed session persistence foundation** — code journals are saved on explicit stop/server shutdown and replayed on restore. Controlled by `SAGEMATH_MCP_PERSIST_SESSIONS` and `SAGEMATH_MCP_PERSIST_DIR`.
- [x] **Complete persistence lifecycle and isolation** — journals are saved during idle culling, filenames carry a digest of the full session id in a versioned namespace, writes are atomic, and journals from the previous naming schemes are still restored (review items 14 and 15).

## Phase 4 — Niche Domains (Not Planned)

These domains are fully accessible via `evaluate_sage` and documented in its tool description. Dedicated tools are not planned because the domains require specialized knowledge to use effectively, and the `evaluate_sage` escape hatch with domain-specific examples already covers them.

| Domain | Access via `evaluate_sage` | Why no dedicated tool |
|--------|---------------------------|----------------------|
| Graph theory | `graphs.PetersenGraph(); G.chromatic_number()` | Problems are too varied for a single tool interface |
| Group theory | `SymmetricGroup(5).order()` | Requires domain expertise |
| Elliptic curves | `EllipticCurve([0,0,1,-1,0]).rank()` | Highly specialized |
| Coding theory | `codes.HammingCode(GF(2), 3).minimum_distance()` | Niche |
| Tensor operations | Sage tensor module with index notation | Very specialized |
| Boolean algebra | `BooleanPolynomialRing` | Sage is not strong here |
| Category theory | Limited Sage support | Out of Sage's scope |
| Unit conversion | External `units` package | Domain-specific |
| Curve fitting | Limited in Sage (scipy is better) | Wrong tool for the job |

---

## Completed (v0.2.0)

All items from the initial evaluation and TODO have been implemented:

- [x] 18 MCP math tools (calculus, algebra, linear algebra, ODEs, number theory, statistics, plotting)
- [x] CLI integration test suite (43 cases, Claude + Gemini)
- [x] 267 pure-Python tests and 342 tests against SageMath 10.9
- [x] FastMCP 3.x upgrade with full API migration
- [x] CI modernization (6 parallel jobs, matrix testing, uv caching, pip-audit, coverage)
- [x] Docker image pinned to SageMath 10.9
- [x] Helm chart health probes (liveness, readiness, startup)
- [x] Python 3.12+ minimum
- [x] All GitHub Actions on Node.js 24
- [x] Worker startup error propagation
- [x] MCP resource serialization fix
- [x] Security policy: base64/io imports for plot support
- [x] Comprehensive documentation across all markdown files
- [x] Project metadata, classifiers, URLs
- [x] MIT LICENSE file (was Apache 2.0)
- [x] Version synchronization across pyproject.toml, __init__.py, Helm chart
- [ ] Include both `server.json` version fields in automated version synchronization
