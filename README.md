# SageMath MCP Server

<!-- mcp-name: io.github.XBP-Europe/sagemath-mcp -->

[![CI](https://github.com/XBP-Europe/sagemath-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/XBP-Europe/sagemath-mcp/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/XBP-Europe/sagemath-mcp.svg)](https://github.com/XBP-Europe/sagemath-mcp/releases/latest)
[![PyPI](https://img.shields.io/pypi/v/sagemath-mcp.svg)](https://pypi.org/project/sagemath-mcp/)
[![GHCR](https://img.shields.io/badge/GHCR-sagemath--mcp-blue?logo=github)](https://github.com/XBP-Europe/sagemath-mcp/pkgs/container/sagemath-mcp)
[![License](https://img.shields.io/github/license/XBP-Europe/sagemath-mcp.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/MCP-Model%20Context%20Protocol-purple)](https://modelcontextprotocol.io/)
[![FastMCP](https://img.shields.io/badge/FastMCP-3.4%2B-green.svg)](https://gofastmcp.com/)
[![SageMath](https://img.shields.io/badge/SageMath-10.9-orange)](https://www.sagemath.org/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://docs.astral.sh/ruff/)
[![Typed](https://img.shields.io/badge/type--checked-py.typed-blue)](https://peps.python.org/pep-0561/)
[![Coverage](https://img.shields.io/badge/coverage-100%25-brightgreen.svg)](https://github.com/XBP-Europe/sagemath-mcp/actions/workflows/ci.yml)
[![Downloads](https://img.shields.io/pypi/dm/sagemath-mcp.svg)](https://pypi.org/project/sagemath-mcp/)
[![MCP Registry](https://img.shields.io/badge/MCP%20Registry-listed-purple)](https://registry.modelcontextprotocol.io/)
[![Signed](https://img.shields.io/badge/images-cosign%20signed-blueviolet?logo=sigstore)](https://github.com/XBP-Europe/sagemath-mcp/blob/main/.github/workflows/release.yml)
[![Dependabot](https://img.shields.io/badge/dependabot-enabled-025E8C?logo=dependabot)](https://github.com/XBP-Europe/sagemath-mcp/blob/main/.github/dependabot.yml)
[![Last commit](https://img.shields.io/github/last-commit/XBP-Europe/sagemath-mcp.svg)](https://github.com/XBP-Europe/sagemath-mcp/commits/main)

A [Model Context Protocol](https://modelcontextprotocol.io/) server that gives an
LLM a sandboxed mathematical subset of [SageMath](https://www.sagemath.org/) —
symbolic calculus, number theory, linear algebra, ODEs, plotting, combinatorics,
graphs, groups, elliptic curves, and more. Each MCP session gets a dedicated Sage
worker process, so variables, functions, and assumptions **persist across tool
calls**. It ships **40 MCP tools**, one of which — `verify_claim` — re-checks a
stated result through a proof ladder and answers `proved` / `refuted` /
`supported` / `undecided` with its evidence.

Caller code is **deny-by-default**: the full breadth of Sage mathematics is
reachable, but imports, the external CAS interfaces, and the file / display /
persistence primitives are not. The policy accepts **98.6% of SageMath's own
432,878 documented doctest examples** while refusing the rest — measured on every
CI run (see [Security](#security)).

Full manual: **[USAGE.md](USAGE.md)** — every tool's parameters and examples, how
code is interpreted, and the security model in depth.

## Install & run

**Recommended — the container image (SageMath is baked in):**

```bash
docker run --rm \
  --read-only --tmpfs /tmp:rw,size=512m --tmpfs /home/sage/.sage:rw,size=256m \
  --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 4g \
  -p 127.0.0.1:8314:8314 \
  ghcr.io/xbp-europe/sagemath-mcp:latest
```

Those flags are the hardening the server expects; the port is published on
loopback deliberately — the server executes code and authenticates nobody.
`docker compose up --build` applies the same hardening from one reviewed file.
Released images are signed with Cosign.

**From PyPI (bring your own Sage runtime):**

```bash
pip install sagemath-mcp
sagemath-mcp                                             # stdio (default)
sagemath-mcp --transport streamable-http --port 8314    # HTTP on 127.0.0.1
```

This needs a working SageMath on the host — either `sage` on your `PATH` or the
`sagemath/sagemath` Docker image.

**A Sage runtime without the 3 GB image ([passagemath](https://github.com/passagemath/passagemath), optional):**

```bash
pip install "sagemath-mcp[passagemath]"    # ~1 GB, no Docker, no local Sage build
sagemath-mcp
```

A pip-installable, modularized fork of SageMath. `from sage.all import *` and the
worker run unmodified; the server detects the runtime at import and loads the
matching security artifacts, so the deny-by-default policy is equivalent on both.
It is pinned exactly (`passagemath-standard==10.8.9`) and exercised by its own CI
lane — the whole suite plus the doctest-corpus sweep against the pin — because
passagemath's release QA has shipped broken backends
([docs/passagemath_evaluation.md](docs/passagemath_evaluation.md)). It is the
optional runtime; the monolithic image stays primary, and for untrusted or
multi-tenant use run the container regardless of runtime — a pip install has your
user's privileges, the container adds OS-level isolation.

Source install, Docker Compose, and the Kubernetes Helm chart are in
**[USAGE.md](USAGE.md)**.

## Connect an MCP client

**Claude Desktop** — add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "sagemath": { "command": "uv", "args": ["run", "sagemath-mcp"] }
  }
}
```

Claude Code, Codex CLI, Gemini CLI, and HTTP-transport setup are in
[USAGE.md](USAGE.md#integrating-with-mcp-clients).

## Try it

Prompts a client can run once the server is connected:

- **Damped harmonic oscillator** — "Solve `x'' + 2·x' + 5·x = 0` with
  `x(0)=1`, `x'(0)=0`, then verify the solution satisfies the ODE."
- **General relativity** — "On the hyperbolic upper half-plane with metric
  `(dx² + dy²)/y²`, compute the Ricci scalar and confirm it is a constant
  negative curvature."
- **Coupled two-tank system** — "Solve the linear ODE system for two mixing
  tanks, then take the long-term limit of each concentration."

Each builds an object once and explores it across calls — the case for
`evaluate_sage` and its persistent session.

## The 40 tools

The math tools use SageMath as the backend; full parameters and examples are in
**[USAGE.md](USAGE.md#tool-reference)**.

| Category | Tools |
|----------|-------|
| **Core execution** | `evaluate_sage`, `evaluate_sage_streaming` |
| **Verification** | `verify_claim` |
| **Calculus** | `differentiate_expression`, `integrate_expression`, `limit_expression`, `series_expansion` |
| **Algebra** | `solve_equation`, `simplify_expression`, `expand_expression`, `factor_expression`, `calculate_expression`, `symbolic_sum` |
| **Linear algebra** | `matrix_multiply`, `matrix_operation` |
| **Differential equations** | `solve_ode` |
| **Number theory** | `number_theory_operation` |
| **Combinatorics** | `combinatorics_operation` |
| **Graph / group theory** | `graph_operation`, `group_operation` |
| **Elliptic curves / coding** | `elliptic_curve_operation`, `coding_theory_operation` |
| **Polynomials / boolean / geometry** | `polynomial_ring_operation`, `boolean_algebra_operation`, `geometry_operation` |
| **Statistics / probability** | `statistics_summary`, `distribution_operation` |
| **Visualization** | `plot_expression`, `plot3d_expression`, `plot_multi_expression` |
| **Numeric methods / vector calculus** | `find_root`, `vector_calculus_operation` |
| **Session control** | `reset_sage_session`, `interrupt_sage_session`, `cancel_sage_session` |
| **Named workspaces** | `start_sage_session`, `list_sage_sessions`, `stop_sage_session` |
| **Diagnostics** | `check_sage_health`, `lookup_sage_doc` |

Plus HTTP `/health` and `/ready` endpoints and 3 MCP resources (session
snapshots, monitoring metrics, doc links). Prefer `interrupt_sage_session` over
`cancel_sage_session` — it stops a computation while keeping the session's
variables.

## How it works

```
┌─────────────────────────────────────────────────────────────┐
│  MCP Client (Claude Desktop, Gemini CLI, Codex CLI, ...)    │
└───────────────────────────┬─────────────────────────────────┘
                            │  MCP protocol (stdio or HTTP)
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  app.py + tools/ --- FastMCP 3.x                            │
│  ┌─────────────┐  ┌──────────────┐                          │
│  │ 40 MCP Tools│  │ 3 Resources  │   session.py routes each │
│  └─────────────┘  └──────────────┘   client to its worker   │
└───────────────────────────┬─────────────────────────────────┘
                            ▼   one subprocess per session
┌─────────────────────────────────────────────────────────────┐
│  _sage_worker.py --- allowlist.py + security.py             │
│  AST validation, then exec() in a persistent namespace      │
│  (vars, functions and classes survive across calls)         │
└─────────────────────────────────────────────────────────────┘
```

**Request flow:** MCP client → a tool in `tools/` →
`SageSessionManager.get_or_create()` → `SageSession.evaluate()` → JSON request to
the `_sage_worker.py` subprocess → AST validation → `exec()` in the persistent
namespace → JSON response.

- **Process isolation** — each session runs Sage in its own subprocess; a crash
  or timeout in one cannot affect another.
- **Stateful sessions** — variables, functions, and assumptions persist across
  calls, enabling multi-step workflows.
- **Deny-by-default** — a name is refused unless the generated allowlist offers
  it or the caller's own code bound it. A helper a future SageMath adds is
  refused until someone reviews it, rather than reachable the day it lands.

## Security

The AST validator is **defence in depth against accidents and casual misuse — it
is not a boundary against determined adversarial code.** **The container is the
security boundary.** The server has **no authentication**, so every default is
loopback: `--host` defaults to `127.0.0.1`, the default transport is stdio, and
Compose / Helm keep the endpoint off the network. Put something that
authenticates in front of it before exposing it.

What the policy enforces: an **allowlist** (caller code may read only a name the
server offers or the caller itself bound); **no imports** by default; `eval` /
`exec` / `compile` and runtime string evaluation blocked; dunder access blocked;
the external CAS interfaces and every file / network / persistence primitive
removed from the namespace, by provenance rather than by name. The container adds
a read-only root, dropped capabilities, `no-new-privileges`, and fork / memory
ceilings.

Full threat model and the complete blocked / allowed tables:
**[SECURITY.md](SECURITY.md)** and
[USAGE.md § Security model](USAGE.md#security-model).

## Docs & more

- **[USAGE.md](USAGE.md)** — the full manual: every tool, how code is
  interpreted, deployment, and the security model.
- **[docs/mcp_quickstart.md](docs/mcp_quickstart.md)** — a first-session walk-through.
- **[CHANGELOG.md](CHANGELOG.md)** · **[ROADMAP.md](ROADMAP.md)** ·
  **[CONTRIBUTING.md](CONTRIBUTING.md)** · **[SECURITY.md](SECURITY.md)**

## Requirements

Python 3.12+ and a SageMath runtime (the container image bundles SageMath 10.9;
otherwise `sage` on `PATH`, or the `[passagemath]` extra). Built on
[FastMCP 3.x](https://gofastmcp.com/).

## Contributing

Issues and pull requests welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). Run
`make lint` and `make test` before pushing (`git config core.hooksPath .githooks`
wires the pre-push check). Roadmap and open work: [ROADMAP.md](ROADMAP.md).

## License

MIT — see [LICENSE](LICENSE). SageMath itself is GPL-2.0-or-later and is used as a
separate runtime; no SageMath source is redistributed in this repository.
