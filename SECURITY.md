# Security Policy

## Supported Versions

We currently support the latest released version of the `sagemath-mcp` package. Security fixes will be applied to `main` and backported only when there is a compelling reason.

| Version | Supported |
| ------- | --------- |
| latest  | ✅        |

## Security Model

Read this before reporting: it decides what counts as a vulnerability here, and
it is not obvious from the outside.

This server **evaluates mathematics that a language model wrote**. Execution is
the product, so "code ran" is not by itself a finding. What matters is where it
ran and what it could reach.

There are four layers, and only one of them is a boundary:

| Layer | What it is | What it is not |
|-------|-----------|----------------|
| **Caller allowlist** (`allowlist.py`) | A caller may read only the names this server offers -- the mathematical names Sage preloads, safe builtins, and whatever they define themselves. Deny-by-default: an unrecognised name is refused rather than assumed harmless | Derived from today's namespace, so it does not retroactively catch something dangerous already in it |
| AST policy (`security.py`) | Rejects disallowed imports, `eval`/`exec`, dunder access, indirection helpers, forbidden modules and known code-executing Sage helpers | **Not a boundary.** It is a denylist over a namespace thousands of names deep, and it has been bypassed and repaired repeatedly |
| Worker namespace scrub (`_sage_worker.py`) | Removes known code-executing Sage helpers and external CAS interfaces from the worker's initial namespace | A backstop for spellings the policy misses, not a guarantee that Sage exposes no other route to the same capability |
| **The container** | With the supplied configuration: a read-only root filesystem and checkout, dropped capabilities, no new privileges, and deployment-specific resource limits | **This is the process and filesystem boundary.** Run it; it does not itself block network egress or make readable secrets safe |

One property of the AST policy is worth stating plainly, because it decides
whether a finding is interesting: **every attribute rule is enforced on the
source text.** The parent and the attribute are both read out of the AST. Any
primitive that fetches an attribute by a *runtime string* therefore defeats all
of them at once, which is why `attrgetter`, `methodcaller`, `itemgetter`,
`getattr`, `setattr` and `vars` are refused as a class rather than as a list.
`operator.attrgetter("misc.persist.unpickle_global")(sage)` returned the real
function on SageMath 10.9 and was arbitrary code execution. If you find another
way to reach an attribute by a name the parser never sees, that is a finding
even if you cannot yet build a payload from it.

The practical consequence: **run the container, and do not expose the port.**
Defaults are loopback throughout — stdio transport, `--host 127.0.0.1`, the
compose file publishing to `127.0.0.1:8314`, a `ClusterIP` service — because
there is **no authentication**, which is normal for a locally-run MCP server and
is why it must stay local unless you put something authenticating in front.

## Threat Model

### Assets to protect

- The host, container runtime and Kubernetes node from code executed by a Sage
  worker.
- Files, credentials and environment variables available to the server. A
  read-only mount prevents modification, but it does not prevent disclosure.
- The confidentiality and integrity of every MCP session, including saved
  variables, journals, pending requests and cancellation state.
- The integrity of mathematical results. A plausible but silently rounded or
  cross-session result is a security-relevant failure even if no shell is
  reached.
- Service availability and the integrity of release artifacts and dependencies.

### Actors and entry points

The operator who selects the image, configuration, mounts, credentials, network
policy and exposure of the HTTP endpoint is trusted. MCP clients, prompts,
model-generated code and every caller-controlled tool argument are untrusted.
Package and image dependencies are trusted only to the extent that they are
pinned, scanned and obtained from the documented release channel.

Untrusted data enters through direct Sage code, specialised-tool parameters,
session and workspace identifiers, cancellation requests, and the unauthenticated
HTTP transport when it is enabled. Specialised tools are not inherently safer:
their generated templates execute as trusted code, so every caller-controlled
fragment must pass the appropriate literal, identifier or expression validator
before interpolation.

### Trust boundaries and data flow

```text
untrusted MCP client
        |
        v
MCP transport and tool routing  (no authentication in this project)
        |
        v
allowlist + AST validation + namespace scrub  (defence in depth, bypassable)
        |
        v
Sage worker in a hardened container  (process/filesystem boundary)
        |
        +----> explicitly mounted files and injected environment
        +----> network destinations allowed by the deployment
```

The container limits host impact; it is not a confidentiality boundary for data
deliberately passed into it. The supplied Compose and Helm configurations do not
deny outbound traffic. Deployments handling sensitive data must therefore avoid
injecting unrelated secrets and apply an external egress policy. A `ClusterIP`
Service limits ordinary exposure but is not authentication or authorization.

Sessions share one server process while evaluations run in per-session workers.
Session routing, journals, response IDs, timeouts and cancellation paths must all
preserve that isolation. A stale response or journal assigned to another session
crosses a trust boundary.

### Threats and security objectives

