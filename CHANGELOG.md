# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- **Dependencies refreshed**: `hypothesis` 6.168.0 → 6.168.1 and
  `nest-asyncio2` 1.7.2 → 1.7.3, the only two upgrades available. The
  `fastmcp` cap was re-tested rather than assumed: 4.0.5 is still the newest
  release and still issues a fresh `Context.session_id` per tool call, so the
  cap holds and the ignore rules kept it held through a blanket
  `uv lock --upgrade`.

### Documentation

- **`ROADMAP.md` and `TODO.md` brought up to 0.8.4.** The test snapshot was
  eleven tests stale, and `TODO.md`'s record of completed work stopped before
  the fuzzing campaign — so the five surfaces, the four findings and the two
  that the release itself tripped over were nowhere in the live queue's
  narrative.


### Documentation

- **`SUPPORT.md` now states what this project does not have.** The OpenSSF
  Scorecard reports `Code-Review 0/10`, and that is accurate rather than a
  scoring artefact: one account opens and merges everything, including every
  security fix. `main` requires seven status checks but no approving review,
  and administrator enforcement is off. The note says so, says what the strict
  automated gates do and do not buy, and cites the case where it already cost
  something -- the v0.8.4 release failed twice on a guard written and merged
  unreviewed, which CI could not catch because the fault was in the release
  workflow itself. `tests/test_support_claims.py` fails if the disclosure is
  deleted while nothing changed, or if it overstates the protection.


### Added

- **One command to record the Zenodo DOI.** Issue #92 has been blocked on the
  GitHub-Zenodo integration; it is now enabled, and Zenodo will mint a concept
  DOI from the next published release (it does not archive retroactively, so
  0.8.4 is not covered). `scripts/set_zenodo_doi.py` writes the number into
  `CITATION.cff`, the README badge, `SUPPORT.md` and `CONTRIBUTING.md` in one
  go, and `tests/test_zenodo_doi.py` fails if the four ever disagree -- four
  hand-maintained copies of a number is the shape that drifted in
  REVIEW_ACTIONS 94 and 97. The tests are meaningful before the DOI exists
  too: they refuse a placeholder, because a placeholder renders as a real
  badge and resolves to someone else's record.


### Fixed

- **The v0.8.4 release failed on a guard added in 0.8.4 itself.**
  `docker-passagemath-manifest` assembles an index from already-pushed images
  and has never checked the repository out; the tag guard from REVIEW_ACTIONS
  88 called `scripts/check_image_tags.py` into an empty working directory, so
  the job exited 2 and `publish`, `github-release` and `mcp-registry` were
  skipped behind it. The images reached GHCR and PyPI never received 0.8.4.
  The job now checks out, and a test fails when any job runs a repository
  command without one. The dry-run dispatch exists to catch exactly this and
  was not run -- running it then found a *second* bug in the same step, which
  the first had been hiding: `--suffix "$SUFFIX"` passes `-passagemath`, and
  argparse reads a leading dash as an option name. Both are fixed, both have
  tests. See REVIEW_ACTIONS 98.


## [0.8.4] - 2026-09-22

**A security release, and the first one found mostly by machine.**

0.8.3 closed a sandbox escape that a review found. This one closes five things
a *fuzzer* found, in surfaces nothing had generated input for: the AST policy,
the codegen gates, the worker's protocol, the session keys and the monitoring
metrics. Two of them a caller could trigger by accident -- `del Integer` made
`2 + 2` fail for the rest of a session, and a malformed protocol frame killed
the worker outright, taking every variable with it.

The security fix proper is `del`: it was counted as *binding* a name, and
`_bound_names` walks unreachable code, so `if False: del eval` bought the
allowlist exemption for thirteen names. None reached execution -- the
namespace scrub and the restricted builtins held -- which is the layering
`SECURITY.md` describes working as described. The first lock is supposed to
hold too.

Two changes make the policy stricter in exchange for being honest about what
it enumerates. `latex` is callable and no longer reachable into: four of its
thirteen attributes run a LaTeX toolchain, refusing those four by name was the
shape item 79 had to abandon, and deny-by-default costs 48 corpus examples
against the 1,408 calls it keeps. The monitoring redaction became an allowlist
for the same reason.

One change goes the other way. `sage.<module>.<name>` is accepted where the
module is already a permitted star export -- the same object by a longer
name -- which recovered 284 corpus examples. Acceptance lands at **98.8908%**
against an enforced floor of 98.50%.

The rest is infrastructure that should have existed already: continuous
fuzzing of five surfaces, a documented and tested way to verify a release, a
coherent dependency pipeline, and tests that derive the numbers this project
quotes about itself rather than trusting the prose. Three of those numbers
were wrong when checked.

### Security

- **`del` counted as binding a name, which bought the allowlist exemption.**
  `_bound_names` treated `ast.Del` as creating a name, and it walks
  unreachable code, so `if False: del eval` followed by `eval("1")`
  validated -- item 37's trap, closed for the `sage` root and left open for
  every other name. Thirteen names were reachable this way, including `os`,
  `sys`, `subprocess` and `pickle`. **None of them executed:** the namespace
  scrub and the restricted builtins are the second lock and both held, which
  is the layering `SECURITY.md` describes. The first lock is supposed to hold
  too. Found by a new generative fuzz campaign over `validate_code`, not by
  review. See REVIEW_ACTIONS 90.

### Added

- **A structural guard for helpers, not just tools.** The test that keeps
  caller strings out of generated code walked only `@tool`-decorated
  functions, so a tool handing a string to a helper that interpolates it was
  invisible -- and generated code runs under `trusted_policy()`. Four helpers
  interpolate a parameter and all four are safe (three are prompts producing
  text; `_savefig_snippet` takes a dict lookup behind a `Literal`), but a
  fifth would have been found the hard way. Also fuzzes the two codegen gates
  that had not been: `_validated_identifier` and `_encode_literal`.

- **Fuzzing for the codegen gates and the worker protocol**, the two security
  surfaces the first campaign did not reach. The codegen gates are the
  higher-consequence one -- generated templates run under `trusted_policy()`,
  which permits `sage_eval` -- and two of the three return text interpolated
  **verbatim** into generated code, so the harness checks structure: no
  newline, no added statement, no call the fragment did not itself bring.
  150,000 fragments, clean. The import rewriter gained thirteen import shapes
  in the existing campaign (214,844 programs, clean) plus property tests that
  a star expands to exactly the screened names. All three harnesses run in CI
  on changes to `security.py`, `codegen.py` or `_sage_worker.py`, and a test
  fails if a harness exists that CI never runs.

- **Continuous fuzzing of the AST policy.** `fuzz/fuzz_validate.py` asserts
  that `validate_code` never raises anything but `SecurityViolation` and never
  accepts a denied name in a read position, checked against the **parsed
  tree** rather than the source text -- the first campaign to skip that
  reported `f'{{name}}'` as a bypass, which is a literal brace with no name in
  it. It runs on the Python the package requires -- 50,000 programs per pull
  request touching the policy, two million weekly. ClusterFuzzLite was wired
  up first and removed the same day: its base image ships Python 3.11, and
  PEP 701 rewrote f-string parsing in 3.12, so a coverage-guided run there
  would face a different parser for the very construct that produced this
  campaign's one false positive. `tests/test_security_property.py` now
  builds its contexts instead of listing seven of them, and
  `tests/test_fuzz_harness.py` checks the target's oracles fire on planted
  holes, because a fuzz target that cannot fail is worse than none.

- **A documented, tested way to check a release.** Three badges claimed cosign
  signing and SLSA provenance, and `SECURITY.md`'s threat model listed
  "verify signed release images" as a mitigation, but nothing said how --
  which matters more than usual here, because keyless verification fails
  outright without `--certificate-identity*`, and the pattern that makes that
  error go away fastest is `.*`, which passes for every identity Sigstore has
  ever issued. `SECURITY.md` gains *Verifying a release* with commands for the
  image signature and both provenance attestations, each run against the
  published v0.8.3 first, and the signing badges now link to it instead of to
  the workflow source. `tests/test_release_verification.py` applies the
  documented signer pattern to a real release identity and to four it must
  reject, so a loosened pattern fails review.

### Changed

- **The monitoring redaction is an allowlist, not a denylist.**
  `public_snapshot()` popped three named free-text fields and published the
  rest, so a field added to the metrics later would publish itself -- the
  enumeration shape items 79 and 92 had to abandon, guarding the leak that
  already happened twice (items 57, 58). A planted field came straight
  through it. It did not reach the wire, because pydantic ignores unknown
  keys, but that is a default rather than a decision and not the lock the
  docstring claimed. Only the listed aggregate fields are copied out now.
  See REVIEW_ACTIONS 95.

- **`latex` is callable but not reachable into.** It is not a function but an
  object with thirteen public attributes, four of which run a LaTeX
  toolchain -- `latex.has_file` ran `call("kpsewhich %s" % name, shell=True)`
  as the container user on 10.9. Those four were refused by name and the other
  nine accepted, which is the enumeration shape item 79 had to abandon for the
  `sage` tree: the list is only ever as good as the members someone thought
  of. Attribute access on `latex` is now deny-by-default. `latex(expr)` is
  untouched -- the corpus calls it 1,408 times -- and the change costs 48
  examples, all typesetting rather than mathematics (98.9037% → 98.8908%,
  floor 98.50%). **This reverses a prior deliberate relaxation:** the two
  methods `latex.extra_preamble()` and `latex.matrix_delimiters(...)` used to
  validate. See REVIEW_ACTIONS 92.

- **`sage.<module>.<name>` is accepted where the module is already a permitted
  star export.** Item 79 refused every attribute chain rooted at `sage` to
  close a sandbox escape, and that root refusal stays. What changes is a
  spelling: `from sage.rings.ideal import *` was already permitted -- the
  module passes the star-export screen as a whole -- and already binds
  `Katsura`, so `sage.rings.ideal.Katsura` names the same object by a longer
  path and grants nothing new. One table authorizes both forms, so they cannot
  drift apart. Thirteen modules were screened and admitted; `sage.env`,
  `sage.symbolic.constants` and `sage.manifolds.utilities` screened clean and
  were excluded by curation -- `sage.env` exports 75 filesystem paths, which is
  the clearest reminder yet that a clean screen is a floor and not the
  decision. Corpus acceptance 98.8340% → **98.9098%** (284 examples), floor
  98.50%.

### Fixed

- **`ROADMAP.md` said `REVIEW_ACTIONS.md` held 34 items, all closed.** It
  holds 93, numbered to 96, and two are open on purpose -- item 8 accepted,
  item 9 deferred. Wrong by nearly a factor of three and in the flattering
  direction: a reader takes "34, all closed" as finished work rather than a
  running ledger, and "all closed" turns two deliberate decisions into
  oversights. `tests/test_docs_counts.py` now derives the count from the file
  and checks the tool count, which appears in four documents at once. See
  REVIEW_ACTIONS 97.

- **Every Dependabot Python PR was red for the same structural reason.**
  `requirements-passagemath.txt` is a generated export of `uv.lock`, and the
  `pip` ecosystem scans `requirements*.txt` -- so Dependabot edited the
  derived file without touching the lock, contradicting it and failing the
  drift test every time (#141, #144, #150). The update was meaningless on its
  own terms, too: changing the export while the lock stands still makes the
  image install a set the lock does not describe. Python is now managed
  through the **`uv` ecosystem**, which updates `pyproject.toml` and
  `uv.lock`. A dependency bump has a documented second step,
  `make passagemath-lock`, and `CONTRIBUTING.md` says so.

  This fixes the incoherence but **not** the recurring red: the first PR
  after the switch still failed the drift test, because Dependabot
  regenerates the export without the project's flags (2,975 lines against
  the 2,802 a real export produces) and has no way to learn them. The
  remaining options are written up in REVIEW_ACTIONS 96.

- **One click for the second half of a dependency bump.** A
  `workflow_dispatch` workflow runs `make passagemath-lock` on a branch you
  name and pushes if the file changed, so clearing a Dependabot PR's drift
  failure no longer needs a local checkout. It is not a Dependabot event, so
  it runs with an ordinary token -- the alternatives all wanted a stored PAT
  or `pull_request_target`. It refuses to run against the default branch.
  Dependabot is also told not to write the file at all via `exclude-paths`,
  which is the documented option for this and which an earlier note in
  REVIEW_ACTIONS wrongly said did not exist. It may not take effect --
  dependabot-core#15102 reports the uv ecosystem ignoring it -- so the
  workflow is what holds. REVIEW_ACTIONS 96 records the five approaches other
  projects take and why each was not simply copied.

- **The bearer-token verifier raised where it should have refused.** A lone
  surrogate cannot be UTF-8 encoded, so `verify_token` raised
  `UnicodeEncodeError` -- a 500 from the one function whose job is answering
  yes or no. Not reachable over HTTP: header bytes decode as latin-1, and
  every byte sequence tried against a real server returned a clean 401
  (measured). It refuses now. See REVIEW_ACTIONS 94.

- **Two clients could have composed to one storage key.** Keys are
  `scope::name`, and the default workspace keys on the bare scope, so
  `key_for("A", "x")` and `key_for("A::x", "default")` both produced `A::x` --
  one client's named workspace and another's default, sharing a worker and its
  namespace. Not reachable: the scope is the MCP session id, fastmcp issues a
  hex UUID and refuses a client-supplied `Mcp-Session-Id` with 404 (measured).
  But that invariant belongs to a dependency and was asserted nowhere here,
  guarding the only thing the key scheme exists to do. The scope is now
  checked; every existing key shape and journal filename is unchanged. See
  REVIEW_ACTIONS 93.

- **The documentation said `latex` was blocked; it was offered.** `USAGE.md`
  listed it among names that "write, fetch or display" and `ROADMAP.md`
  promised callers "no `show`/`latex`/`html`". Checked name by name, ten of
  the eleven in that list were accurate and `latex` was the exception -- and
  the false claim had survived long enough to be cited as the reason for a
  curation decision in the previous release. Both documents now describe what
  the policy does, and a test fails if they drift back.

- **A star export handed back a call-only name.** The new rule exempted any
  name the caller had bound, on the shadowing principle that `latex = 1` makes
  the attributes yours. But a star export binds the *real* object, and
  `sage.schemes.toric.fano_variety` is on the curated list and re-exports
  `latex` -- so `from sage.schemes.toric.fano_variety import *` followed by
  `latex.engine` returned the genuine bound method. The exemption is now for
  names the caller **assigned**, which is what owning a value means.

- **A malformed protocol frame killed the session.** The worker's loop went
  straight to `message.get("type")`, so any well-formed JSON that is not an
  object -- `[]`, `"s"`, `3`, `null`, `true` -- raised an uncaught
  `AttributeError` and the loop died, discarding every variable in the
  session and leaving the parent a closed pipe with no reason.
  `{"type": "execute"}` with no `code` did the same through a `KeyError`.
  Frames come from `session.py`, so this was not reachable from a caller; it
  was one bug in that file away from a dead session with no diagnosis.
  Parsing is now a pure `_read_frame` that answers instead of raising. See
  REVIEW_ACTIONS 91.

