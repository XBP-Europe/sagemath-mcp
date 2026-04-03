# Roadmap

This document tracks planned improvements to the SageMath MCP server, organized by priority and effort. The goal is to strengthen the server's position as a universal mathematics MCP server that enables LLMs to perform any symbolic or discrete mathematical operation.

**Current state (v0.3.0-dev):** 33 MCP tools (30 Sage-backed, 1 pure-Python `statistics_summary`, 2 infrastructure) covering calculus, algebra, linear algebra, ODEs, number theory, combinatorics, graph theory, group theory, elliptic curves, coding theory, boolean algebra, polynomial rings, geometry, probability, vector calculus, statistics, 2D/3D plotting, numeric root-finding, and streaming execution. 242 unit tests at 99% branch coverage, plus 43 CLI integration tests.

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
- [x] Docker image pinned to SageMath 10.5
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
