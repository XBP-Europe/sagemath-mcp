# Roadmap

This document tracks planned improvements to the SageMath MCP server, organized by priority and effort. The goal is to strengthen the server's position as a universal mathematics MCP server that enables LLMs to perform any symbolic or discrete mathematical operation.

**Current state (v0.4.0):** 37 MCP tools (31 Sage-backed, 6 infrastructure) covering calculus, algebra, linear algebra, ODEs, number theory, combinatorics, graph theory, group theory, elliptic curves, coding theory, boolean algebra, polynomial rings, geometry, probability, vector calculus, statistics, 2D/3D plotting, numeric root-finding, and streaming execution. 258 unit tests, and 333 tests against a real SageMath 10.9 runtime, plus 43 CLI integration tests.

Integration coverage now includes every tool exercised against the examples in its own
documentation, and a syntax matrix over the input spellings each tool must accept. Both
run in CI, which had previously reported the integration job as passing while running
nothing at all.

---

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

- **Sandboxing.** sympy-mcp documents that its parser "uses `eval` under the hood,
  effectively allowing arbitrary code execution". No SageMath peer documents a sandbox at
  all. The AST validator with a configurable policy is the clearest differentiator, and
  only [Eis4TY/Sym-MCP](https://github.com/Eis4TY/Sym-MCP) shares the approach.
- **Tool surface.** 37 against 3, 5 and 10 for the SageMath peers.
- **Verification.** 258 unit and 333 real-runtime tests; peer test coverage is largely
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
- [ ] List on Smithery and Glama, as fermat-mcp does

At the time of the survey the only SageMath server in the official registry was
`io.github.justice8096/sagemath-mcp-server`, a one-star project with 10 tools. Registry
publication requires the ownership marker to be present in the *published* PyPI
description, so it takes effect from the first release after this change.

## Tier 2: Session ergonomics (done 2026-08-13)

The two capabilities where a one-star project was genuinely ahead. Neither needed an
architectural change.

- [x] **Interrupt without restart.** `interrupt_sage_session` signals the worker, which
      turns the resulting KeyboardInterrupt into an `Interrupted` response and keeps its
      namespace. `cancel_sage_session` remains the escape hatch for a wedged worker.
- [x] **Named multi-sessions.** `start_sage_session`, `list_sage_sessions` and
      `stop_sage_session`, with an optional `session` argument on the state-bearing
      tools. The default workspace keys on the bare scope, so existing behaviour and
      persisted journals are unchanged.

Two details worth remembering. `interrupt` deliberately does not take the session lock:
the evaluation being interrupted holds it, so waiting would deadlock until the
computation everyone is trying to stop finishes on its own. And the worker's
`except Exception` did not catch `KeyboardInterrupt`, which is a `BaseException` — without
handling it explicitly the worker exited and took the namespace with it, defeating the
purpose.

## Under consideration — Tier 3: Jupyter kernel transport

Replacing the JSON-over-stdio worker with `jupyter_client` would retire a class of bugs
this project keeps paying for: stream framing, interrupt handling and multi-line input.
It is also a rewrite of `session.py` and `_sage_worker.py`, and the AST validator would
have to be re-integrated into that path, since the sandbox is the main differentiator and
cannot be lost in the move. Prototype before committing.

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
- [x] **`evaluate_sage_streaming`** — executes code and emits each stdout line as a progress event for real-time partial output display
- [x] **Disk-backed session persistence** — code journal saved to `SAGEMATH_MCP_PERSIST_DIR` on shutdown, replayed on restore. Controlled by `SAGEMATH_MCP_PERSIST_SESSIONS` and `SAGEMATH_MCP_PERSIST_DIR` environment variables.

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
- [x] 242 unit tests at 99% branch coverage
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