| Threat | Objective |
|--------|-----------|
| Generated-code injection | Validate every caller-controlled fragment before it reaches a trusted template; reject rather than guess when syntax is outside the accepted subset |
| Direct shell, file, network, loader, compiler, pickle or external-CAS access | Block known routes in the AST policy and worker namespace, test bypasses against real Sage, and contain any missed route in the hardened runtime |
| Attribute access by a name the parser cannot see | Refuse string-path primitives as a class, since each one defeats every AST attribute rule at once |
| Container or node escape | Run as non-root with a read-only root, dropped capabilities, no privilege escalation and current runtime/image security fixes |
| Session crossover or stale responses | Bind requests, responses, journals and cancellation to the correct session and request identifiers |
| Unauthenticated remote use | Keep listeners local by default; require deployment-provided authentication and authorization before broader exposure |
| Resource exhaustion | Enforce evaluation timeouts and deployment resource limits (Compose supplies PID/memory limits; Helm supplies CPU/memory limits); cancellation must release worker and queue resources |
| Incorrect or lossy results | Preserve exact values across Sage, Python and JSON boundaries and fail explicitly when exact transport is impossible |
| Supply-chain compromise | Pin dependencies, keep the lockfile reproducible, scan dependencies and verify signed release images |

### Assumptions and deployment responsibilities

- The container runtime or Kubernetes cluster correctly enforces its isolation
  and security context. A bare `uv run sagemath-mcp` process does not provide
  that boundary.
- Operators do not mount the Docker socket, host devices, writable source trees
  or sensitive paths into the worker. Additional mounts and `envFrom` sources
  expand the impact of a sandbox bypass.
- Operators add network policy or another egress control when the server can
  read confidential data. Loopback binding and `ClusterIP` affect inbound reach,
  not outbound access.
- Authentication, TLS, tenant authorization and audit retention are supplied by
  the surrounding platform when this becomes a shared or remotely reachable
  service.
- The documented image and Sage version are used. A Sage upgrade can add new
  helpers or change namespace provenance and must rerun the full security and
  integration suites before release.

### In scope, and wanted

- Escaping the container, or reaching the host from inside it.
- Reading or corrupting another client's session state; anything that crosses
  between MCP sessions.
- Reaching the filesystem, network or a shell **through a tool's parameters** —
  the specialised tools build Sage code around caller input, and a string that
  escapes that construction is a real finding.
- A bypass of the caller allowlist, the AST policy or the namespace scrub. Not a host compromise on its
  own, but each one is a defect we fix and add a regression test for.
- **Silently wrong mathematics.** Unusual for a security file, but it belongs
  here: a wrong number returned with no error is the worst failure this project
  has, because nothing tells the caller. Integers above 2^53 being rounded by a
  JSON client was exactly this.
- Vulnerable dependencies (`pip-audit` runs in CI and weekly).

### Expected behaviour, not a vulnerability

- Arbitrary mathematics executing **inside the container**. That is the product.
- No authentication on stdio or a loopback HTTP transport.
- Resource exhaustion inside the configured limits — a long computation is
  bounded by `SAGEMATH_MCP_EVAL_TIMEOUT`, while the deployment must supply the
  appropriate process, memory and CPU limits.
- Anything reachable only after setting `SAGEMATH_MCP_SECURITY_ENABLED=false`,
  which disables the policy by explicit request.
- Exposing the port publicly and then being reached through it.

If you are unsure which side of the line a finding falls on, report it. Getting
the classification right is our job, not yours.

## Reporting a Vulnerability

If you discover a security vulnerability, please report it privately to the maintainers:

- Email: sagemath-mcp-maintainers@proton.me

Please include:

1. A description of the issue and its impact.
2. Steps to reproduce or proof-of-concept code, if available. For a sandbox
   finding, the most useful form is the exact code you sent to a tool, the tool
   and parameter you sent it to, and what came back.
3. Any relevant environment details (operating system, Sage version,
   configuration), and whether you were running the container or a bare install.

Past findings are written up in [`REVIEW_ACTIONS.md`](REVIEW_ACTIONS.md) with the
reproduction, the fix and the regression test for each. It is worth a look before
reporting: it shows the shape of finding this project acts on, and several
categories that are already closed.

We aim to acknowledge reports within **3 business days** and provide an initial assessment within **7 business days**.

## Disclosure Policy

1. We will confirm the issue and determine its scope.
2. A fix will be developed and reviewed. When possible we will coordinate with you regarding timelines.
3. A security advisory will be published once a fix is available, and a new release will be tagged.
4. Credit will be given to reporters unless they prefer to remain anonymous.

## PGP / Encryption

If you prefer to encrypt your report, please request our PGP public key via email. We will respond with the key and next steps.

## Guidelines for Responsible Research

- Do not publicly disclose vulnerabilities before we have had a chance to remediate.
- Avoid accessing or modifying data without explicit permission.
- Never use automated scanning in ways that could impact service availability.

Thank you for helping keep SageMath MCP safe for everyone!
