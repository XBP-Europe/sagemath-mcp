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
| 7 | Low | Distribution: Smithery and Glama listings | **partly done** |
| 8 | Low | Codex still routes two questions to `evaluate_sage` | accepted |
| 9 | Low | Jupyter kernel `debug_request` question left unresolved | deferred |
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
- **Glama**: indexes public MCP servers from GitHub automatically and ranks on
  metadata quality. The repository topics, description and README added earlier
  are what it reads; claim the listing at <https://glama.ai/mcp/servers> to edit
  it.

Note that SageMath is a large runtime and is not bundled: the Smithery command
assumes `sage` is on PATH, so the container image remains the better route for
callers who do not have it. Worth saying on the listing rather than leaving
people to discover it.

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

**Suggestion:** leave it. The remaining lever would be structural — not exposing
`evaluate_sage`, or client-side tool-choice hints — and neither is worth the cost
for two cases that already return correct answers.

---

## 9. Jupyter kernel `debug_request` question — deferred

`prototypes/jupyter_transport/FINDINGS.md` recommends against adopting the kernel
transport. One question was left open: `debugpy` is present in Sage's Python, and
whether a crafted `debug_request` can evaluate outside `do_execute` was never
established.

**Suggestion:** only worth answering if the transport is revisited for rich
display, which is the one argument that would justify it.

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

SSH authentication to GitHub broke during this session (`ssh -T git@github.com`
returns `Permission denied (publickey)` with keys loaded). `gh` still works
because it uses token auth. If it persists, `git remote set-url origin https://…`
with `gh auth setup-git` routes git through the same token.