- **`del Integer` broke arithmetic for the rest of the session.** Deleting a
  name the server provides was accepted, and the namespace persists between
  calls -- so after one `del Integer`, `2 + 2` failed with a `NameError`,
  because the Sage preparser rewrites every integer literal to `Integer(...)`.
  `del x` removed a predefined symbol. Deleting a provided name is now
  refused, with a message naming the assignment to use instead; deleting your
  own variables is unchanged. The asymmetry is deliberate: assignment shadows
  a name, deletion removes it. Costs 23 corpus examples, all doctests tidying
  up a local they had just assigned (98.9098% → 98.9037%, floor 98.50%).

- **A refusal that told callers to do the one thing they could not.** The
  module-reach rule said "name the function directly" for every chain, and the
  ceiling beside it recorded as settled fact that "every one of them has a
  direct spelling". Measured for the first time: of the 1,090 examples it
  refuses, **835 reach a leaf offered under no spelling at all** —
  `sage.rings.ideal.Katsura` is mathematics, and there was no `Katsura` to
  name. The message is now conditional: it names the spelling when one exists
  (`name the function directly: 'ZZ'`) and says plainly when none does. The
  one ceiling became three, counting three different things, so the false
  claim cannot re-form inside a number sized for something else. See
  REVIEW_ACTIONS 89.

- **Releases published only `vX.Y.Z` and `latest`.** `docker/metadata-action`
  ran on its defaults in both image jobs, so there was no `0.8.3` to pin a
  deployment to and no `0.8` to track for security patches -- while the chart's
  own comment tells operators to prefer a release tag over `latest`. Both jobs
  now ask for the semver tags, and `scripts/check_image_tags.py` fails the
  release between the metadata step and the push if any required tag is
  missing. The shortfall was invisible from the repository and only observable
  by pulling, and `type=semver` produces nothing on a branch, so the dry-run
  dispatch could not have caught it. v0.8.3's own tags were backfilled by hand
  and verify. See REVIEW_ACTIONS 88.

### Documentation

- **Ten of twenty-five settings were undocumented, four of them security
  toggles.** `SAGEMATH_MCP_SECURITY_NAME_ALLOWLIST` disables deny-by-default
  and `SAGEMATH_MCP_SECURITY_ALLOW_IMPORTS` re-enables imports, and neither
  appeared in any document -- switches an operator could only find by reading
  source. `SAGEMATH_MCP_PERSIST_SESSIONS` and `..._PERSIST_DIR`, which
  journal caller code to disk, were invisible too. `USAGE.md` now carries the
  full configuration reference, and `tests/test_docs_settings.py` fails when
  a setting is added without a row.

- **`USAGE.md` pointed at a `README.md` section that does not exist**, telling
  readers to find environment variables in a document that mentions none.

- **Corpus figures had drifted two releases.** The prose said 98.83% and
  98.92%; the sweep reads **98.8908%** and **98.9740%**, with 4,153 refusals
  rather than 4,366 and a suite of 1,375 tests rather than 1,320.
  `tests/test_docs_corpus_figures.py` now ties the prose to
  `doctest-corpus-stats.md` -- it caught a wrong number on its first run.

## [0.8.3] - 2026-09-20

**A security release. Upgrade if you run the server outside the container.**

An adversarial review of the whole codebase found eight issues; all eight are
fixed here. The one that matters: caller code could execute arbitrary Python
by walking the `sage` module tree, which defeated the deny-by-default policy
entirely. On the pip extra, the desktop bundle and the three client one-liners
that policy is the only boundary, so those installs had none.

Closing it cost 950 doctest-corpus examples — 99.09% to 98.83%, against an
enforced floor of 98.50% — and that trade is deliberate and declared. Every
refused example has a direct spelling, and the refusal message names it.

Two more were reachable without any credential: a second route to the same
module tree through Sage-only syntax, and no `Host`/`Origin` validation, which
let a web page drive a loopback-bound server through DNS rebinding.

A second, independent review of those eight fixes then found three fail-open
error paths **inside them** -- each falling back to the permissive behaviour
the fix had just removed. Those are fixed here too, and the release was held
for them.


### Security

- **Three fail-open error paths in this week's own security fixes.** A second,
  independent review of the eight fixes found that three of them fell back to
  the permissive behaviour when something went wrong:

  - The host/origin guard was **silently absent on the SSE transport**.
    FastMCP's legacy SSE app never reads `host_origin_protection`, so
    `--transport sse` shipped with no validation while the other two
    transports had it. The middleware is now constructed explicitly for that
    transport; a foreign `Host` on `/sse` gets 421 on shipped defaults.
  - A **lazy import that would not resolve reverted to the blind path** the
    fix existed to close: the resolution was wrapped in a suppress, so on
    failure the unresolved proxy was judged instead. It now fails the module.
    Regenerating both artifact sets produces a byte-identical file, so failing
    closed costs nothing.
  - A **reset that could not delete the persisted journal still reported
    success**, leaving the state to be replayed — the exact failure that fix
    had just removed, restored by its own error handler. It now raises and
    names the paths.

  When a security check cannot complete, the fallback must be refusal.
  `contextlib.suppress` around a security decision is the smell. See
  REVIEW_ACTIONS 87.

- **The Helm chart is hardened to match the Compose deployment.** Docker
  supplies several container controls implicitly and Kubernetes supplies none
  of them, so the chart was weaker than the documentation describing both: no
  seccomp profile, meaning pods ran **Unconfined** with the whole syscall table
  exposed to a process that executes model-written code; and the namespace's
  default ServiceAccount token projected into that container, which a
  read-only root filesystem does not stop anything reading.

  Both are now set. The chart also gains `auth.existingSecret` /
  `auth.secretKey`, so the bearer token comes from a Secret rather than a
  literal environment value that would land in the Deployment spec,
  `kubectl describe` and the release Secret — it was previously the only
  shipped deployment that puts the server on a network and had no supported way
  to set the token. Absent unless configured, since no authentication is the
  supported posture for a local run.

  The README credited both deployments with a fork ceiling; Kubernetes has no
  per-pod PID limit in the pod spec, so that sentence is corrected rather than
  a chart field invented. `tests/test_helm_chart.py` renders the chart and
  reads the result. See REVIEW_ACTIONS 86.


- **The star-export screen judged the proxy rather than the object.** It never
  resolved a `LazyImport`, which is not a `ModuleType` however module-like its
  target and proxies no `__module__` — so both of its value-based checks read
  one as harmless. `sage.graphs.generators.distance_regular` exports `codes` as
  a lazy import of a module, and it was baked into the curated star list: the
  screen handed a caller a module object, the one thing that mechanism promises
  never to do. Worse, the provenance check was blind for *every* lazy
  re-export. The screen now resolves lazy imports first, as the namespace scrub
  in the same file already did in two places. Exactly one name leaves the lists
  and there is no corpus cost, because `codes` is separately allowlisted. See
  REVIEW_ACTIONS 85.


- **`reset_sage_session` did not clear state when session persistence is on.**
  It cleared the in-memory journal and left the file on disk, and the next
  worker-backed call replayed it — so a caller who reset specifically to drop
  sensitive intermediates got them back one call later, with no signal. Reset
  now deletes the persisted journal too, legacy paths included. See
  REVIEW_ACTIONS 84.

- **The workspace token could reach an MCP notification.** `evaluate_sage`'s
  cancellation path printed its raw `session` argument, which may be the bearer
  credential `start_sage_session` promises never to expose. The masking helper
  moved to the shared strings module and `evaluate_sage` now uses it. The
  earlier regression test iterated a hand-written list of four tools, which is
  why this was missed; the new one scans every tool module instead.


- **Sage-only syntax smuggled a `sage` chain past the tool-parameter screen.**
  `sage.misc.latex.png(1,'/tmp/x.png')` was refused, but
  `[sage.misc.latex.png(1,'/tmp/x.png')..1]` was accepted: it is not valid
  Python, so it fell through the parsed path to a token screen that mirrored
  two of the policy's forbidden sets and not the third. It then reached
  `sage_eval` under the trusted policy, where `[X..1]` preparses into a range
  call and invokes `X`. Confirmed reaching the evaluator through a real tool
  call. The screen now mirrors all three sets, and `[1..5]` still works. See
  REVIEW_ACTIONS 83.


- **The HTTP transports now validate `Host` and `Origin`.** Binding to loopback
  does not keep a browser out: a page served from a domain whose DNS rebinds to
  `127.0.0.1` reaches the server as same-origin, needs no preflight, and can
  read the response. Verified before the fix — a request carrying
  `Host: attacker.example` was accepted and the whole chain, initialize through
  `tools/call`, completed. On the configuration the README recommends that was
  arbitrary evaluation and full result disclosure from a drive-by page.

  This matters more here than it would elsewhere, because running locally with
  no authentication is a supported posture: there is nothing behind the bind.

  Protection runs in `auto` mode, which validates only when the connection
  arrives over loopback — measured, not assumed, so container and Kubernetes
  deployments reached on a real address are untouched. A reverse proxy that
  talks to the server over localhost while forwarding its own `Host` needs
  `FASTMCP_HTTP_ALLOWED_HOSTS`; `SECURITY.md` documents it. See
  REVIEW_ACTIONS 82.


- **Caller code could execute arbitrary Python through the `sage` module tree.**
  Found by an adversarial review and verified against real SageMath before
  anything changed: `sage.misc.lazy_import.LazyImport('builtins','eval')('6*7')`
  returned 42, `LazyImport('subprocess','run')` handed over the callable,
  `LazyImport('builtins','open')('/etc/hostname').read()` read a file, and
  `LazyImport('os','environ')` disclosed the environment. The bare spellings
  were all correctly refused — deny-by-default worked exactly as designed and
  the dotted path walked around it.

  `sage` is on the caller allowlist, so the tree was live, and the only guard
  was a hand-written list of dangerous path segments. Ten of the thirty modules
  the worker classifies as dangerous had no listed segment and no forbidden
  leaf. The namespace scrub cannot help: it clears names from the session
  namespace and from `sage.all`, never from `sage.misc` or `sage.libs`.

  The root is now refused instead — both as the head of an attribute chain and
  as a bare name, since what comes back is a module object. Any list of segments
  is one Sage release behind; the root is not. Generated code is unaffected.

  **This cost 950 corpus examples, 99.09% → 98.83%**, against an enforced floor
  of 98.50% (passagemath: 99.17% → 98.92%), and the cost is declared with its
  own ceiling rather than absorbed.
  Every refused example has a direct spelling — `exp(1)`, not
  `sage.functions.log.exp(1)` — and the refusal message names it. A boundary,
  not a gap. See REVIEW_ACTIONS 81.

  Anyone running the server outside the container should upgrade: on the pip,
  bundle and CLI install paths this policy is the only boundary.


### Changed

- **Six more internal modules are star-importable, and corpus acceptance
  reaches 99.09%.** Each failed on exactly one re-exported helper —
  `lazy_import`, `pari` or `get_verbose` — with real mathematics behind it,
  including `sage.rings.qqbar` and its 102 names of algebraic number theory.
  That is the case the per-module drop permission was built for, and it had
  simply never been applied to them.

  This corrects the previous pass, which concluded a third was not worth doing.
  That conclusion came from re-screening the ranking and seeing which modules
  came back **clean**; it never asked why the dirty ones were dirty. "Which
  candidates screen clean" and "which candidates could be made clean" are
  different questions, and only the second finds these. Measured on SageMath
  10.9: 370,966 → 371,012 accepted, 3,462 → 3,416 refused, 99.0754% →
  **99.0877%**; on passagemath 10.8.11, 99.12% → **99.17%**. See REVIEW_ACTIONS 80.


### Fixed

- **Documentation audited against the code after three releases in two days.**
  Nineteen findings, verified individually rather than taken on trust. The ones
  that mattered:
  - `MONITORING.md`'s Prometheus exporter could not run. It pointed at a
    `scripts/metrics_exporter.py` that does not exist, passed the transport
    twice to `Client`, never entered the client as a context manager, and then
    indexed and attributed a dict as if it were a list of objects. Corrected
    and checked against a running server, where the monitoring resource returns
    a dict with exactly the six fields the exporter reads.
  - `USAGE.md` and `docs/mcp_quickstart.md` said every symbol other than
    `x, y, z, t` needs `var('w')` in `evaluate_sage`. That stopped being true
    when symbol-shaped names began auto-declaring, and one page contradicted
    itself 490 lines apart.
  - `USAGE.md` documented the plotting tools as returning
    `{"image_base64": ...}`. They return an MCP image content block; the base64
    dict is what was replaced because clients showed a wall of text.
  - `USAGE.md` told readers to make the mounted project directory writable. It
    is mounted read-only, and two other pages say so.
  - `DISTRIBUTION.md` ran `twine` from the `dev` extra, which does not contain
    it, and both it and `CONTRIBUTING.md` said the version bump touches four or
    five files. It touches eight, three of which decide which release a
    one-click install pulls.
  - `TESTING.md` listed seven CI jobs (there are eight; `passagemath` was
    missing) and its suite table omitted fourteen test files.

- **The sdist round-trip test now skips legibly instead of erroring.** With
  `--no-isolation` it builds using whatever backend is installed, and an
  environment carrying an older `hatchling` than `[build-system] requires` —
  the Sage container ships 1.29 — failed inside the build with four errors and
  a wall of log. It now checks the backend version up front and says to run
  `make sage-deps`.


### Security

- **The desktop-bundle packer is pinned.** `release.yml` and `make mcpb` ran
  `npx @anthropic-ai/mcpb@latest`. That tool runs inside the release job, and
  the bundle it produces is signed and attested a few steps later, so an
  unpinned packer meant the signature vouched for whatever npm served at that
  moment — and a format change could reach someone's desktop app without anyone
  deciding to ship it. Now pinned to 2.1.2 in both places, verified to produce
  a bundle identical to the released 0.8.2 one, so the pin changes what is
  trusted and nothing else. A test fails if the two places drift apart or if
  `@latest` comes back. OpenSSF Scorecard does not flag this, because it
  inspects `npm install` rather than `npx`.

  The three `npm install -g` lines in the nightly CLI harness stay deliberately
  unpinned, and the workflow now says why: that job exists to measure how
  today's clients behave, and it publishes nothing.


## [0.8.2] - 2026-09-17

Cut for one reason: the sdist every previous release published could not be
built from. Anyone installing from source, packaging for a distribution, or
reviewing the conda-forge recipe hit it; the wheel on PyPI was always fine, so
most users never did. It also carries a second pass at letting more of
SageMath's own mathematics through.


### Fixed

- **The published sdist could not build a wheel.** Every release since the
  typing marker was added shipped an sdist that fails with `FileNotFoundError:
  Forced include not found: src/sagemath_mcp/py.typed`, which breaks `pip
  install --no-binary :all:`, conda-forge, and any distribution packaging from
  source. The wheel on PyPI was always fine, which is why it went unnoticed:
  CI builds the wheel from the repository, where `src/` exists. `packages` was
  set on `[tool.hatch.build]`, which applies to every target, so the sdist
  rewrote `src/sagemath_mcp` to `sagemath_mcp` and then no longer matched the
  `src/...` paths in `pyproject.toml`. It is now set on the wheel target alone,
  and the sdist uses `only-include` so it keeps the source layout.

  Worth knowing for the next packaging change: simply dropping the
  `force-include` makes the build *succeed* and emit a wheel containing only
  `.dist-info` — no code, installs cleanly, fails at every import.
  `tests/test_sdist_roundtrip.py` now builds the sdist and then a wheel from
  that sdist and looks inside, which catches both. Found by submitting the
  conda-forge recipe. See REVIEW_ACTIONS 79.

