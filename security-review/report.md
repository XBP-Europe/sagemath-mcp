# Security review — branch `fix/fragment-gate-and-monitoring-leak`

**Scope:** the pending changes on this branch versus `main` (commits `4854cab..0176c7e`,
review items 55–60 plus the monitoring leak fix). Reviewed at commit
`0176c7e9917a3d3bc6502be4303fef4e426eb1b9`.

**Method:** read the full source diff; ran the pure-Python suite (886 passed) and the
Sage-backed security/integration/coverage suites inside the running `sage-mcp`
container (426 passed); then wrote adversarial probes against the three new attack
surfaces (star-import expansion, `attrcall` literal screening, `inject_shorthands`)
and executed them end-to-end through the real worker on SageMath 10.9.

**Headline:** one **Critical** — the new star-import feature (item 60) is a complete
bypass of the AST validator and yields arbitrary command execution through the
`evaluate_sage` tool. Verified live: `os.system` ran and wrote a file as the container
user. The other four changes (monitoring redaction, `attrcall` screening, the token-screen
rework, `inject_shorthands`) reviewed clean.

---

## [Critical · Confirmed] — Sandbox escape via curated star-import module objects (CWE-94 / CWE-913 / OWASP A03:2021)

**Location:**
- `src/sagemath_mcp/_sage_worker.py:462` — `_star_export_screen()`, the provenance check
- `src/sagemath_mcp/star_exports.py:82` (`sage.modular.dims`) and `:29`
  (`sage.rings.polynomial.real_roots`) — the two admitted modules that export a module object
- `src/sagemath_mcp/security.py:1238-1242` — the terminal-segment attribute rule that the
  pivot exploits

**Reachable from:** the `evaluate_sage` (and `evaluate_sage_streaming`) MCP tool — the
primary entry point. Caller code → `SageSession.evaluate()` → worker `_execute` (untrusted
path) → `_split_code` → `rewrite_permitted_imports` expands the star → `validate_module`
approves → `exec` in the persistent namespace.

**Description.** Item 60 permits `from <curated module> import *` for 13 internal Sage
modules whose public names `_star_export_screen` judged "clean as a whole." The screen
decides a value's provenance with `home = getattr(value, "__module__", "")`
(`_sage_worker.py:462`). **Module objects have no `__module__`** (they carry `__name__`), so
`home` is `""` and every re-exported module object passes the screen silently. Two of the 13
curated modules re-export module objects:

- `sage.modular.dims` exports `dirichlet` = the module `sage.modular.dirichlet`
- `sage.rings.polynomial.real_roots` exports `time` = the stdlib `time` module

A bound Sage module object is a pivot into the entire `sage.*` tree. `sage.modular.dirichlet`
re-exports `sage.modules.free_module_element`, which reaches `sage` → `sage.env` → `os`,
`sys`, `subprocess`, `socket`, `shutil` (all imported by ordinary Sage submodules).

The second half of the chain is the terminal-segment rule at `security.py:1238`. For an
attribute chain `X.os` whose **root is caller-bound and not on the allowlist**, the validator
computes `module_path = root in allowed_names` (False here) and then `if not module_path …:
continue` — i.e. it treats the terminal `os` as a harmless *method name* on a mathematical
object, not as the `os` module. That inference is correct for `A.trace()` but false when the
root is a module object: `dirichlet.free_module_element.sage.env.os` **is** the real `os`
module, and the whole chain contains no forbidden *parent* before the terminal `os`, so
nothing fires. The caller binds `os` to a fresh name and calls `.system()` — which was
deliberately removed from `forbidden_attribute_names`, so `alias.system('…')` is unguarded.

**Impact — verified, not theoretical.** A single `evaluate_sage` call:

```python
from sage.modular.dims import *
_m = dirichlet.free_module_element.sage.env.os
_m.system('id > /tmp/PWNED2 2>&1')
```

executed on SageMath 10.9 in the container: the snippet returned `ok`, and `/tmp/PWNED2`
contained `uid=1001(sage) gid=1001(sage) groups=1001(sage)`. `_m.environ['PATH']` and
`_m.getcwd()` also returned live values, so the same alias reads every environment variable
(secrets injected via compose env land here) and opens outbound sockets.

Blast radius depends on deployment:
- **stdio (the default, Claude Desktop / `uv run sagemath-mcp`)** runs with **no container**.
  There the AST validator is the only boundary, so this is arbitrary code execution on the
  user's host.
- **Docker/Helm** are hardened (`read_only`, `cap_drop: ALL`, `no-new-privileges`,
  non-root). The escape is bounded to: read all env vars, read the mounted checkout, write
  the `/tmp` and `/home/sage/.sage` tmpfs, and open outbound network connections (compose
  does not set `network_mode: none`). That is still full environment/secret disclosure and
  an exfil channel.

