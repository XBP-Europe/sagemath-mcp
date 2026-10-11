# SageMath MCP

Gives Claude a sandboxed mathematical subset of [SageMath](https://www.sagemath.org/)
through 40 tools: exact and symbolic computation, calculus, linear algebra,
number theory, combinatorics, graph and group theory, elliptic curves, coding
theory, plotting, and `verify_claim`, which re-checks a stated result and
reports whether it was proved, refuted or only supported, with evidence. Each
conversation gets its own Sage session, so variables and definitions persist
between tool calls.

## Install

In Claude Code:

```
/plugin install sagemath-mcp --marketplace XBP-Europe/sagemath-mcp
```

## Requirements

- [uv](https://docs.astral.sh/uv/) on your `PATH`; the plugin starts the server
  with `uvx`, pinned to the release this plugin version names.
- macOS or Linux. The Sage runtime comes from the
  [passagemath](https://github.com/passagemath/passagemath) wheels, which have no
  Windows build; on Windows, run the container described in the main README.
- About 1 GB of disk and a network connection on the first start, when uv
  downloads the Sage runtime. Later starts are immediate.

## What runs, and what it can reach

The server runs on your machine with your user's privileges. Code the model
sends is checked by a deny-by-default validator before Sage runs it: imports,
file and network access, shell access and external computer-algebra interfaces
are refused. Nothing is sent anywhere by the server; the only network access is
uv downloading the packages on first launch. See the
[security model](https://github.com/XBP-Europe/sagemath-mcp/blob/main/SECURITY.md)
and the [privacy statement](https://github.com/XBP-Europe/sagemath-mcp/blob/main/PRIVACY.md).

sagemath-mcp is an independent project by XBP Europe and is not affiliated with
the SageMath developers. Documentation, the full tool list and other ways to
install are in the [main repository](https://github.com/XBP-Europe/sagemath-mcp).
Licensed MIT; SageMath and passagemath are GPL.