### Changed

- **The conda-forge recipe is submitted, and converted to the v1 format.**
  `packaging/conda/meta.yaml` becomes `packaging/conda/recipe.yaml`:
  staged-recipes deprecated the v0 `meta.yaml` format in August 2026 and warns
  that v0 submissions are "less likely to be reviewed in a timely manner".
  Submitted as conda-forge/staged-recipes#34875 with `csteinlxbp` as the listed
  maintainer, confirmed on the pull request as their checklist requires.
  `tests/test_conda_recipe.py` now reads the recipe as YAML rather than by
  regular expression, and asserts the maintainer handle rather than leaving it
  to a copy-paste.


### Changed

- **Eighteen more internal modules are star-importable, and corpus acceptance
  reaches 99.08%.** A second pass over the same ranking item 77 used, now that
  the three big entries are gone. None of these is individually large — the
  biggest is 31 corpus examples — but together they are most of what the
  mechanism can still reach: vector calculus operators (`grad`, `div`, `curl`,
  `laplacian`), generalised quadrangles, set factories, combinatorial species,
  toric varieties and Chow groups, superpartitions, transversal matroids and
  gammoids, spinor genera, and more. Each screens clean as a whole, with no
  drop needed. Measured on SageMath 10.9: 370,837 → 370,966 accepted, 3,591 →
  3,462 refused, 99.0409% → **99.0754%**; on passagemath 10.8.11, 99.12% →
  **99.16%**.

  Three modules that screen clean are excluded anyway, by curation:
  `sage.misc.sageinspect` reads source files and returns filesystem paths,
  `sage.misc.nested_class` exports pickle helpers, and
  `sage.symbolic.random_tests` and friends are Sage's own test scaffolding,
  which would raise the number without giving a caller anything to compute
  with. The reasoning is recorded in the candidate list rather than left to be
  rediscovered. See REVIEW_ACTIONS 78.


## [0.8.1] - 2026-09-17

The first release that carries the one-click desktop bundle, and the first whose
provenance is a file on the release page rather than only a record in GitHub's
attestation store. It also accepts more of SageMath's own mathematics than any
release before it.

### Added

- **Release provenance as a file on the release page.** Every release now
  attaches `sagemath-mcp-<version>.intoto.jsonl`: the Sigstore bundle naming
  the wheel, the sdist and the `.mcpb` as its subjects, copied from the
  attestation step that already signed them and checked to cover all three. It
  verifies an artefact offline —
  `gh attestation verify <file> --owner XBP-Europe --bundle <this file>` makes
  no API call — and it is the only provenance the desktop bundle has, which is
  now attested alongside the Python artefacts. It also gives OpenSSF
  Scorecard's *Signed-Releases* check something to read: that check inspects
  release assets only, so the Cosign signatures on the GHCR digest and the PEP
  740 attestations on PyPI were invisible to it and v0.8.0 scored 0. The score
  averages the last five releases, so it climbs as releases ship rather than
  jumping.

- **README quick-start for all four clients.** *Connect an MCP client* now
  gives one command each for Claude Desktop (the bundle), Claude Code, Gemini
  CLI and Codex CLI, verified by running each `mcp add` against the real CLI.
  The commands carry no version literal, so they cannot go stale; pinning is
  documented in `USAGE.md`. It also states the three things that surprise
  people once, in one place: `uv` is required, the first launch pulls about
  1 GB of Sage wheels, and a local install has your own privileges.
- **A Gemini CLI extension (`gemini-extension.json`).** The repository is now
  installable as one: `gemini extensions install
  https://github.com/XBP-Europe/sagemath-mcp --ref vX.Y.Z`. The manifest lives
  at the root because that is where `gemini extensions install` reads it from a
  git ref, and it pins `sagemath-mcp[passagemath]==<release>` through `uvx`, so
  the extension brings a Sage runtime with the server for the same reason the
  MCPB bundle does. Validated with `gemini extensions validate`, and the `uvx
  --from … sagemath-mcp` invocation was run against the published release.
  Codex CLI has no extension or bundle format — only `codex mcp add` — so
  `USAGE.md` documents the equivalent one-liner instead of pretending otherwise.
  `scripts/bump_version.py` moves the manifest version and its pin, checked by
  `tests/test_version_consistency.py` and `tests/test_gemini_extension.py`.
- **A one-click desktop bundle (`packaging/mcpb`).** `sagemath-mcp-<version>.mcpb`
  is now built and attached to every release, so a desktop MCP host can install
  the server by opening a file. It uses the MCPB **`uv` server type**, which
  keeps the bundle at about 2 KB — three files, no vendored dependencies — and
  lets the host resolve one pin, `sagemath-mcp[passagemath]==<release>`, at first
  launch. That pin is the point: it brings a **Sage runtime** as well as the
  server, where a bundle installing only the server would start cleanly and then
  refuse every evaluation. The cost is stated in the manifest the host shows the
  user: roughly 1 GB on first launch. Platforms are macOS and Linux, excluding
  native Windows on the evidence in `docs/passagemath_evaluation.md`, where
  passagemath's Windows support is partial. `make mcpb` builds it locally;
  `mcpb pack` validates the manifest against the published schema as it packs,
  and it runs in the release's `build` job so a bad manifest fails before
  anything is published. `tests/test_mcpb_bundle.py` covers what a schema
  cannot, and `scripts/bump_version.py` moves the manifest version and the pin
  so a release cannot ship a bundle that installs the previous one.

- **A hard tier for the tool-surface measurement** (`--tier hard`, 14 cases).
  The 2026-09-15 measurement found its own case set no longer forced tools:
  frontier clients answered 60 of 63 with no MCP server at all, from recall, so
  the arms could not be compared on correctness. The new cases resist that by
  construction — long arbitrary answers (a 22-digit determinant, a 69-digit
  partition count), inputs deliberately off round numbers (`nth_prime(9999991)`,
  not `10^7`), every answer deterministic and every computation inside the
  worker's timeout. Each case carries the SageMath expression that produces its
  answer, and `test_every_hard_case_answer_is_what_sage_computes` re-derives all
  fourteen against the installed Sage, so a Sage upgrade that moves one fails
  with the case id instead of quietly scoring every model wrong.
  `EXTENDED_CASES` is unchanged, so `make cli-extended` still checks exactly the
  integration contract it always did; the tier is opted into with `--tier`, and
  `make tool-surface` now runs both. First result, against Claude Code: 4/14
  with no server, 14/14 with core tools, 14/14 with the full catalogue — the
  tier separates server from no server by +10, and shows the full catalogue
  buying nothing over `evaluate_sage` on hard mathematics.

### Changed

- **Three more internal modules are star-importable, and the corpus acceptance
  rises to 99.04%.** `sage.matroids.advanced`, `sage.combinat.matrices.latin`
  and `sage.graphs.generators.distance_regular` are Sage's own public entry
  points for their areas, and each was refused whole because it re-exports one
  piece of import machinery — `lazy_import`, `libgap` — next to the
  mathematics. Between them they accounted for 399 of the 1,642 corpus
  refusals reading *is not a name this server offers*. The screen now takes a
  per-module, reviewed permission naming exactly which helper may be dropped
  from the expansion; a *different* dangerous export still fails the module
  whole, so a future Sage stops the generator with the new name instead of
  dropping it quietly. Dropping costs the caller nothing: the namespace scrub
  deletes those names at worker start and the validator refuses them by name,
  which an integration test asserts after the star import. Measured on
  SageMath 10.9: 370,492 → 370,837 accepted, 3,936 → 3,591 refused, 98.9488%
  → **99.0409%**; on passagemath 10.8.11 the same 345 examples, 99.03% →
  **99.12%**. `scripts/analyse_corpus_refusals.py` is the analysis that
  ranked the candidates and is kept for the next pass. See REVIEW_ACTIONS 77.


- **The conda-forge recipe packages 0.8.0.** `packaging/conda/meta.yaml` now
  pins the 0.8.0 sdist and its hash, which exist on PyPI as of this release. The
  declared metadata is unchanged from 0.7.0 — same `requires-python` and the same
  three runtime dependencies — so only the version and `sha256` moved.
  `tests/test_conda_recipe.py` verifies the hash against PyPI.

### Fixed

- **The bundle step broke every dry run.** It named the output by stripping a
  leading `v` from `GITHUB_REF_NAME`, which on a `workflow_dispatch` is the
  branch: a branch with a slash in it made the path
  `bundle/sagemath-mcp-some/branch.mcpb`, a nested directory, and the `ls` on
  the next line failed the job. The `${VERSION:-0.0.0-dryrun}` fallback never
  applied, because a branch name is not empty. The version now comes from
  `GITHUB_REF_TYPE`. Found by running the dry run, which is the only thing that
  reaches this step before a tag.

- **The desktop bundle would have broken the next PyPI publish.** `mcpb pack`
  wrote `sagemath-mcp-<version>.mcpb` into `dist/`, which the publish job
  uploads with `packages-dir: dist`; twine reads the whole directory and rejects
  anything that is not a distribution (`InvalidDistribution: Unknown
  distribution format`, reproduced locally). The failure would have landed in
  the publish job — after the container images were pushed and signed — and only
  on a real tag, since a dry run skips publishing entirely. The bundle now packs
  into `bundle/` (so does `make mcpb`), the build job fails if anything but a
  wheel or an sdist is in `dist/`, and `tests/test_mcpb_bundle.py` holds both.

- **Restored the tool-surface findings dropped from `TODO.md`.** Merging the
  vendored-HTML removal resolved a rebase conflict by taking one side of a hunk
  that also held the measurement write-up, so the item read as unstarted. The
  text is back, with the hard-tier result appended.

- **SBOM attestation no longer exceeds GitHub's 16 MiB limit.** The v0.8.0 tag's
  first run pushed and signed the container image, attested its provenance, and
  then failed at `Attest image SBOM`: the SPDX document was 21.8 MB, of which
  26,120 per-file entries were 15.1 MB and their package-to-file relationships
  another 5.5 MB. Because every publish depends on that job, PyPI, the MCP
  registry and the GitHub release were skipped — the all-artefacts-or-none rule
  working as designed, on a failure that only a real tag could reveal (the
  attestation steps are gated on a push, so no dry run reaches them).
  `.syft.yaml` now turns off package-file-ownership relationships, which takes
  the same image to 4.07 MB with all 493 packages intact, and each SBOM step in
  `release.yml` checks the size before attesting so a future overflow fails
  early with a message that names the cause.

## [0.8.0] - 2026-09-16

### Security

