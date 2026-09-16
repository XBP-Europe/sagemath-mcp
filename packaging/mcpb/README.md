# MCPB bundle

`manifest.json` and `pyproject.toml` here build a
[MCP Bundle](https://github.com/modelcontextprotocol/mcpb) — the one-click
install format desktop MCP hosts use, Claude Desktop among them.

## What it does

It uses the **`uv` server type**, so the bundle itself is about 2 KB: three
files, no vendored dependencies. The host resolves `pyproject.toml` with uv at
first launch, and that pins one thing —

```
sagemath-mcp[passagemath]==<the release>
```

— which brings the server **and a Sage runtime**. That is the point. A bundle
that installed only the server would start cleanly and then refuse every
evaluation for want of a Sage behind it, and no one-click install can require
the user to already have `sage` on their PATH.

## What it costs

The passagemath wheels are roughly **1 GB**, downloaded on first launch. The
first start is therefore slow and needs a network; later starts are immediate.
The manifest's `long_description` says so, because a gigabyte arriving
unannounced after a one-click install is how an extension gets uninstalled
before it ever works.

## Platforms

`darwin` and `linux` only. Native Windows is excluded on the evidence in
[`docs/passagemath_evaluation.md`](../../docs/passagemath_evaluation.md):
passagemath's Windows support is partial — `plot` yes, `pari`, `singular` and
`maxima` no — so a one-click Windows install would give a server that starts and
then fails most of its tools, which is worse than not offering it.

## Security

A bundle is a **local install with your user's privileges**. The deny-by-default
policy still applies to caller code, but the process boundary the container
provides does not. For untrusted or multi-tenant use, run the container instead;
[`SECURITY.md`](../../SECURITY.md) has the threat model.

## Building it

```bash
make mcpb          # writes dist/sagemath-mcp-<version>.mcpb
```

That runs `npx @anthropic-ai/mcpb pack`, which validates the manifest against
the published schema on the way through. `tests/test_mcpb_bundle.py` checks the
manifest's other promises without needing node, and
`tests/test_version_consistency.py` keeps the version and the pin in step with
`pyproject.toml` — `scripts/bump_version.py` moves both, so a release cannot
ship a bundle that installs the previous one.
