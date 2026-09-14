# Support

What "supported" means for this project, where to ask, and how fast to expect an
answer. Written so that an evaluator can price the risk of depending on it.

## Where to ask

| You want to… | Go to |
| --- | --- |
| Ask how to do something, or whether a result is right | [GitHub Discussions](https://github.com/XBP-Europe/sagemath-mcp/discussions) (Q&A) |
| Report a bug or ask for a feature | [GitHub Issues](https://github.com/XBP-Europe/sagemath-mcp/issues) — the templates ask for what a fix needs |
| Report a sandbox escape or any security problem | **Privately**, per [SECURITY.md](SECURITY.md). Never in an issue or discussion |
| Contribute code or docs | [CONTRIBUTING.md](CONTRIBUTING.md) |
| Cite the software | [CITATION.cff](CITATION.cff), or GitHub's *Cite this repository* box |

Before asking, [USAGE.md](USAGE.md) is the manual and
[docs/mcp_quickstart.md](docs/mcp_quickstart.md) a first-session walk-through;
`check_sage_health` and `lookup_sage_doc` are the two tools built for diagnosing
"why was this refused" and "is this name offered".

## What is supported

**Versions.** The latest release only, as [SECURITY.md](SECURITY.md) states.
Fixes land on `main` and ship in the next release; nothing is backported to
earlier versions unless there is a compelling reason. Upgrade before reporting.

**Python.** 3.12 and 3.13, the CI matrix (`requires-python >= 3.12`). A new
CPython minor is added to the matrix once the Sage runtimes below ship wheels or
an image for it, not before.

**Sage runtimes.** Two, with different guarantees:

| Runtime | Status | What backs it |
| --- | --- | --- |
| The published container image (monolithic SageMath 10.9, `ghcr.io/xbp-europe/sagemath-mcp`) | **Primary.** The release is built on it, smoke-tested against it and signed | Integration suite + doctest-corpus sweep on every push |
| The `[passagemath]` pip extra (`passagemath-standard`, pinned exactly) | **Optional.** Same policy, second generated artifact set | Its own CI lane cold-installs the pin and runs the whole suite; the pin moves only through that lane |
| The passagemath container image (`ghcr.io/xbp-europe/sagemath-mcp:<tag>-passagemath`, linux/amd64 + linux/arm64) | **Optional on amd64; the native choice on arm64**, where the primary image runs only under emulation | Built from the same pinned extra, smoke-tested natively per architecture in the release, signed and attested like the primary image |
| A locally installed `sage` on `PATH` | Best effort | Not tested in CI. Should work on 10.9; other versions may refuse names or lack helpers |

The version pins are deliberate. A Sage upgrade regenerates and re-reviews the
security allowlists, so the runtime moves when the review is done, not when
upstream tags.

**Transports and clients.** stdio (the default; Claude Desktop, Claude Code and
other local MCP hosts) and streamable HTTP behind the container. Any client that
speaks the MCP protocol version fastmcp 3.x implements is expected to work; the
`tests/cli_integration` harness exercises three real clients but runs locally,
where the API keys live, not in CI.

**Deployment.** Docker Compose and the Helm chart in `charts/` are maintained
with the code and version-bumped with it. For untrusted or multi-tenant use the
container is the security boundary; a bare `pip install` runs with your user's
privileges. See the threat model in [SECURITY.md](SECURITY.md).

## Release cadence and versioning

Releases are **tag-driven, not calendar-driven**: a version ships when a change
warrants it. In practice that has been every few weeks during active development;
a security fix ships as soon as it is verified against real Sage, as a patch
release. Pre-releases carry a `-beta.N` suffix and are not supported versions.

Versioning is [semantic](https://semver.org/) with one project-specific rule: a
tool returning a **different value** than the previous release is a *minor* bump
even when the new value corrects a bug, because a client that pinned to the old
output breaks either way. Tool names, parameters and descriptions are snapshotted
in the test suite and change only deliberately.

Every release publishes the same artefacts from one workflow: the wheel and
sdist on PyPI with PEP 740 attestations, a Cosign-signed image on GHCR carrying
SLSA provenance and an SPDX SBOM as attestations, a GitHub release whose notes
are the [CHANGELOG.md](CHANGELOG.md) section for that version with the SBOMs
attached, and an updated entry in the official MCP registry.
[DISTRIBUTION.md](DISTRIBUTION.md) shows how to verify each. **A PyPI version is
never reused**; a bad release is followed by a new one, not replaced.

## Response expectations

This is a single-maintainer project (`CODEOWNERS` names one person) under an
organisation's account, and the honest expectation follows from that:

- **Security reports:** acknowledged within 3 business days, initial assessment
  within 7 — the commitment in [SECURITY.md](SECURITY.md), and the one thing
  that pre-empts everything else.
- **Bugs with a reproduction** (the tool, the exact input, what came back):
  usually triaged within a week. A refused expression that is legitimate
  mathematics is treated as a bug, not a feature request — reducing refusals is
  an explicit goal, and the doctest-corpus acceptance rate is the metric.
- **Feature requests and discussions:** read and answered, on no fixed schedule.
  [ROADMAP.md](ROADMAP.md) and [TODO.md](TODO.md) say what is planned and,
  as importantly, what is explicitly not.

Every commitment above is best effort, and none of it is a service-level
agreement. If you need one, or need the runtime pinned to a different Sage
version than the project ships, the maintainers can be reached at
sagemath-mcp-maintainers@proton.me.

## Good first issues

Issues labelled
[`good first issue`](https://github.com/XBP-Europe/sagemath-mcp/labels/good%20first%20issue)
are scoped so that a first contribution needs only the pure-Python unit suite
(`make test`, no Sage), and [`help wanted`](https://github.com/XBP-Europe/sagemath-mcp/labels/help%20wanted)
marks work the maintainer would rather review than write. CONTRIBUTING.md
explains what CI enforces, including the 100% coverage gate, so a first pull
request does not learn it from a red check.