- **The passagemath image installs with `--require-hashes`.**
  `Dockerfile.passagemath` used a plain `pip install ".[passagemath]"`, the last
  unhashed dependency install in the repository (Scorecard's Pinned-Dependencies
  remainder, #94). It now installs `requirements-passagemath.txt`, exported from
  `uv.lock` by `make passagemath-lock` with every wheel and sdist hash the lock
  knows, so pip installs exactly the locked set on amd64 and arm64 and refuses
  anything else; the project is then installed from the checkout with
  `--no-deps`. `tests/test_passagemath_lock.py` fails whenever the export and
  the lock disagree, so a pin bump or Dependabot update that forgets
  `make passagemath-lock` fails in CI, not in the image. Stated limit: pip does
  not hash-check the build dependencies it fetches for an sdist fallback (the
  arm64 `cysignals` build).
- **Workflows pinned by commit SHA, tokens least-privilege, CodeQL added.**
  The first published OpenSSF Scorecard (5.7) scored Pinned-Dependencies and
  Token-Permissions at zero. Every `uses:` in all eight workflows (73
  references) is now pinned to a commit SHA with a version comment — Dependabot
  keeps SHA pins updated — and the three Dockerfile `FROM` lines are pinned by
  index digest (tag kept for the tests that compare it with the setup scripts
  and README badge). Every workflow declares `permissions: contents: read` at
  the top; write scopes live at job level only where a step uses them
  (`issues: write` left the top level of `audit.yml` and `cli-nightly.yml`).
  A new `codeql.yml` runs CodeQL (`python` + `actions`, security-extended) on
  push, pull request and weekly. Verified with the Scorecard CLI on the tree:
  Token-Permissions 10, Pinned-Dependencies 8 (the remainder is the two `pip`
  lines in `Dockerfile.passagemath` and three `npm -g` lines in the local-only
  CLI nightly, left unpinned by hash deliberately; see TODO.md for the full
  Scorecard plan).
- **The allowlist generator classifies rather than accepts.**
  `scripts/generate_allowlist.py` used to bake in whatever survived the namespace
  scrub, inheriting every gap in it — the root cause shared by four past findings.
  It now classifies each surviving name and **fails generation** on anything it
  cannot place as mathematics: a module object from outside `sage`, or a value of
  foreign provenance not in a small reviewed set. A dangerous helper a future
  SageMath adds now stops the generator with its name, instead of being
  allowlisted silently for a probe to find later. Calibrated against real Sage so
  it is output-neutral — byte-identical output on monolithic 10.9 and passagemath
  10.8.9 — so no allowlist regeneration and no new refusals. Guarded by
  synthetic unit tests and a real-Sage integration test.

### Added

- **A conda-forge recipe, written and verified but not submitted** (#93).
  `packaging/conda/meta.yaml` packages the project for conda-forge, where Sage
  users already live: `noarch: python`, the PyPI sdist pinned by hash, the
  console script as an entry point, and a test section that runs the one command
  which works without a Sage runtime. It deliberately **does not depend on
  `sage`** — the server takes `sage` from `PATH`, the `[passagemath]` extra or
  the container, and a hard dependency would force a multi-gigabyte install on
  everyone. Buildable today: every runtime dependency is on conda-forge,
  including `fastmcp 3.4.7`, the only version satisfying the `<4` cap.
  `tests/test_conda_recipe.py` keeps it from drifting — dependencies, Python
  floor and entry point against `pyproject.toml`, and the sdist hash against
  PyPI when the network is up. Submitting it to `conda-forge/staged-recipes`
  names a maintainer publicly and is left to the repository owner;
  `packaging/conda/README.md` has the steps.
- **Tool-surface measurement (`make tool-surface`, `tool-surface-stats.md`).**
  The roadmap asserted that 40 tools are a differentiator and a reviewer
  doubted it; now it is measured. The CLI harness's 23 tool-forcing cases run
  through Claude Code, Gemini CLI and Codex in three arms: no server (enforced
  per client and observed: Claude `--tools ""`, Gemini's tool statistics, Codex's
  `--json` command-execution events), the server narrowed **on the wire** to
  `evaluate_sage` plus the session and diagnostic tools (`mcp_proxy.py
  --allow-tools` hides the rest from `tools/list` and refuses them on
  `tools/call`; unit-tested), and the full catalogue. `run_extended.py --tools
  {full,core,none} --json-out` produces the per-case results,
  `tool_surface_report.py` lays the arms side by side, comparing only
  client-cases both arms measured; a `QUOTA` status keeps a provider cut-off
  (spend limit, out of credits) from posing as a wrong answer. First result:
  frontier clients answer the set from recall without any server (60/63, Gemini
  wrong-confident 3 times), and the full catalogue is ahead of core tools by a
  few cases because dedicated tools spare the model the Sage-writing friction it
  otherwise hits — a conclusion, and a friction list, recorded in TODO.md and
  ROADMAP.md. Codex's full arm could not be measured (out of credits).
- **A native arm64 container: the passagemath image.** The primary image is
  built on `sagemath/sagemath`, which is published for `linux/amd64` only, so
  Apple-silicon and Graviton hosts ran it under emulation. `Dockerfile.passagemath`
  builds the same server on the pip-installable passagemath runtime from the
  pinned `[passagemath]` extra (`python:3.12-slim` base; a builder stage with a
  C toolchain installs into a venv the runtime stage copies, because not every
  dependency has a wheel on every architecture -- cysignals 1.12.6 shipped none
  for aarch64; the same `sage` UID/GID 1001 and writable paths, so the Compose
  file and Helm chart apply unchanged). The release builds and smoke-tests it **natively
  per architecture** (`ubuntu-latest` and `ubuntu-24.04-arm`, with Maxima and
  GAP probes on top of the stateful assign-and-read), pushes the tested images
  under `<tag>-passagemath-{amd64,arm64}`, assembles the `<tag>-passagemath`
  multi-arch index from exactly those, and signs and attests it like the
  primary image; PyPI publishes only if it succeeded too. It is the optional
  image on amd64, where the monolithic one stays primary, and the native choice
  on arm64. README, USAGE, DISTRIBUTION and SUPPORT say which to pick.
- **Release trust signals: SBOMs, SLSA provenance, explicit PEP 740, Scorecard.**
  The release workflow now generates an SPDX SBOM of the container image (from the
  exact image the smoke test ran against) and of the package's own dependency
  tree (from `uv.lock`), attaches both to the GitHub release, and attests the
  image's build provenance (SLSA, via `actions/attest-build-provenance`) and SBOM
  (`actions/attest-sbom`) to its digest on GHCR next to the Cosign signature.
  The wheel and sdist attached to the release get SLSA provenance too; PyPI's
  PEP 740 attestations, already present on 0.7.0, are now switched on explicitly.
  A new `scorecard.yml` runs the OpenSSF Scorecard weekly and on every push to
  `main`, publishing to scorecard.dev and code scanning. README gained
  Provenance, PyPI-attestations and Scorecard badges, each backed by a test that
  the workflow actually does what the badge says; `DISTRIBUTION.md` documents
  how to verify every artefact (`cosign verify`, `gh attestation verify`,
  `pypi-attestations`). Dry-run dispatches still publish and attest nothing but
  now exercise SBOM generation and check both files parse.
- **Citability and support files.** `CITATION.cff` (GitHub's *Cite this
  repository* box; what Zenodo reads to mint a release DOI) and `SUPPORT.md`
  (what "supported" means: latest release only, Python 3.12/3.13, the two Sage
  runtimes and their guarantees, tag-driven release cadence, the output-change
  minor-bump rule, and honest single-maintainer response expectations). The
  version-bump script now rewrites the citation's `version` and `date-released`,
  and `tests/test_version_consistency.py` includes the file, so a citation can
  never name an unreleased version. GitHub Discussions is enabled for questions;
  the issue-template chooser, README and CONTRIBUTING point there, and the
  README gained a *Citing* section.
- **Optional HTTP bearer-token authentication (opt-in).** Set
  `SAGEMATH_MCP_HTTP_AUTH_TOKEN=<secret>` and every MCP request over the HTTP
  transports must carry `Authorization: Bearer <secret>`; the `/health` and
  `/ready` probes stay open for load balancers. The token is compared in constant
  time (`secrets.compare_digest`) and never logged. No-auth stays the deliberate
  default — the container is the boundary, keep it on loopback (`SECURITY.md`) —
  and the server now logs a loud warning when it binds a non-loopback host with
  no token set, so the Dockerfile's container-internal `--host 0.0.0.0` is an
  explicit, noted choice. It is a single shared secret (an API key, not an OAuth
  server) that guards the transport, not a replacement for the container or TLS.
  See `src/sagemath_mcp/auth.py` and `tests/test_auth.py`.
- **passagemath CI lane and pin smoke gate.** A `passagemath` job in `ci.yml`
  cold-installs the exact `passagemath-standard==10.8.9` pin (no Docker, ~1 min)
  and runs the whole test suite against it — the real worker, the artifact-drift
  tests and the doctest corpus sweep — so it doubles as the smoke gate for
  bumping the pin: a release like 10.8.10, which broke the Maxima backend, would
  fail here rather than in a user's install. On the pin the suite is **1184
  passed / 1 skipped** and the corpus sweep measures **433,201 examples over
  3,232 files at 99.02% acceptance** (monolithic 10.9: 432,878 at 98.86%),
  clearing every floor with margin. This closes blocker (2) of the passagemath
  adoption plan (`docs/passagemath_evaluation.md`).

### Changed

- **Doctest-corpus figures refreshed to what CI measures today.** The README,
  ROADMAP, TESTING and `docs/sage_doctest_corpus.md` quoted three different
  stale acceptance rates (98.6%, 98.59%, 98.86%) for SageMath's 432,878
  documented examples. They now all say what `main` measures: **98.95%**
  (370,492 accepted, 3,936 refused, 58,268 out of scope) on SageMath 10.9 and
  **99.03%** of 433,289 on passagemath 10.8.11, with the ledger of what each
  review item cost or won back completed through items 64–65. The committed
  `doctest-corpus-stats.md` is the report from the 2026-09-14 CI run.
- **passagemath pin moved from 10.8.9 to 10.8.11.** The Maxima regression that
  kept the `[passagemath]` extra on 10.8.9 (passagemath/passagemath#2836) is
  fixed upstream: the broken 10.8.10/10.8.11 `passagemath-ecl` wheels were yanked
  and `10.8.11.post1` ships the fix, which is what `passagemath-standard==10.8.11`
  now resolves to. `solve`/`integrate`/`limit` answer again and `passagemath-gap`
  has its Linux x86_64 wheels, so the pin passes the cold-install smoke gate (the
  `passagemath` CI lane). The passagemath artifact set was regenerated against
  it and reviewed: the allowlist is byte-identical; the
  `sage.rings.polynomial.pbori.pbori` star-export list follows what the module's
  `import *` now binds (gains `ClasscallMetaclass`/`typecall`, loses
  `UniqueRepresentation`), still screened clean by `_star_export_screen`.
  10.8.11 also exports `inline_plots` from `sage.repl.interpreter`, a
  dangerous-provenance module, so it joins `commence_startup` in
  `_DANGEROUS_BARE_NAMES`: the worker strips it on passagemath, it never reaches
  the allowlist, and the entry is a no-op on monolithic Sage. The
  `make allowlist-passagemath`/`star-exports-passagemath` targets now pin Python
  3.12 like the CI lane -- on 3.13 the generator picked up the `fma` and
  `PythonFinalizationError` builtins, which the drift test on 3.12 would reject.
- **README is a front door, not a manual.** Trimmed from ~1,680 lines to ~230:
  what it is, one install-and-run path per audience (the GHCR image first, then
  PyPI, then the passagemath extra), one client config, three example prompts, a
  compact 40-tool index, a condensed architecture and security summary, and links
  out. The full per-tool reference, the "how code is interpreted" notes and the
  complete security model moved into `USAGE.md`, which is now the single manual;
  the embedded changelog is dropped in favour of `CHANGELOG.md`. The doc-honesty
  tests move with the content (every blocked module is now asserted against
  `USAGE.md`), and the tool-count and badge invariants are unchanged.

### Removed

- **The vendored Sage reference HTML (`external_docs/reference_html`).** Seven
  pages copied from doc.sagemath.org (102 KB), added early as offline reference
  material. SageMath's documentation is GPL-2.0-or-later and this repository is
  MIT and says no SageMath source is redistributed here; and nothing read the
  files — `lookup_sage_doc` and the `sagemath/docs/{scope}` resource link to
  doc.sagemath.org directly, and the directory was already kept out of the
  container image. Deleted, no replacement needed (#91).

### Fixed

- **Refusals and runtime errors name the spelling that works.** The 2026-09-15
  tool-surface measurement lost cases to a handful of exchanges in which the
  server was right and unhelpful: `partitions` and `bessel_J_zeros` refused with
  "check the spelling" (Sage never had them), `import mpmath` refused with no
  alternative named, and Sage runtime errors a model does not know how to read —
  `'float' object has no attribute 'n'` on a `numerical_integral` result,
  `unable to convert '6.62607015e-34' to a rational` from `QQ('...')`, `cannot
  approximate to a precision of 70 bits` from `.n(digits=20)` on an `RDF`, a
  `RealLiteral` "not callable" from `2.0(x)`, and the double-escaped-newline
  `SyntaxError`. Three changes: a `_SAGE_SPELLINGS` table (25 names models
  invent — the SymPy/NumPy/SciPy spellings and the two above — each answered
  with the Sage spelling, verified against real Sage by
  `test_every_sage_spelling_hint_computes`, which also fails if a future Sage
  adds one of the names); `mpmath` and `functools` in the import-alternatives
  table; and a `_RUNTIME_HINTS` table in the worker that appends a hint to the
  message of those five error shapes (type and traceback untouched, nothing
  substituted, unit-tested in pure Python and against real Sage). The first
  sentence of every refusal is unchanged, so the doctest-corpus rule table and
  its ceilings are unaffected.
- **The security-artifact drift tests validate the runtime that is installed.**
  `test_the_caller_allowlist_matches_this_sage` and
  `test_the_star_exports_match_this_sage` imported the monolithic
  `allowlist.py`/`star_exports.py` directly, so under passagemath they compared
  its 24-names-different namespace against the wrong baked set; they now go
  through `_artifacts`, which dispatches to the runtime's own set (a strict no-op
  on monolithic). `test_external_interfaces_are_not_in_the_namespace` is now
  layout-aware the same way `_dangerous_sage_names` is (REVIEW_ACTIONS 69): it
  counts a name as an interface only when its value resolves under
  `sage.interfaces`, so passagemath's modularized `sage.interfaces.all`
  re-exporting ordinary mathematics (`Integer`, `parent`, `Hom`, ...) no longer
  reads as a breach — verified no genuine interface is reachable on the pin.
- **The doctest corpus sweep runs under passagemath.** `sage_library()` derived
  the source tree from `sage.__file__`, which is `None` under passagemath's
  namespace-package layout; it now falls back to `sage.__path__`. The sweep also
  models star-imports with the runtime's own vetted set rather than always the
  monolithic one.

## [0.7.0] - 2026-09-07

A survey of the other SageMath MCP servers (a feature comparison and a
code-level read of each peer's source, 2026-08-24) drove this window, and four
rounds of external review hardened it. Nothing here is a breaking change: the
40-tool surface, the deny-by-default sandbox and the stdio/HTTP transports are
unchanged; everything added is additive (the `verify_claim` tool, MCP prompts,
the pre-warmed worker pool, portable workspace handles, image plot responses,
mutation and property testing, an outcome benchmark, and the opt-in passagemath
runtime). Highlights: `verify_claim` for checking the model's own algebra;
`pip install "sagemath-mcp[passagemath]"` as a ~1 GB alternative to the 3 GB
Sage image; and plots that render as images instead of a base64 wall.

### Added

- **passagemath as a selectable runtime (`pip install "sagemath-mcp[passagemath]"`).**
  A pip-installable, modularized fork of SageMath as an alternative to the ~3 GB
  `sagemath/sagemath` Docker image — ~1 GB download, no Docker, no local Sage
  build; `from sage.all import *` and the worker run unmodified. Both runtimes
  work: the server detects which is installed at import
  (`importlib.metadata.version("passagemath-standard")`) and dispatches to the
  matching generated security-artifact set (`_artifacts.py` →
  `allowlist_passagemath.py` / `star_exports_passagemath.py`), so the
  deny-by-default sandbox is identical on both. The extra is pinned exactly
  (`passagemath-standard==10.8.9`) because passagemath's own release QA has
  shipped broken backends (`docs/passagemath_evaluation.md` §4). Landing this
  required making the denylist derivation layout-aware (the modularized
  `sage.interfaces.all` re-exports ordinary maths, which the old derivation
  swallowed — REVIEW_ACTIONS 69) and denylisting three passagemath-only
  interface names (`Maxima`, `Mathics3`, `mathics3`) plus its `commence_startup`
  helper. Verified byte-for-byte no-op on monolithic (artifacts regenerate
  identically, all agreement tests pass) and correct on passagemath (15/15
  star-export modules screen clean, ordinary maths offered, interfaces refused,
  vetted star-imports allowed). `make allowlist-passagemath` /
  `star-exports-passagemath` regenerate its artifacts with no Docker. Remaining
  before it is a recommended path: a passagemath CI lane (integration suite +
  doctest corpus sweep against the pin) and filing the upstream `maxima_lib`
  regression.
- **Outcome benchmark.** `benchmarks/` — a fixed, seeded case set (`cases.json`,
  24 problems in five difficulty tiers, every gold answer verified in the Sage
  10.9 container) and a Workflow (`outcome_benchmark.workflow.js`) that runs it
  through the model twice, reasoning-only vs. with Sage compute, scoring every
  answer for *mathematical equivalence* in Sage (not string-matched) by an
  independent step. It measures the claim the doctest corpus cannot: do models
  get more mathematics *right* with these tools. First run (subject `haiku`,
  judge `sonnet`, `scripts/write_benchmark_stats.py` → `benchmark-stats.md`):
  **17/24 → 24/24**, the entire +7 in the compute-heavy and infeasible tiers —
  a factoring, an 8×8 determinant, a partition count — where reasoning alone
  refused six and answered one *confidently wrong*, while Sage got all ten. On
  the arithmetic/competition/advanced tiers both arms score 100%: the tool does
  not help where the model is already right, and does not hurt. A stronger
  subject model closes the gap on its own — this is as much a measurement of the
  model as of the server, so it is never CI-gated.
- **MCP prompts (3).** `prove_and_verify`, `solve_and_check` and
  `explore_object` — reusable instructions a client surfaces in its prompt
  picker, each steering the model toward what this server is good at: verifying
  its own algebra with `verify_claim`, checking a result before presenting it,
  and building an object once in a session and exploring it in `evaluate_sage`
  rather than the fresh-namespace helper tools. Almost no MCP server ships
  prompts; they are the cheapest way to shape usage.
- **Pre-warmed worker pool.** The cost of a session's first call was ~1s of
  Sage lazy initialisation (the import is cheap; the first *evaluation* is not).
  The server now keeps a small pool of spare workers, each already past that
  init, and a new session adopts one — measured **~980ms → ~2ms** on the first
  call — while the pool refills in the background. Sized by
  `SAGEMATH_MCP_WARM_POOL_SIZE` (default 1, `0` disables), never exceeding
  `SAGEMATH_MCP_MAX_SESSIONS`.
- **Portable workspace handles.** `start_sage_session` now returns a
  `workspace_token` alongside the workspace: a server-issued, unguessable bearer
  handle that addresses that one workspace independently of the transport-level
  MCP session id. Passed as any tool's `session` argument it reaches the same
  state across a reconnect — or a transport that rotates the session id per call
  (which is what the MCP spec's retirement of protocol-level sessions, and
  fastmcp 4, make the norm). Names keep their current transport-scoped behavior,
  so two clients each using `default` stay isolated. The handle is a bearer
  credential, not authentication: possession grants access, so it is unguessable
  and kept out of monitoring, listings, error messages, logs and journal
  filenames; an unknown or revoked handle is refused, never silently turned into
  a fresh workspace; and stopping or culling a workspace invalidates its handles.
  Every stateful tool and lifecycle operation (evaluate, verify, reset,
  interrupt, cancel, stop) resolves a handle through one central path. The
  `fastmcp>=3.4.7,<4` cap stays in place — this is additive, not a lift of it.
- **`verify_claim` (39 → 40).** The checking primitive from the field survey,
  for the dominant failure mode of models doing mathematics: confident wrong
  algebra. A stated claim — `integral(x^2/(e^x-1), x, 0, oo) == 2*zeta(3)` — is
  re-checked independently through a ladder: Sage's symbolic prover, the exact
  difference (`(lhs-rhs).simplify_full().is_zero()`), exact arithmetic over
  `QQbar`/`AA` for constant claims, then certified interval arithmetic and
  numeric sampling over the free variables. Verdicts are `proved`, `refuted`,
  `supported` or `undecided`, and two rules keep them honest: the prover
  returning `False` means *not proved*, never *false* — `refuted` requires an
  exact decision or an exhibited counterexample — and `supported` always
  carries its evidence (sample count, precision), never a bare confidence
  number. Several more honesty rules landed after external review. Decimal
  literals are read as the exact rationals they denote (`0.1` means 1/10, so
  `0.1 + 0.2 == 0.3` is proved and `1.0 + 1e-20 == 1.0` is refuted — deciding
  over 53-bit doubles answered both wrongly while claiming exactness), and a
  second review round closed the deeper case: a comparison whose operands are
  genuine machine floats (`RR(1)`, an `.n()` result, a session value in `RR`) is
  now reported as `supported` over inexact numbers via a new `float_comparison`
  method, never as an exact proof — `RR(1) + RR(1)/10^20 == RR(1)` is true only
  by rounding. The session's active assumptions are honored, now including
  non-substitutable domain declarations: under `assume(x, 'integer')` a sampled
  1/2 is inadmissible and never offered as a counterexample to `x != 1/2` (the
  first pass silently ignored such declarations and refuted falsely), and any
  verdict that relied on an assumption names it in the evidence. No new security
  surface: the claim passes the same fragment gate as every other tool parameter
  before touching generated code.
- **Two diagnostics tools (37 → 39).** `check_sage_health` is an MCP-level
  readiness probe for stdio clients that cannot reach the HTTP `/health` route:
  it spins up (or reuses) the workspace worker, evaluates `1+1`, and reports
  `ok`/backend/latency, reporting failure in its result rather than erroring.
  `lookup_sage_doc` returns upstream documentation links for a Sage name and —
  the part the manual cannot answer — whether this server offers that name to
  `evaluate_sage` caller code.
- **MCP annotations on every tool.** Each tool now declares
  `readOnlyHint`/`destructiveHint`/`idempotentHint`/`openWorldHint`, so a client
  can tell which calls discard state (`cancel`/`reset`/`stop`) from those that
  keep it (`interrupt`). An inventory test pins the memberships.
- **Mutation testing of the security policy.** `make mutation`
  (`scripts/run_mutation_tests.py`) drives cosmic-ray over
  `src/sagemath_mcp/security.py`: it applies each deliberate weakening — a
  flipped comparison, a dropped `not`, a relaxed `and` — and runs the security
  suite, counting how many the tests *catch*. That is a claim line coverage
  cannot make: `security.py` was already at 100% coverage and still let these
  through. The run is parallelised across HTTP workers, each mutating its own
  copy of the tree with `PYTHONPATH` shadowing the editable install, so a
  ~35-minute serial sweep finishes in ~2 minutes (`--workers`, default 8; `1`
  is the serial reference); a weekly, non-gating CI job publishes
  `mutation-stats.md`. New Hypothesis property tests
  (`tests/test_security_property.py`) assert the policy's invariants over
  generated inputs — every forbidden name in every referencing position, any
  attribute on any forbidden module, any import at all — which is what kills the
  behavioural mutants. Nine of these tests were written directly against survivors
  the first run surfaced, closing real gaps: `_is_dunder`'s length boundary and
  its `and` (the shortest path out of the sandbox), the resource limits accepted
  *at* the limit rather than only rejected past it, `forbid_global`/`forbid_nonlocal`
  firing on the right node, and the attribute-chain exemption not shielding a
  forbidden third segment (`operator.abs.os`). Score: **426/696 killed (61.2%)**;
  excluding the 209 equivalent type-annotation mutants (an `X | None` hint is a
  never-evaluated string under `from __future__ import annotations`, so no test
  can kill it), the effective score is **87.5%**. The remaining survivors are
  equivalent or near-equivalent (interned-string `==`/`is`, keyword-only `*`
  markers, `index == last` where `index <= last`), tracked in TODO.

### Changed

- **The evaluation-timeout error now coaches the retry.** Instead of a bare
  "timed out after Ns", it says the worker was restarted and variables were
  discarded, and names the fix: a larger per-call `timeout`,
  `evaluate_sage_streaming` to watch a long computation, or
  `interrupt_sage_session` to stop one while keeping its variables.

### Fixed

- **Non-finite results stay valid JSON and keep their shape** (2026-09-06
  return-shape audit). A `float('inf')`/`nan` serialises to the bare tokens
  `Infinity`/`NaN`, which are not valid JSON — a strict client rejects the whole
  response. And a result *containing* one (calculate_expression's
  `{string, numeric}` for `log(0)`) collapsed entirely to a single
  double-encoded string, because the `-inf` token in its repr defeated result
  reconstruction, dropping the documented `numeric` field. Both are fixed
  centrally, where every helper tool's result passes: reconstruction now accepts
  `inf`/`nan` at any depth via a bounded literal evaluator (no code execution),
  and non-finite floats are sent as the strings `Infinity`/`-Infinity`/`NaN`.
  The rest of the audit was already sound — large integers travel as decimal
  strings, plots as image content, and ordinary string results are fine.
- **Plots now render as images** (2026-09-06 external evaluation).
  `plot_expression`, `plot3d_expression` and `plot_multi_expression` returned
  `{"image_base64": ...}` — a JSON dict a client serialised as text, so a plot
  arrived as a ~200 KB wall of base64 that displayed nothing and ate the context
  window. They now return proper MCP image content (a `fastmcp` `Image` →
  `ImageContent`) the client renders inline, at a bounded canvas/DPI (a PNG
  dropped to ~25 KB), with a new `image_format` argument to choose SVG (vector,
  smaller for line plots) instead of PNG.
- **Slimmer, cache-friendly Docker image** (2026-09-06 external evaluation). The
  Dockerfile did `COPY . /workspace`, pulling the whole repo — tests,
  `external_docs`, the 100 KB+ review file — into the image and busting the
  install layer's cache on every edit to any of them. It now copies only the
  wheel-build inputs (`pyproject.toml`, `README.md`, `LICENSE`, `src/`), so the
  image excludes the working tree and the layer survives doc/test edits.
  Verified the built image still runs the stateful smoke and serves all 40 tools.
- **Tool count reconciled and pinned to the inventory.** The count disagreed
  across files (README 40, GitHub description 40, `server.json` "34");
  `server.json` now says 40, and a new test
  (`test_hardcoded_tool_counts_match_the_inventory`) fails if any stated count
  drifts from `tests/fixtures/tool_inventory.json`, the source of truth — so the
  next added tool points at every place to bump.
- **Honest scope language** (2026-09-06 external review). "full access to
  SageMath", "run any SageMath code" and "arbitrary SageMath code" are replaced
  across the README, USAGE and the `evaluate_sage` tool description with the
  deny-by-default subset the sandbox actually offers. The usability point the
  same review raised is fixed alongside it: that the specialized tools evaluate
  in a fresh namespace and cannot see `evaluate_sage` variables — so stateful
  multi-step work belongs in `evaluate_sage` despite its "LAST RESORT" framing —
  is now stated in the tool description the model reads and at the top of the
  `evaluate_sage` reference, not only in a note far below.
- **Session/worker robustness** (2026-09-06 external review). Four fixes:
  worker startup is now serialized by a per-session lock, closing a race where
  two simultaneous first requests to one session launched two workers and
  leaked one; a configurable ceiling (`SAGEMATH_MCP_MAX_SESSIONS`, default 128)
  bounds concurrently live workers so a client opening a workspace per call
  cannot exhaust the host, while existing sessions stay reachable; the ~30
  helper tools now record the same monitoring counters `evaluate_sage` does,
  where before they evaluated invisibly to the metrics; and readiness moved to
  a new HTTP `/ready` endpoint that evaluates `1+1` on the backend (503 when it
  cannot), with the Helm readiness probe pointed at it, so a pod whose Sage is
  unusable stops receiving traffic. `/health` stays a shallow liveness check on
  purpose — a wedged computation should not restart the pod.
- **The release now validates the artifact it publishes** (2026-09-06 external
  review). The Docker release job builds the image, runs a stateful smoke test
  inside it (assign, read back in the same session — the exact workflow fastmcp
  4.0.3 broke while every signature stayed valid), and only then pushes and
  signs; a manual `dry_run` dispatch used to push and sign a GHCR image anyway
  and now publishes nothing. A second review round found the same class of gap
  on the other destinations: PyPI, the MCP registry and the GitHub release each
  gated on `startsWith(github.ref, 'refs/tags/v')` alone, and a
  `workflow_dispatch` can target a tag ref — so a dry-run dispatch against a tag
  still satisfied them. Every publish now requires the tag **push** event under
  one shared policy, and a static test asserts no ref-only gate returns. The
  Docker job now publishes the exact image the smoke test ran against — it
  retags and pushes the tested candidate and signs it by its registry digest,
  rather than a second build that could differ from the one just verified. The
  CI compose smoke test asserted nothing about its stateful call — it printed
  the result and reported success even when the second call failed — and now
  fails unless the read-back returns 42.
- **The onboarding paths now match the security model** (2026-09-06 external
  review). The README's `docker run` example published the unauthenticated
  evaluator on every host interface while overriding the image's CMD without
  its `--host 0.0.0.0` — unsafe and non-functional at once; it now carries the
  same hardening flags as Compose and publishes on the loopback interface, and
  a lint test holds every README port mapping to that. The dev/test container
  scripts defaulted to the moving `sagemath/sagemath:latest` tag with no
  resource ceilings; they now pin the Dockerfile's Sage release (a test keeps
  the three in step), apply pids/memory limits and `no-new-privileges`, and
  say plainly that they are a development fixture, not a hardened runtime.
- **fastmcp capped below 4.** The requirement was `>=3.4.7` with no upper
  bound, so a fresh install resolved fastmcp 4.0.3 — under which the
  cache-isolation suite fails: a second client's identical tool call is not
  executed in its own session, the cross-client leak
  `tests/test_cache_isolation.py` exists to catch. Now `>=3.4.7,<4`; raising it
  is deliberate work gated on that suite (REVIEW_ACTIONS item 68).
- **Orphaned worker grandchildren.** The worker now leads its own process group
  and every hard kill goes through `os.killpg`, so helper processes Sage forks
  (the pexpect interfaces fork GAP among others) are reaped on cancel or timeout
  instead of being left to run. `interrupt` still signals only the worker, the
  way the Sage REPL forwards Ctrl-C.
- **Protocol-framing corruption from inherited descriptors.** The JSON worker
  protocol moved off descriptor 1: the pipe is duplicated to a private stream and
  descriptor 1 is pointed at stderr, so a child a Sage internal forks — or a C
  library writing to the descriptor directly — surfaces as logged noise rather
  than a corrupted response line.
- **The allowlist generator no longer bakes in the caller shims.** Regenerating
  `allowlist.py` on any Sage version had begun emitting `attrcall` and
  `set_verbose` (installed into the worker namespace after the scrub); both are
  meant to be absent, and three tests enforce it. The generator now subtracts the
  shims.
- **Workspace tokens no longer leak into logs** (2026-09-07 external review,
  REVIEW_ACTIONS 70). `reset`/`interrupt`/`cancel`/`stop` interpolated the
  caller's `session` argument — now a bearer `workspace_token` — into MCP
  notifications and responses, contrary to the secrecy the handle promises. A
  token is shown as the generic label `the workspace`; only names appear.
- **`verify_claim` enforces exactness on every proof path** (2026-09-07
  external review, REVIEW_ACTIONS 71, 73, 75). A rounded result wrapped in a
  list, a symbolic expression, a dict key, a bare predicate
  (`(RR(1)+RR(1)/10^20-RR(1)).is_zero()`), or that predicate wrapped in `== True`
  or a lambda, was still reported `proved/exact`. Exactness is now judged from a
  claim's inputs, not its collapsed value: every value-bearing sub-expression is
  evaluated from its original source (so Python's bit-xor precedence for `^`, and
  UTF-8-byte-vs-character offsets for non-ASCII like `α`, can neither corrupt nor
  crash a claim) and any machine number among them blocks an exact rung. The
  session's active assumptions are attached centrally — a structured
  `assumptions` field and the evidence — so no branch can conceal them.
- **Warm pool holds its ceiling and reclaims cancelled workers** (2026-09-07
  external review, REVIEW_ACTIONS 72, 74, 76). Total-worker accounting (live
  sessions + pool + in-flight refills) is shared, so a refill can no longer
  overshoot `SAGEMATH_MCP_MAX_SESSIONS`; and a cancelled refill's worker is
  reclaimed to completion by a manager-owned cleanup that survives cancellation
  of the request that triggered it — rather than being dropped from tracking
  while still alive — before its slot is reused.

### Removed

- **`smithery.yaml`.** Smithery's post-Arcade.dev publish flow accepts only a
  public HTTPS endpoint, so the GitHub/`smithery.yaml` connect the file existed
  for no longer exists; listing there would require hosting a public,
  authenticated code-execution endpoint against the local-only posture in
  `SECURITY.md`. Distribution is covered by the official MCP registry
  (`io.github.XBP-Europe/sagemath-mcp`) and Glama.

### Tests

- Covered sympy-mcp's entire self-demonstration (calculus, linear algebra, the
  damped oscillator, a coupled two-tank ODE system checked against its algebraic
  steady state, general relativity via SageManifolds, units) and the peer field's
  lattice-reduction and GAP-structure workloads as end-to-end use cases — all
  through `evaluate_sage` in one carried-over session.

## [0.6.1] - 2026-08-16

A security patch on 0.6.0. It closes a critical sandbox escape introduced by the
curated `import *` feature, hardens the validator against the same class, stops a
cross-client information leak in the monitoring resource, and — safely — reduces
how often the guardrails refuse legitimate SageMath mathematics (doctest-corpus
acceptance 98.69% → 98.95%).

### Security

- **Curated `import *` allowed arbitrary command execution (critical).** The
  screen that vets an internal module for `from <module> import *` decided
  provenance from each value's `__module__`, but a module object has none, so a
  re-exported module passed — `sage.modular.dims` exports `dirichlet`. A bound
  module object is a pivot into the whole `sage.*` tree, and the validator's
  terminal-attribute rule then treated `alias.os` under a caller-bound root as a
  benign method, so
  `from sage.modular.dims import *; dirichlet.free_module_element.sage.env.os.system('id')`
  ran a shell as the container user. The screen now drops module-object exports
  and the validator refuses a terminal module name under any root; both are
  covered by regression tests that fail against the unpatched code. (review
  items 61, 62, 63)
- **The monitoring resource leaked another client's inputs and outputs.** The
  `resource://sagemath/monitoring/{scope}` snapshot carried the last failing
  evaluation's error message, rejected code and untruncated stdout, and
  `_METRICS` is a process-global singleton, so any client could read another
  client's data over the shipped HTTP deployment. Those free-text fields are
  dropped before the snapshot leaves the process; only non-identifying aggregate
  counters remain. (review item 58)

### Added

- Caller code may now `from <module> import *` for a curated set of internal
  SageMath modules whose public names are all ordinary mathematics, screened
  clean as a whole and generated into `star_exports.py`. Nothing is added to the
  allowlist. (review items 60, 63)
- `evaluate_sage` auto-declares symbol-shaped free names (`w`, `x_2`, `alpha`)
  as symbols, matching SageMath's SR and the specialised tools, instead of
  refusing them. Narrow and typo-guarded: multi-letter names stay errors, and a
  session variable is never turned back into a symbol. (review item 65)

### Changed

- `set_verbose` is offered to caller code as a no-op — it only sets a global
  verbosity level, which has no surface over MCP — rather than refused. (review
  item 64)
- `inject_shorthands` is simulated so the names it creates are readable in the
  session, and a literal `attrcall('method')` is accepted once its name is
  screened against the same rules the dotted spelling would face. (review item 59)
- `doctest-corpus-stats.md` is tracked in the repository (counts only, never
  corpus text) so a guardrail change's effect on the acceptance rate is visible
  in review.

### Fixed

- The guarded `attrcall` wrapper was stripped by the namespace reseal and never
  reinstalled, so `attrcall` silently stopped working after the first
  specialised-tool call in a session. Caller shims are now reinstalled after
  every reseal. (review item 64)

## [0.6.0] - 2026-08-15

A security and correctness release, and a large one. `evaluate_sage` now
runs SageMath rather than Python, caller code is checked against a
deny-by-default allowlist, and a run of sandbox escapes found over the course
of the work were each closed with a regression test. It is a **minor bump
rather than a patch** because caller-visible behaviour changes: `2^3` is 8,
`x`/`y`/`z`/`t` are predefined, and callers can no longer import, reach the
external CAS interfaces, or call `show`/`view`/`latex`/`html`.

### Security

- **A forbidden attribute could be reached by alias.** The rule fired only when
  the attribute was the callee, so `f = latex.has_file; f(payload)` passed
  validation and ran a shell — as did the list, tuple, dict and lambda-default
  spellings. Reaching the attribute is the capability, so the check moved to the
  attribute node. Older and wider than the `latex` methods: `popen`, `rmtree`
  and the `spawn*` family had been guarded the same call-only way for far
  longer. No new over-block — the doctest corpus still passes.
- **Re-offering `latex` handed over a shell (remote code execution).**
  `Latex.has_file(name)` runs `call("kpsewhich %s" % name, shell=True)`, so
  `latex.has_file('x; id > /tmp/x')` executed a command as the container user;
  `check_file` and `add_package_to_preamble_if_available` reach it too. The name
  had been re-offered on the reasoning that `latex(...)` builds a string — true
  of the call, and not of the object, since allowlisting a name hands over every
  method on it. The three methods are refused by name, `latex(obj)` and its
  string-building methods still work, and the first, broader fix was rejected
  because it refused 56 examples from SageMath's own doctests.
- **A caller could reserve a name for a tool to fill.** Binding a template's
  internal in dead code (`if False: _fig = 1`) marked it as the caller's own, so
  the object a later tool call built arrived under a name already exempt from
  being withheld — a live `matplotlib` Figure, the BytesIO holding the plot PNG,
  and the prelude's symbol table. No capability was reachable through them, but
  holding trusted code's objects is the wrong side of the invariant. Whatever
  trusted execution introduces is now withheld regardless of what the caller
  claimed first — determined from the generated code's own AST as well as from
  a namespace diff, since the diff alone is blind to trusted code *overwriting*
  a name the caller had legitimately created, and the AST alone cannot see what
  `from sage.all import *` brings in.
- **`write_*` methods wrote caller-chosen files.**
  `graphs.PetersenGraph().write_to_eps(path)` and
  `Polyhedron().write_cdd_Hrepresentation(path)` each wrote to disk — the same
  capability `save*`, `dump*` and `export*` were forbidden for, under a name
  none of them covered. `write` is now the fourth forbidden attribute prefix;
  plotting is unaffected, since the templates render through
  `.savefig(BytesIO)` under the trusted policy, which clears these prefixes.
  Found by auditing the factory guard rather than the code it guards: it had
  been skipping every callable whose parameters are all optional, which hid 225
  factories. The guard now covers anything callable with no arguments, matches
  capability words against name segments rather than substrings, and accepts a
  baseline of 37 mathematical collisions so anything new fails.
- **A specialised tool call reopened the scrubbed namespace (remote code
  execution).** The generated prelude runs `from sage.all import *` in the same
  persistent namespace as caller code, restoring every name the startup scrub
  had removed. `unpickle_global` is guarded by that scrub alone, so after any
  tool call a caller who had bound the name in dead code could reach it:
  `unpickle_global('os', 'system')` ran a shell as the container user. The
  namespace is now **resealed after trusted execution** rather than only at
  startup — both scrubs re-applied and the withheld set re-taken — because a
  snapshot cannot cover names that appear later. Caller-created names are
  preserved. The reseal runs in a `finally`, so it covers a tool call that
  raises or is interrupted as well as one that succeeds: the prelude runs first,
  so a failing call has already repopulated the namespace by the time it fails,
  and sealing only on success left every failing call holding the door open.
- **A caller binding can no longer authorize a name that already exists.**
  Binding is judged statically, so `leaked = smuggled(); smuggled = None`
  authorized reading `smuggled` at the start of the module, where it still held
  whatever the namespace had put there — a preloaded object from a custom
  `SAGEMATH_MCP_STARTUP` executed. Splitting it across two calls worked too,
  with the binding in a statement that raised before assigning. The rule is now
  general: a name that is live but not offered is refused whatever authorizes
  it, which is what the earlier dunder-only fix should have been. Not reachable
  by an untrusted caller on a default deployment, since the startup is operator
  configuration — but the same hole opens with no custom startup at all if a
  SageMath upgrade lands before `make allowlist` is rerun.
- **The rich-output subsystem is fully closed.** `get_display_manager` and
  `pretty_print` were the last live names from `sage.repl.rich_output`, joining
  `show` and `view` — removed by provenance this time, which also took
  `DisplayManager` and `restricted_output`. The manager hands back an object
  carrying `switch_backend` and `graphics_from_save`; neither is exploitable on
  10.9 (no backend class is reachable, and `graphics_from_save` can only invoke
  a callable the caller could already call), but none of it has a purpose over
  MCP. Plotting and `want_latex` are unaffected.
- **A structural guard for objects returned by allowlisted factories.** The
  allowlist governs names; an object's methods are governed only by the
  attribute rules, so a factory handing back a rich object is a route no name
  check can see. A test now calls every allowlisted zero-argument factory and
  fails if the result exposes a method matching a capability word.
- **Sage's own string-path primitives are refused.** The previous round blocked
  Python's `operator.attrgetter` and left SageMath's equivalents in place.
  `attrcall('save', path)(M)`, `raw_getattr(M, 'save')(M, path)` and
  `getattr_debug(M, 'save')(path)` each wrote a real file, and `getattr_debug`
  is a full `getattr` equivalent that reached
  `__class__.__base__.__subclasses__()`. A source scan cannot find this class of
  helper — 807 of the 1902 allowlisted names are compiled Cython with no
  readable source — so the fix is by provenance: `sage.misc.call`,
  `sage.cpython.getattr` and `sage.cpython.debug` are scrubbed wholesale, which
  also caught `getattr_from_other_class` and `dir_with_other_class` that nobody
  had named.
- **`make denylist`.** Adding a module to `_DANGEROUS_SAGE_MODULES` used to
  remove nothing until a hand-maintained baked list was updated, and there was
  no command to update it — which is why `sage.misc.call` was added and
  `attrcall` stayed reachable. The drift test now names the command.
- **String-path attribute access is refused.** Every attribute rule in this
  server is enforced on the AST, and `operator.attrgetter` takes its path as a
  runtime string the AST never sees — so
  `operator.attrgetter("misc.persist.unpickle_global")(sage)` returned the real
  function, which is arbitrary code execution, and
  `operator.attrgetter("__builtins__")(warnings)` returned the builtins dict.
  Sage binds 22 module objects including `sage` itself, so one such primitive
  reaches the whole tree; `getattr`, `setattr` and `vars` were already refused,
  which left `operator` as the only way in. `attrgetter`, `methodcaller` and
  `itemgetter` are now forbidden calls and `operator` a forbidden attribute
  parent.
- **A dangerous-module entry that removed nothing.** `sage.libs.pari.all` was
  listed after `pari` was found to run a shell, and contributed zero names: the
  derivation takes only names *defined* in a module, and PARI's are defined in
  `cypari2`. The removal that worked was the explicit one. An integration test
  now fails on any provenance entry matching no names, so an entry that looks
  like protection and is not cannot be added silently.
- **`pari` executed shell commands.** `pari('system("id > /tmp/x")')` wrote a
  file as the container user. The scrub that removed `gp` and `maxima` works
  from `sage.interfaces.all`, and the PARI *library* interface comes from
  `sage.libs.pari`, so it was never covered.
- **`oeis` reached the network**, and `install_doc`, `show`, `view`, `animate`,
  `html` and `latex` each wrote to disk or read the installation. All are
  removed from the caller namespace. Plotting and LaTeX output are unaffected:
  the plot tools render through `.savefig(BytesIO)`, and `latex` is imported
  from `sage.all` inside the worker rather than read from that namespace.
- **Caller code is checked against an allowlist.** A name may be read only if
  this server offers it: the mathematical names SageMath preloads, the safe
  builtins, and whatever the caller defines itself -- including names created
  earlier in the same session, which the worker reports so stateful use keeps
  working. Everything else is refused. Seven bypasses in two days were each a
  name nobody had forbidden, and this changes the default for the next one: a
  helper a future SageMath adds is denied until someone reviews it. An
  integration test, plus a weekly scheduled job, fails when the allowlist and the
  installed Sage disagree.

  Tool *parameters* keep the previous rules and are not allowlisted -- they name
  things valid in a template's context (`HammingCode` inside `codes.`), and the
  denylist, import ban and persistence rules all still apply to them.
- **A caller binding can no longer authorize a dunder.** Names the caller's own
  code binds are trusted without consulting the allowlist, and binding is judged
  statically — `if False: __builtins__ = 1` counts, as does `except ValueError as
  __builtins__`, which never names the object. Every name live in the worker
  namespace is allowlisted except nine dunders, and `__builtins__['__import__']
  ('os')` is a shell. Reading a dunder was already blocked by its own rule, so
  this was the second lock rather than the first; bindings now drop dunders so
  the allowlist does not depend on a rule enforced elsewhere. The drift test
  checks the shape of the gap rather than filtering it out of the comparison.
- **Caller code can no longer import anything.** `sage.*` was allowlisted for the
  generated prelude, and callers used it to re-import every helper the worker
  namespace scrub had removed: `from sage.misc.cython import compile_and_load`
  compiled and loaded a module, `from sage.interfaces.gp import Gp` spawned GP,
  and `unpickle_global('os', 'system')('id')` ran a shell command. The allowlist
  now belongs to the generated templates alone. **Breaking for callers who
  imported** — `import math`, `from sage.all import factorial` — but the names are
  already in the namespace without them.
- **Caller code cannot write files.** `.save()` was blocked; `.dump()`,
  `.save_image()` and `.export_jmol()` were not, and each wrote a real file.
  Persistence is matched by prefix (`save*`, `dump*`, `export*`) for callers; the
  plot templates keep `.savefig(BytesIO)`.
- **Sage's external CAS interfaces are no longer reachable.** `gp` and `maxima`
  both executed shell commands through their own `system` escapes --
  `gp('system("id > /tmp/x")')` wrote a file as the container user. Everything
  `sage.interfaces.all` exports is removed from the worker namespace, so a
  future Sage release adding an interface is covered without anyone updating a
  list. The libraries are untouched: Gröbner bases still go through libsingular
  and factoring through PARI, in-process.
- **Sage helpers that execute, compile, fetch or write are removed by
  provenance.** `cython(get_remote_file(url))` was download, compile and execute
  in one expression; `sh()` runs a shell; `loads` is code execution from bytes.
  Names from fifteen modules are stripped at worker startup, which covers the
  helper nobody has thought of yet. Doing this by walking the namespace instead
  forced every lazy import to resolve and put 1.8s into the first evaluation, so
  it resolves only those modules.
- **Forbidden functions are blocked through attribute chains.**
  `sage.misc.sage_eval.sage_eval("__import__('os').getuid()")` returned the
  container uid: the name checks looked at bare names and call targets, and
  `sage` is an allowed import root, so the same function was reachable one dot
  further along. The final name is what is checked now, however it is spelled.
- **`load()` and `attach()` are forbidden for callers.** They execute whatever
  path they are given and `load()` accepts a URL, so this was remote code
  execution from a name no rule mentioned.
- **`docker compose up` no longer publishes on every interface.** The port
  mapping was `8314:8314`, which binds all interfaces on the host; the server
  evaluates code and authenticates nobody, so following the quickstart put an
  unauthenticated Sage evaluator on the local network. It now publishes to
  `127.0.0.1:8314`, and a test fails if that widens again. Every other default
  was already loopback (stdio transport, `--host 127.0.0.1`, `ClusterIP`
  service), which is what made the compose mapping stand out.
- `USAGE.md` showed `--host 0.0.0.0` without qualification. It is correct inside
  a container, where the published port decides reachability, and wrong on a
  host; that distinction is now stated where the command appears.

### Changed

- **`x`, `y`, `z` and `t` are now predefined for caller code.** Sage's REPL
  predefines `x` alone, but the specialised tools have always declared four in
  their prelude, so `differentiate_expression("x^2*y^3")` worked while the same
  mathematics through `evaluate_sage` failed. Both paths now read one constant
  (`symbols.PREDEFINED_SYMBOLS`), with a test asserting they agree. Four and no
  more: `y`, `z` and `t` are unbound in a fresh Sage namespace, whereas `n` and
  `i` are numerical approximation and the Gaussian imaginary unit. A mistyped
  `y` now becomes a symbolic variable rather than an error, which is already
  true of `x` in Sage.
- **`evaluate_sage` now runs SageMath, not Python.** Caller code goes through
  Sage's preparser, as the Sage REPL does, so `2^3` is 8 rather than 1, integer
  literals are Sage `Integer`s, generator syntax like `K.<a> = NumberField(...)`
  parses, and `x` is predefined. The tool advertised "SageMath code" and executed
  plain Python; five of the seven examples in its own description could not run.
  The specialised tools have always preparsed via `sage_eval`, so the two halves
  of the server disagreed about which language they accepted.

  **This changes results for anyone relying on `^` meaning XOR.** Use `^^` for
  XOR, as in Sage. Server-generated templates are deliberately not preparsed.

  Validation reads the preparsed source, so the sandbox is unaffected: payloads
  hidden behind preparser-only syntax are rejected like any other.

### Added

- **The specialised tools declare a symbol on sight, the way `SR` does.**
  `simplify_expression("w^2 + w^2")` answers `2*w^2` where it used to fail, and
  `expand_expression("(θ + φ)^2")` answers in the letters you wrote. The rule is
  SageMath's own and it is two rules, not one: `w + 1` typed as *code* is a
  `NameError` in Sage as it is here, while `SR("a*b + a")` — a string parsed
  into the symbolic ring — creates `a` and `b`. The tools take an expression as
  a string, so they follow the second; `evaluate_sage` is code and still refuses
  with the message that names `var('w')`.

  Narrower than `SR` in the way that matters. `SR` invents any identifier, so
  `SR("sinn(x)")` returns `sinn(x)` and `SR("pi2*2")` returns `2*pi2` — a typo
  becomes a symbol and the caller gets a confident wrong answer. Only
  symbol-shaped names are declared: a letter with an optional index, a
  spelled-out Greek name, or a Greek letter. `sinn`, `foobar` and `pi2` are
  still errors.

  Names SageMath already defines are never shadowed, which took two goes to get
  right. The first version used `str.isalpha()` and declared a fresh `π`,
  turning `π.n()` into "cannot evaluate symbolic expression numerically" — the
  generated check was more permissive than the `_SYMBOL_SHAPE` regex it was
  meant to mirror, which is ASCII-only. The Greek letters come back through the
  allowlist instead, so `π`, `σ`, `ζ`, `Γ` and `ψ` keep their meanings — pi, the
  divisor sum, zeta, gamma and digamma — and the other twenty-four declare.
- **A sequence of matrices is laid out the way Sage lays it out.** `repr`
  stacks a basis one matrix after another; Sage prints them side by side, in
  columns, and for eight 3×3 matrices that is 4 lines against 32. It matters for
  a server whose entire output is text, and it was invisible until the doctests
  were *executed* rather than validated — it was the only class of disagreement
  left in that suite. The layout is Sage's own `format_list` under Sage's own
  condition: an element has to opt in through `_repr_option('ascii_art')` or its
  parent's `element_ascii_art`. Matrices do, morphisms do not, and SageMath's
  doctests record both — approximating that rule instead of reading it was wrong
  twice before the gate was right.
- **SageMath's doctests are executed now, not only validated.**
  `tests/test_sage_doctest_execution.py` runs a deterministic sample of the
  corpus through a real session and compares what comes back against the output
  Sage documents, using SageMath's own `SageOutputChecker` so the `...` ellipsis
  and `# tol` semantics are the ones the corpus was written against. Measured
  against 10.9: 400 docstrings, 2,163 examples, 1,259 comparable, **100%
  agreement, no mismatches and no unexpected errors**. It is opt-in and sampled
  — 26 examples a second against 9,000 for validation, so the whole corpus is
  about three and a half hours — and runs as `make doctest-execution`, never on
  the pull-request path.

  Five conventions had to be understood before the number meant anything, each
  of which produced a false failure first: a `Traceback` block is an assertion
  rather than an error; excluding an example must mean *do not compare* and
  never *do not execute*, or a later line is checked against a namespace that
  never got the earlier one's effect; `doctest:`-emitted warnings arrive on our
  stderr; `# todo: not implemented` marks an answer that is deliberately wrong;
  and Sage's REPL lays a sequence of matrices out in columns where this server
  stacks them. The last is a real difference in what a caller sees and is on the
  queue rather than hidden — the harness skips those comparisons so the gap is
  measured.
- **Two suites of the workload this server exists for.**
  `test_numerical_workflows.py` covers floating point, where a model's answer is
  not imprecise but confidently wrong: catastrophic cancellation in the
  quadratic formula, a 12×12 Hilbert solve with no correct digit and a residual
  that looks fine, Newton's quadratic convergence measured rather than claimed,
  a grid-refinement check that the finite-difference Laplacian really is
  second-order, the CFL limit crossed, Robertson's stiff kinetics returning NaN
  under an explicit step, and a quadrature error estimate that is accurate about
  the wrong domain. `test_physics_workflows.py` runs sessions that end at a
  number with an external referee — Wien's constant and the Sun's temperature
  from Planck's law, the Stefan–Boltzmann constant to eleven digits, Mercury's
  43″ per century from the Schwarzschild orbit equation, the oscillator ladder
  by finite differences, the anharmonic oscillator where the perturbation series
  goes negative and diagonalisation does not, phonon modes against the closed
  form, Maxwell's equations on a plane wave, the Bohr radius and 1/α from CODATA,
  a decay fit by two independent methods, and the double pendulum's energy
  conservation and sensitivity. 17 tests, ~17s against SageMath 10.9.
- **Every refusal without a security justification is gone**, found by
  categorising all 8,218 that SageMath's doctest corpus provokes and fixed
  test-first with every bypass payload still refused. Corpus acceptance went
  from 97.81% to **98.60%** — 2,960 refusals removed, a 36% reduction — and the
  allowlist gained exactly two names.
  - **`latex(...)` works again** (1,387 refusals). It was scrubbed alongside
    `show`/`view`/`html`, which write files; it builds a string. `latex.eval()`
    runs the toolchain and is still refused, by the rule that forbids `eval` as
    an attribute.
  - **A forbidden global no longer shadows an ordinary local or method** (575).
    `A.trace()` is the trace of a matrix, `l.remove(x)` is a list, and `db`,
    `gap`, `maxima` and `sh` are what people call their variables. Those names
    are absent from both the namespace and the allowlist, so an unbound read is
    still refused and a caller's binding is their own value — now asserted, in
    the unit suite and against the real namespace. `sage.misc.sh.sh('id')` and
    `sage.misc.trace.trace(code)` are cut as attribute *paths* instead, which is
    where they live.
  - **`operator.le` and the other arithmetic and comparison functions** (206).
    The module stays forbidden and a named subset is let through, so
    `Poset((divisors(30), operator.le))` works while `operator.attrgetter`,
    `operator.setitem` and `m = operator` do not.
  - **`_` holds the previous result** (694), as in every REPL Sage ships. Caller
    code only: a tool call in between cannot move it.
  - **`eval`, `vars`, `locals` and `input` are usable as identifiers** (38) —
    an eigenvalue, a list of variables, an automaton's input word, a dictionary.
    Each is absent from the restricted builtins, the worker namespace *and* the
    allowlist, so the bare name resolved to nothing and the ban bought only a
    message; a test asserts all three absences. `latex.eval()` is the
    demonstrated danger and stays refused, as an attribute. `getattr` stays
    fully forbidden — it really is in the builtins, because Sage needs it.
  - **`.system()` is a method again** (26) — the system of ODEs of a geodesic.
    It was forbidden for `os.system`, and `os` cannot be spelled at all.
- **SageMath's own doctests, run against the validator.**
  `tests/test_sage_doctest_corpus.py` harvests every `sage: ` example in the
  installed SageMath — 432,878 of them across 3,168 sources — and pushes each
  through `preparse` + `validate_module`, grouped by docstring so names bound
  early in a block authorise reads later, as a session does. It answers at scale
  the question a hand-written table can only sample: *would this server refuse
  the mathematics SageMath itself documents?* Against 10.9, in 48 seconds:
  **97.81% of in-scope examples accepted**, every refusal attributable to a rule
  that is named and capped in the file, and no allowlist gap in any mathematical
  name. The corpus is SageMath's, GPL-2.0-or-later, read at run time and never
  copied into this repository — only counts reach the assertions.
- **`scripts/analyse_doctest_refusals.py`**, which categorises the 8,218
  refusals by whether the security justification holds: 35.8% deliberate and
  sound, 29.4% not ours at all, and **a third with no strong justification** —
  `latex(...)` at 1,387, the forbidden-global-shadows-a-local class at 783, the
  REPL's `_` at 694, and `operator.le` at 206. Recorded as items 45 and 46.
- **Nine CLI cases in the new `numerics` and `physics` domains**, chosen so the
  memorable answer is the wrong one — π²/6 against a sum truncated at 10⁶, `0.5`
  against a discretised oscillator, 43″ against Mercury's 42.98. Run with
  `--domain numerics,physics`.
- The extended CLI runner distinguishes `DODGED` from `WRONG_ANSWER`, using the
  `forbidden` markers each case already carried and nothing read.
- **The runner reports what the server actually said.** `TOOL_ERROR` used to
  print "the server returned isError for a tool call", so every diagnosis meant
  re-running with the temporary wire log kept. It now quotes the message, which
  turned three opaque Gemini failures into one word — `import` — on the first
  read.
- **A failed call whose *mathematics* Sage rejected no longer fails the case.**
  A divergent integral, a bracket with no sign change, an unevaluated `limit()`
  that `N()` cannot reduce: the model tries something else and answers
  correctly, which is a session working. Refusals, dead workers and timeouts
  stay fatal whatever happens afterwards — those are the defects this suite
  exists to catch — and nothing passes without an accepted tool that succeeded
  and the expected answer.
- **The sdist shipped one file of documentation, not eight.** `MANIFEST.in`
  listed `USAGE.md`, `TESTING.md`, `AGENTS.md`, `INSTALLATION.md` and everything
  under `docs/`, and had no effect: the build backend is hatchling, which does
  not read `MANIFEST.in`. Every sdist contained `README.md` alone while
  `DISTRIBUTION.md` and `build_release.py` both said documentation was included.
  The file list moved to `[tool.hatch.build.targets.sdist]`, where it works, and
  `MANIFEST.in` is deleted rather than left looking authoritative.
- **A research-workflow suite** (`tests/test_research_workflows.py`): nine
  multi-step sessions at genuinely open problems — Collatz, Goldbach and its
  weak form, twin primes and Legendre, odd perfect numbers, the Riemann
  hypothesis, Birch–Swinnerton-Dyer, Erdős–Straus, sums of three cubes, and abc.
  They test the *session* rather than the call: a helper defined in step one is
  used in step five, which is both what distinguishes this server from a
  stateless evaluator and the strongest stress on deny-by-default caller code,
  since a mathematician writes loops, comprehensions and helper functions
  freely. Assertions prefer invariants over remembered constants. 7 s in the
  integration suite.
- **Five open-problem CLI cases** driving a real Claude/Gemini/Codex against the
  server: twin-prime counts below 10^6, the Collatz record holder below 10^5,
  the largest prime gap below 10^6, amicable pairs, and a curve's rank and
  conductor. Every answer needs a real sweep, so a model that skips the server
  cannot bluff past the wire-log check.
- **A suite for mathematics that must work** (`tests/test_math_coverage.py`).
  The security suite asserts things are blocked, so a policy that refused
  everything would pass all of it. This covers the opposite failure, in six
  layers: 34 binding forms, the same forms across calls, 72 mathematical truths
  Sage itself evaluates, 19 groups of equivalent spellings that must agree, 17
  preparser forms, and allowlist reachability by area with a size floor. Layers
  that need no Sage run in the fast job, because that is where allowlist
  regressions come from.

### Fixed

- **`nonlocal` and `global` are permitted, the input limits admit a matrix, and
  a withheld name says which spelling works.** All three came out of reading the
  doctest corpus's refusals as a work queue rather than an audit.
  - `nonlocal` rebinds a name in an enclosing *function*, so it cannot reach the
    worker namespace at all; it was refused by a policy flag with no comment, no
    recorded rationale and no test named for it, and the cost was every closure
    that accumulates something. `global` followed a round later, once its own
    question was answered: it binds at module scope, but `SR = 5` is permitted
    at the top level anyway, so the declaration cannot be what makes it
    dangerous. Verified against 10.9 — `global unpickle_global` claims a name
    whose object was scrubbed and reads back a `NameError`, while `cython`,
    `attrcall` and `sage_input` stay refused by name.
  - `max_source_chars` rose from 8,000 to 131,072 and `max_ast_nodes` from 2,500
    to 50,000. A 40×40 integer matrix is 17,706 characters and 6,497 nodes
    *after preparsing* — Sage wraps every literal as `Integer(0)` — so a matrix
    small enough to paste was refused before anything looked at it, and raising
    only the character limit would have left the node limit refusing a 25×25.
    The new limits admit a 100×100 matrix and cap one request at roughly 140ms
    of parsing, measured: preparse, parse and validate cost about 1.1µs per
    character on 10.9, linearly. Execution is bounded separately by
    `eval_timeout`.
  - **`A.inject_variables()` works, and the names outlive the call.**
    `R.<u, v> = QQ[]` was fine because the preparser binds statically, while
    `R = PolynomialRing(QQ, 'u,v')` followed by `R.inject_variables()` — the
    same mathematics written the other way — was refused, 741 times across the
    corpus. A snippet that asks for an injection now has the *allowlist* half of
    deny-by-default suspended, and only that half: the withheld check still
    refuses every name that is live and not offered, so what suspending buys is
    names that are not live at all, which are either the injected ones or a
    `NameError`. The worker records what appeared so the next call can read it,
    gated on the caller having written the call. `inject_shorthands` is
    deliberately excluded — Sage routes it through the REPL's globals, so
    nothing lands here and the undeclared-symbol message is the better answer.
  - **The length limit is checked before the preparser and after it.** Raising
    `max_source_chars` made a new failure reachable: Sage rewrites every literal,
    so 92 KB of arithmetic arrives at the parser as 506 KB, and the worker parses
    before it validates. CPython got there first and answered `RecursionError:
    maximum recursion depth exceeded during ast construction` — telling a caller
    their mathematics broke the interpreter when it had exceeded a documented
    limit. The check now runs on what the caller wrote *and* on what the
    preparser produced, and the message says which: a number measured against
    the typed source is the one the caller can act on.
  - A name withheld because it spawns an external program now names the
    in-process equivalent: `gap(...)` points at `SymmetricGroup(5)` and
    `libgap`, `singular(...)` at `ideal(...).groebner_basis()`,
    `attrcall('bruhat_le')` at the lambda it stands for. ~2,300 of the corpus's
    refusals are these names, and
    `test_the_blocked_interfaces_do_not_block_the_mathematics` already proved
    each equivalent works — this writes down what that test knows. A lone `r`
    keeps the undeclared-symbol message, which is right: it is a radius far more
    often than the R interface.
- **`f(x) = x^2 + 1` was refused.** Sage's function-definition syntax — the
  first thing in its tutorial, and how a physicist writes `V(r) = -1/r` —
  expands to `__tmp__=var("x"); f = symbolic_expression(...).function(x)`, and
  the server validates the preparsed source, so the blanket dunder ban caught
  the preparser's own scratch name. `__tmp__` is now permitted as an assignment
  *target* only: the preparser never reads it back, a store cannot leak anything
  the caller did not already hold, and every other dunder stays refused in both
  directions (`__builtins__ = {...}` is a store). Found by writing the first
  physics session, not by a security review — an over-block passes every test in
  a suite that only asserts refusals.
- **`find_root` accepts an equation.** Kepler's equation arrives written as
  `E - 0.6*sin(E) = 0.75`, every CLI passed it that way, and `sage_eval`
  answered `invalid syntax (<string>, line 1)` — which names neither the cause
  nor the fix, while `solve_equation` had always accepted the form. The string
  is split the same way, and only after the plain expression fails to parse, so
  `log(x, base=2) - 1` is untouched.
- **The import refusal now says what to do instead.** "Import statements are
  disabled for Sage executions" is true and useless: Gemini opens numerical work
  with `import numpy as np`, was told only that imports are disabled, and failed
  three physics cases in a row without recovering. The message now adds that
  SageMath is already loaded and names what to reach for. The same three cases
  were re-run against the same model: two now pass, and the third fails on a
  function Gemini invented (`bessel_Jn_zeros`, which is SciPy's name), where the
  refusal is correct.
- **`match` statements and `function('f')` created unusable variables.** The
  allowlist trusts names the caller's own code binds, and binding was detected
  from `Name` nodes alone: `match` patterns bind through their own node types,
  and Sage's `function('f')` injects a name exactly as `var()` does. Every
  variable in a match statement, and every bare `function()` declaration, read
  as undefined for the rest of the session.
- **Uniformly indented code is no longer refused.** A snippet lifted out of a
  markdown block arrives with four spaces on every line, and was rejected for
  its margin rather than its mathematics. Caller code is dedented before
  validation and before execution; a valid program cannot be changed by it,
  since valid module-level code has no common indent to remove.
- **A refusal now names a fix the caller can perform.** SageMath predefines only
  `x`, so `diff(x^2*y^3, x, y)` needs `var('y')` — but the allowlist answered
  that the name "needs to be added to the allowlist", which is true and useless
  to a model that will simply retry. Short lowercase names are now told to
  declare the symbol.
- `evaluate_sage_streaming` had no error handling at all: a timeout, a security
  violation or a dead worker propagated raw and none were recorded, while
  `evaluate_sage` reported each properly.
- A failed journal write destroyed the previous journal. The superseded file was
  deleted before the new one was written, so a full disk left the session with no
  journal and a stray temporary file. The new file is put in place first now.
- A timed-out evaluation propagated as a bare `TimeoutError`: monitoring recorded
  nothing and the client saw an unstructured error. Both `evaluate_sage` and the
  specialised tools now report it as a tool error carrying the deadline.
- Three examples in the `evaluate_sage` description were wrong under any
  execution model: the Laplace pair needed its symbols declared (Sage's REPL
  predefines only `x`), `desolve_rsolve` does not exist, and
  `continued_fraction` has no `nterms` keyword.

### Removed

- **`docs/reference_md/` and `EVALUATION.md`.** The reference directory was
  orphaned: no code read it, and the `resource://sagemath/docs/{scope}` resource
  serves links into the upstream manual directly, so the local copy was 200-odd
  links pointing at the same URLs, and already accruing maintenance (one page
  recommended `search_src`, which callers may no longer use). `scripts/convert_html_to_md.py`, which only regenerated it, goes too.
  `EVALUATION.md` was an April snapshot whose verdict was superseded, whose
  security assessment had become wrong, and whose entire backlog had shipped.

### Documentation

- **A documentation pass over every markdown file**, checking each claim against
  the code rather than re-reading the prose. What it found: `USAGE.md` listed 33
  of 37 tools while its header said 37 — the four missing ones were
  `interrupt_sage_session`, which the same page recommends in prose, and the
  three that make up named workspaces; `INSTALLATION.md` called the SageMath
  runtime "optional" when without it every evaluation fails with `Unable to
  locate Sage executable`; the README architecture diagram
  advertised response caching that was deliberately turned off as an isolation
  bug. Test counts, the predefined symbols and the security framing were stale
  in several places.
- **A test now enforces that every tool is documented** in `USAGE.md` and
  `README.md`, because that table drifted by four without anything failing.
- Security documentation gained the design principle behind the `operator`
  finding: every attribute rule is enforced on the source text, so any primitive
  that fetches an attribute by a runtime string defeats all of them at once.

## [0.5.0] - 2026-08-14

### Security

- **Caller strings interpolated into trusted code no longer reach `sage_eval`.** Four
  tool parameters -- `graph_operation.graph`, `group_operation.group`,
  `coding_theory_operation.code_type` and `polynomial_ring_operation.base_ring` -- were
  embedded into generated Sage without validation. Generated code runs under a policy
  that re-permits `sage_eval` (every helper template is built on it), so a crafted
  parameter reached arbitrary execution: reading files, running shell commands and
  opening outbound connections were all demonstrated against a real SageMath runtime.
  All four now pass the same validation gate as every other expression, variable names
  must be plain identifiers, and a test fails the build if any future tool interpolates
  a caller string without a gate.
- **Forbidden names are rejected wherever they are read**, not only where they are
  called. `f = open` followed by `f("/etc/passwd")`, a `lambda` default, or a list
  literal all bypassed the previous check, through the specialized tools as well as
  `evaluate_sage`. The same applies to module names: `m = os` and
  `from sage.all import os as m` both returned the container uid.
- The worker namespace no longer contains `open`, `eval`, `exec`, `compile`, `input`,
  `breakpoint`, `globals`, `locals`, `vars`, `memoryview`, `help`, `exit` or `quit`, as a
  backstop for spellings the validator does not see.

### Changed

- **Integer results at or above 2^53 are returned as decimal strings**, and the same parameters accept them on the way in (`combinatorics_operation`, `elliptic_curve_operation`, `graph_operation` vertices joined `number_theory_operation`). They were
  returned as JSON numbers, and JavaScript-based MCP clients parse those as IEEE
  doubles, so exact values were silently corrupted: `bell(30)` reached one CLI as
  `846749014511809388871680` rather than `846749014511809332450147`. Integers
  below the boundary keep their numeric type, so ordinary results are unchanged.
  This mirrors the input side, which has required decimal strings for the same
  values since 0.4.0.
- **`interrupt_sage_session` no longer signals an idle worker.** When nothing is running
  it returns `No running computation in session '<name>'` instead of claiming state was
  preserved. Signalling an idle worker was not harmless: it is blocked reading its input,
  where the signal has no computation to abort, and a real Sage worker was left unable to
  answer the next request -- which then timed out and restarted it, destroying the
  namespace the interrupt exists to protect.
- The container runs with a read-only root filesystem, writable `tmpfs` for `/tmp` and
  Sage's own directory only. The Helm chart gained `readOnlyRootFilesystem`, matching
  `emptyDir` scratch, and default CPU and memory requests and limits.

### Internal

- `server.py` split from 2327 lines into `app.py` (the FastMCP object and lifecycle),
  `runtime.py` (settings and session manager), `codegen.py` (the code-building helpers)
  and a `tools/` package by domain. Tool names, schemas and descriptions are unchanged
  and held that way by a committed snapshot test; `from sagemath_mcp import server`
  still works.
- Coverage raised to 100% of statements and branches, enforced in CI.

### Added

- **`interrupt_sage_session`** stops a running computation while keeping every variable
  defined so far. The worker turns the signal into an `Interrupted` response rather than
  exiting, so the namespace survives. `cancel_sage_session` still restarts the worker and
  is now documented as the escape hatch for a wedged one, not the first resort. POSIX
  only.
- **Named workspaces.** `start_sage_session`, `list_sage_sessions` and
  `stop_sage_session`, plus an optional `session` argument on the tools that carry state.
  Workspaces have independent variables, so a long exploration and a scratch calculation
  no longer collide. Omitting `session` uses `default`, which behaves exactly as before,
  and the default workspace still keys on the bare client scope so persisted journals
  keep working.

## [0.4.0] - 2026-08-13

A correctness release. Several tools returned wrong values or did not work at all,
so **output changes for anything relying on the previous behaviour** — hence a minor
bump rather than a patch.

### Changed — output differs from 0.3.1

- **`distribution_operation`** now computes `mean` and `variance` analytically.
  `mean` previously evaluated `get_random_element()`, returning a random draw from
  the distribution — a different wrong answer on every call — and `variance` was
  hardcoded to `null`.
- **`distribution_operation`** now honours both parameters of the normal
  distribution. `mu` was ignored entirely and `sigma` was dropped unless exactly one
  parameter was passed, so `[0, 3]` silently computed with `sigma=1` and `[5, 2]` was
  centred on 0.
- **`matrix_operation([])`** is now rejected. It previously reported a determinant of
  `1.0`, because Sage reads `[]` as the 0×0 matrix whose determinant is 1 by
  convention — an obvious input mistake producing a plausible-looking number.
- **`geometry_operation("distance", ...)`** with fewer than two points is now
  rejected. It previously returned `{"result": null}`, presenting a missing answer as
  an answer.
- **Base image** moved to `sagemath/sagemath:10.9`. The `sage` account is **uid/gid
  1001** in 10.9, where it was 1000 in 10.5. Deployments pinning the old numeric UID
  must be updated; `docker-compose.yml` no longer hardcodes one, and the Helm chart
  now uses 1001.

### Fixed

- **`solve_ode`** rejected the spelling its own documentation advertised. `diff(y(x),
  x)` failed with *"Substitution using function-call syntax and unnamed arguments has
  been removed"*, because the dependent name was bound to the applied expression, so
  `y(x)` became `(y(x))(x)`. Both `diff(y(x), x)` and `diff(y, x)` now work and give
  identical results. ([#12](https://github.com/XBP-Europe/sagemath-mcp/issues/12))
- **All three plot tools** were non-functional. They passed a `BytesIO` to Sage's
  `save()`, which requires a filesystem path. 2D plots now render through the
  matplotlib figure; 3D surfaces are sampled and drawn through matplotlib's 3D axes,
  since `Graphics3d` has no in-memory export.
- **Results larger than 64 KiB** failed with `LimitOverrunError`. A response is read
  with a single `readline()`, and asyncio's default stream limit is 64 KiB; a
  base64-encoded 3D plot is around 100 KiB. Raised to 8 MiB. This affected any large
  result, not only plots.
- **`geometry_operation("distance", ...)`** computed `sqrt(-3)` for a 3-4-5 triangle.
  The generated code used `(a-b)^2`, and `^` is XOR in Python, not exponentiation.
- **`boolean_algebra_operation`** rejected the documented `x*y + x*z + y*z` with
  *"name 'x' is not defined"*, because the ring generators are `x0, x1, x2`. Both
  spellings now parse.
- **`coding_theory_operation`** documented `ReedSolomonCode(GF(7),3,5)`, which is not
  a valid constructor in current Sage. The documented example is now
  `GeneralizedReedSolomonCode(GF(7).list()[:6],3)`.
- **`graph_operation`** rejected every parameterised constructor. `CompleteGraph(4)`
  failed with *"name 'CompleteGraph' is not defined"*, which covered most of Sage's
  catalogue. Bare names, explicit calls, parameterised constructors and adjacency
  dicts all work.
- **Symbolic bounds** are accepted by `integrate_expression`, `limit_expression`,
  `series_expansion` and `symbolic_sum`. Integrating to `a` or summing to `n`
  previously raised `NameError`. Note that `n` and `N` are `numerical_approx` in
  Sage's namespace; short names are now treated as free symbols, while `e`, `i` and
  `I` keep their meaning as constants.
- **Newlines in expressions** no longer raise a syntax error. These tools evaluate a
  single expression, so whitespace is folded before evaluation. `evaluate_sage` is
  unaffected and keeps its newlines.
- **`matrix_multiply`** reports the offending shapes instead of Sage's *"unsupported
  operand parent(s) for \*"*.
- **`statistics_summary([])`** reports what it needs instead of *"list index out of
  range"*.
- **Operation names** tolerate surrounding whitespace across all twelve tools that
  take one.

### Added

- `tests/test_math_examples.py` — every Sage-backed tool is exercised with the
  examples from its own parameter documentation, against a real Sage runtime.
- `tests/test_syntax_variants.py` — the input spellings each tool must accept,
  organised by parameter kind. Equivalent spellings must produce equal results, and
  invalid input must fail cleanly rather than return a wrong value.
- `tests/test_generated_code_lint.py` — static checks needing no Sage: `^` in
  generated Python, `save()` to a buffer, and **any documented example that no test
  exercises**, which is the guard that makes issue #12 structurally impossible.

### Infrastructure

- **Integration tests now actually run.** The Makefile exec'd `sage-mcp` while CI
  named the container `sage-mcp-ci`, so every run failed with *"No such container"* —
  and because the command was piped to `tee`, the exit status was `tee`'s and the job
  reported success. Every previous green integration result was meaningless.
- **`pip-audit` is blocking.** It was `continue-on-error`, which is why an authlib
  advisory (PYSEC-2026-1201) sat in green builds. Transitive dependencies were
  upgraded to clear 32 findings.
- GitHub Actions upgraded across the board; dependency floors raised to match the
  versions actually resolved.
- Added `.dockerignore`. Without it `COPY . /workspace` ingested the local `.venv`
  and `.git`, baking a host-built virtualenv into the image.
- `scripts/bump_version.py` now updates `charts/sagemath-mcp/Chart.yaml`, which had
  been left behind at every previous release.
- `version-bump.yml` opens a pull request instead of pushing to `main`, which is now
  a protected branch.

[0.4.0]: https://github.com/XBP-Europe/sagemath-mcp/releases/tag/v0.4.0

## [0.3.1] - 2026-04-03

Patch release fixing the release pipeline; no code changes from 0.3.0.

### Fixed

- Cosign image signing lowercases the GHCR reference, which failed on the
  uppercase in `XBP-Europe`.
- The release build installs `build` before running `python -m build`.
- PyPI trusted publishing configured through a `pypi` GitHub environment.

## [0.3.0] - 2026-04-03

Grew the toolset from 18 to 33, all Sage-backed.

### Added

- `symbolic_sum` (finite and infinite series, products), `combinatorics_operation`
  (binomial, permutations, combinations, partitions, factorial, Catalan,
  Fibonacci, Bell), `plot3d_expression` (surfaces as base64 PNG),
  `distribution_operation` (normal, exponential, Poisson, chi-squared, Student-t,
  uniform, beta, gamma with PDF/CDF/quantile/sampling), `find_root`,
  `plot_multi_expression` and `vector_calculus_operation`.

## [0.2.0] - 2026-04-03

### Added

- 18 MCP tools covering calculus, algebra, linear algebra, ODEs, number theory,
  statistics and plotting.
- CLI integration suite across Claude and Gemini.
- FastMCP 3.x migration, CI modernisation, Docker pinned to SageMath 10.9, Helm
  health probes, Python 3.12 minimum.

## [0.1.2] - 2025-11-02

### Fixed

- Default MCP HTTP port aligned to 8314 across code, docs and deployment
  artifacts.
- Package published to GitHub Packages during release; release workflow creates
  its uv virtual environment.