The project's own model ("the validator is defence in depth, the container is the boundary")
holds only where a container exists; the default deployment has none.

**Controls checked and ruled out.**
- Namespace scrub (`_strip_from_sage_all`) removes names from `sage.all` only, never from
  `sage.modular.dirichlet.__dict__` or `sage.env.__dict__`, so the pivot modules are intact.
- `forbidden_attribute_parents` catches `os`/`sys`/… only *mid-chain*; as the terminal
  segment under a non-allowlisted root they are skipped (the rule at `security.py:1242`).
- `forbidden_attribute_names` no longer contains `system` (removed in an earlier item as
  "redundant, since `os` is unreachable" — a premise this feature invalidates).
- Dunder rule does not apply — no `__…__` is used.
- The drift test `test_the_star_exports_match_this_sage` **passes**: it re-runs the same
  blind screen, so it agrees the modules are "clean." It does not protect against this class.

**Remediation.** Close it in the screen (the root cause); either fix drops both offending
modules from `STAR_EXPORTS` under the "clean as a whole" rule:

1. In `_star_export_screen` (`_sage_worker.py`), reject any export whose value is a module:
   ```python
   import types
   ...
   value = vars(module).get(name)
   if isinstance(value, types.ModuleType):
       return None          # a bound module object is a pivot into sage.*/stdlib
   ```
   This is decisive and cheap. Regenerate `star_exports.py` (`make` target / the generator)
   and confirm `sage.modular.dims` and `sage.rings.polynomial.real_roots` drop out.

2. Defence in depth, independently worth doing: in the terminal-segment rule
   (`security.py:1238`) do **not** treat a forbidden parent as a benign method when the root
   is a caller-bound *import alias*. `_split_code` already knows which bound names came from
   an `ast.alias`; a chain rooted at an imported name should be judged a module path
   regardless of allowlist membership.

Add a regression test that runs the verified reproducer above through the untrusted worker
path and asserts it is refused. Note the screen is inherently capability-blind (the generator
comment already flags `sage.libs.ecl`/`EclObject`), so the module-object check hardens one
known class; the residual risk below still argues for keeping the curated list minimal.

**References:** CWE-94 (code injection), CWE-913 (improper control of dynamically-managed
code resources), OWASP A03:2021 (Injection).

---

## Residual risk (not a discrete finding) — the star-export screen is capability-blind

`_star_export_screen` is a name + provenance filter. It cannot see what a *callable* does:
the generator already excludes `sage.libs.ecl` by hand because `EclObject` evaluates Lisp,
which no name check detects. The module-object fix above closes the one confirmed hole, but
every added module still rests on human judgement that none of its exported callables
exec/compile/open/connect internally. Keep `CANDIDATE_MODULES` as small as the corpus
genuinely needs, and treat each addition as a manual capability review, not a screen pass.

---

## Changes reviewed and cleared

- **Monitoring leak fix (item 58)** — `MonitoringSnapshot` drops the three free-text fields
  and `public_snapshot()` pops them before serialisation; the resource emits only
  process-wide aggregates. `snapshot()` still returns the fields for server logs. Sound; the
  sibling `session_resource` correctly scopes by `ctx.session_id` and fails closed.
- **`attrcall` literal screening (item 59)** — verified `attrcall('save'…)`, `('eval')`,
  `('__reduce__')`, `('write_to_eps')`, a bare alias, and a non-literal argument are all
  refused; benign literals like `attrcall('bruhat_le')` pass, and the runtime
  `_guarded_attrcall` re-screens with the same function, so static/runtime cannot drift.
- **Token-screen rework (item 55)** — the attribute-vs-bare split via a preceding `.` token
  mirrors the AST path; scrubbed names are removed from `sage.all` so the `bound` rescue is
  safe. Correctly stops over-rejecting `save_point`/`dump_total` while still blocking
  `obj.save_image`.
- **`inject_shorthands` + `__name__="__main__"` (item 59)** — injected names are ordinary
  mathematical shorthands; the namespace diff that trusts them is gated on the caller having
  written the injecting call, and scrubbed names cannot be injected.

## Coverage / limitations

Reviewed: the full branch source diff and all changed `src/` modules. Executed the
Sage-backed security suite and my own reproducers on SageMath 10.9 in the `sage-mcp`
container. Not independently re-audited: the unchanged pre-existing validator beyond the
lines this branch touches, and the capability of every individual callable in the 13 curated
star modules (screened by name/provenance only — see residual risk). No source files were
modified during this review.
