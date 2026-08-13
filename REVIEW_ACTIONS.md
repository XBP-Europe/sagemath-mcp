# Review actions — 2026-08-13

Findings from a review of `345906d`, with a suggested fix and a way to verify each.
Every claim here was measured against a real SageMath 10.9 runtime, not inferred
from reading the code; the commands to reproduce are included so nobody has to
take this document's word for it.

Severity is about consequence, not effort.

| # | Severity | Item | Status |
|---|----------|------|--------|
| 1 | **Critical** | The AST validator is bypassable in at least six ways | open |
| 2 | **Critical** | README documents protections that do not exist | open |
| 3 | High | The container, not the validator, is the real boundary — and it is not hardened | open |
| 4 | Medium | `server.py` is 2147 lines and the least-covered module | open |
| 5 | Medium | Two release paths cannot be exercised before a tag push | open |
| 6 | Low | 104 dependencies, with pip-audit now blocking | open |
| 7 | Low | Distribution: Smithery and Glama listings | open |
| 8 | Low | Codex still routes two questions to `evaluate_sage` | accepted |
| 9 | Low | Jupyter kernel `debug_request` question left unresolved | deferred |

---

## 1. The AST validator is bypassable — **critical**

### What is wrong

Six vectors, each confirmed returning the container uid (`1001`) from inside the
sandbox:

| Vector | Payload |
|--------|---------|
| `os` is in the namespace | `os.getuid()` |
| `getattr` is not forbidden | `getattr(os, 'getuid')()` |
| Dunder traversal | `().__class__.__bases__[0].__subclasses__()` → reaches `subprocess.Popen` |
| Builtins by attribute | `__builtins__.__import__('os').getuid()` |
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
integration suite (333 tests) is the regression net for that.

### How to verify

Write `tests/test_security_bypass.py` with the six payloads above, each asserting
`SecurityViolation`. They must fail against today's code before the fix lands —
that is the only proof the tests are testing anything. Then run the full
integration suite to confirm nothing legitimate broke.

---

## 2. README documents protections that do not exist — **critical**

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

## 3. The container is the real boundary, and it is not hardened — high

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
documented example, and the integration suite stays green.

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

## Not a project issue

SSH authentication to GitHub broke during this session (`ssh -T git@github.com`
returns `Permission denied (publickey)` with keys loaded). `gh` still works
because it uses token auth. If it persists, `git remote set-url origin https://…`
with `gh auth setup-git` routes git through the same token.
