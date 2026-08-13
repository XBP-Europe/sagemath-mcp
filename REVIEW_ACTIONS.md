# Review actions — 2026-08-13

Findings from a review of the 50-commit range `2eac01e..345906d`, with a
suggested fix and a way to verify each. Runtime claims were measured against a
real SageMath 10.9 worker where relevant; protocol, session and persistence
claims were reproduced with MCP clients or focused worker/manager probes. The
full Sage-backed suite passed, which is why the missing regression cases are
called out explicitly below.

Severity is about consequence, not effort.

| # | Severity | Item | Status |
|---|----------|------|--------|
| 1 | **Critical** | The AST validator is bypassable in at least seven ways | **done** |
| 2 | **Critical** | README documents protections that do not exist | **done** |
| 3 | High | The container, not the validator, is the real boundary — and it is not hardened | **done** |
| 4 | Medium | `server.py` is 2147 lines and the least-covered module | open |
| 5 | Medium | Two release paths cannot be exercised before a tag push | open |
| 6 | Low | 104 dependencies, with pip-audit now blocking | open |
| 7 | Low | Distribution: Smithery and Glama listings | open |
| 8 | Low | Codex still routes two questions to `evaluate_sage` | accepted |
| 9 | Low | Jupyter kernel `debug_request` question left unresolved | deferred |
| 10 | **Critical** | Response caching breaks state and isolation across MCP clients | open |
| 11 | High | Cancelling a named workspace restarts the default workspace | open |
| 12 | High | The large-integer corruption guard accepts corrupted JSON integers | open |
| 13 | Medium | `evaluate_sage_streaming` emits output only after completion | open |
| 14 | Medium | Idle culling discards journals instead of persisting them | open |
| 15 | Medium | Sanitized journal filenames collide | open |
| 16 | Medium | Specialized tools cannot select named workspaces | open |
| 17 | Medium | Version bumps leave `server.json` stale | open |

---

## 1. The AST validator is bypassable — **critical** — DONE

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

## 4. `server.py` is 2147 lines and the least-covered module — medium

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

## 5. Two release paths cannot be exercised before a tag push — medium

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

## 6. 104 dependencies, with pip-audit now blocking — low

Making `pip-audit` blocking was right, and it immediately cleared 32 findings.
The consequence is that a new upstream advisory now turns CI red with no change
to this repository, and `fastmcp` pulls a large tree.

**Suggested fix:** accept the tradeoff, but add a scheduled weekly job that runs
the audit against `main` so an advisory surfaces on its own schedule rather than
in whoever's PR happens to be open. Keep the blocking behaviour.

---

## 7. Distribution: Smithery and Glama listings — low

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

## 10. Response caching breaks state and client isolation — **critical**

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

## 11. Named-workspace cancellation targets the wrong worker — high

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

## 12. The large-integer corruption guard does not guard JSON integers — high

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

## 13. The streaming tool buffers all output — medium

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

## 14. Idle culling bypasses persistence — medium

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

## 15. Journal filename sanitization is not injective — medium

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

## 16. Specialized tools cannot use named workspaces — medium

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

## 17. Version bumps leave the registry manifest stale — medium

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

SSH authentication to GitHub broke during this session (`ssh -T git@github.com`
returns `Permission denied (publickey)` with keys loaded). `gh` still works
because it uses token auth. If it persists, `git remote set-url origin https://…`
with `gh auth setup-git` routes git through the same token.
