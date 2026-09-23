# TODO

The live queue. Completed items are not kept here — every shipped change is in
[CHANGELOG.md](CHANGELOG.md), and the security work is written up with its
reproduction and regression test in [REVIEW_ACTIONS.md](REVIEW_ACTIONS.md). This
file carried 31 ticked boxes duplicating both, several of them years of context
out of date.

- [ ] **Lift the `fastmcp<4` cap — blocked upstream, 2026-09-16.** Investigated
      against 4.0.4: `Context.session_id` is a fresh UUID on every tool call, on
      every transport, so no stateful fastmcp server keeps a client's state
      between calls (it breaks fastmcp's own `set_state`/`get_state` too). The
      recorded diagnosis in REVIEW_ACTIONS 68 — a response-cache leak — was
      wrong and is corrected there. Reproduction, cause and the conditions for
      lifting the cap: `docs/fastmcp4_session_regression.md`. Reported upstream
      as PrefectHQ/fastmcp#5134 (2026-09-16); the cap stays until a release
      reports one session id per connection and `tests/test_cache_isolation.py`
      passes against it in the Sage container.
      **Re-checked 2026-09-21 against 4.0.5** (the one release since): three
      calls on one connection still return three different session ids, and
      the upstream issue is open with no replies. Dependabot proposed lifting
      the cap to `<5` in PR #141, which is why `.github/dependabot.yml` now
      ignores major bumps of `fastmcp` -- the cap is a reproduced regression,
      not staleness, and a weekly PR to undo it is noise that will eventually
      be merged by accident.
      **Re-checked 2026-09-23 against 4.0.5**, which is still the newest
      release: three calls on one connection, three session ids. Upstream
      #5134 is open with no replies since 2026-09-16. The cap holds through a
      blanket `uv lock --upgrade`, which is the case the ignore rules exist
      for.
- [ ] From the 2026-09-06 external review, in its recommended order (foundations
      before features; the fastmcp<4 cap and the verifier's exactness fixes from
      the same review already landed — REVIEW_ACTIONS 68, `tools/verify.py`):
      - [x] **Explicit workspace identity.** *Done, 2026-09-06.* The 2026-07-28
        MCP spec retired protocol-level sessions and recommends application-issued
        handles; `start_sage_session` now returns an unguessable bearer
        `workspace_token` that addresses one workspace independently of the
        transport id, resolved through one central path by every stateful tool
        and lifecycle op. Names keep transport-scoped isolation; handles fail
        closed and are kept out of keys/logs/monitoring/listings. The fastmcp<4
        cap stays (a separate change lifts it). See `tools/session.py`,
        `session.py`, `tests/test_workspace_handles.py`.
      - [x] **One canonical hardened onboarding path.** *Done, 2026-09-06.* The
        README `docker run` now carries the Compose hardening and publishes on
        loopback (lint-tested); both setup scripts pin the Dockerfile's Sage
        tag (test-enforced), apply pids/memory/no-new-privileges limits, and
        are labelled as the dev/test fixture they are.
      - **Nightly CLI checks: accepted as local-only** (decided 2026-09-06).
        The clients' API keys are deliberately not published to CI, so the
        nightly runs skip all three clients; the harness is run locally where
        the keys live. Accepted trade-off — revisit only if a key-management
        route appears that does not put paid credentials in repository secrets.
      - [x] **Worker/session robustness.** *Done, 2026-09-06.* Startup is now
        serialized by a per-session lock (no double-launch); a configurable
        session ceiling (`SAGEMATH_MCP_MAX_SESSIONS`, default 128) bounds live
        workers; the helper tools record metrics through `_evaluate_structured`
        the way `evaluate_sage` does; and a new `/ready` endpoint evaluates
        `1+1` on the backend (503 when it cannot), which the Helm readiness
        probe now targets while `/health` stays a shallow liveness check.
      - [x] **Release validation.** *Done, 2026-09-06.* The Docker release job
        smoke-tests the built image with a stateful assign-and-read before any
        push; CI's compose smoke now asserts its stateful result. A second review
        round extended the dry-run guard to every destination: PyPI, the MCP
        registry and the GitHub release gated on the ref alone, which a
        tag-targeted `workflow_dispatch` satisfied, so all publishing now
        requires the tag **push** event under one policy, with a static test
        (`test_the_release_workflow_publishes_only_on_a_tag_push`) enforcing it.
        The push step now publishes the exact candidate image the smoke test ran
        against (retag + push + sign by registry digest), not a second build.
      - [x] **Verifier certainty (second round).** *Done, 2026-09-06.* Two more
        soundness defects the review reproduced: a comparison over machine floats
        (`RR(1)+RR(1)/10^20 == RR(1)`) was labelled proved/exact — now the
        operands are inspected and an inexact comparison is `supported` via a
        `float_comparison` method, never exact; and a sampled counterexample
        could violate a domain assumption (`x != 1/2` refuted at 1/2 under
        `assume(x,'integer')`) — sampling now establishes each point's
        admissibility and skips what it cannot confirm. `tests/test_verify.py`.
      - [x] **README language.** *Done, 2026-09-06.* "full access"/"run any
        SageMath code"/"arbitrary" replaced with the deny-by-default subset
        description across README, USAGE and the `evaluate_sage` tool
        description; the fresh-namespace exception now sits in the tool
        description the model reads and at the top of the `evaluate_sage`
        reference, not only in the deep session-semantics note.
- [x] From the 2026-08-24 field survey: outcome benchmarks. *Done, 2026-09-07.*
      `benchmarks/` (fixed seeded case set + Workflow, scored for equivalence in
      Sage); first run subject `haiku` = **17/24 → 24/24 with Sage**, +7 all in
      the compute-heavy/infeasible tiers, one reasoning-only answer confidently
      wrong. Published to `benchmark-stats.md` + README. This is the live 2-arm
      (reasoning vs. Sage compute) version; the rigorous three-arm (no-tools vs
      `evaluate_sage`-only vs full catalogue, with real tool-gating and the
      wrong-confident/refusal/latency/tool-call breakdown per the 2026-09-06
      review) still wants folding into the `tests/cli_integration` nightlies,
      where the per-client keys live. `verify_claim` shipped 2026-09-06
      (`tools/verify.py`).
- [x] Passagemath runtime extra to cut install footprint. *Done, 2026-09-07;
      all three blockers closed below, pin moved to 10.8.11 on 2026-09-14.*
      Evaluated 2026-09-06
      (`docs/passagemath_evaluation.md`): verdict **adopt, pinned to a verified
      release**, technical fit better than the roadmap sketch assumed — `pip
      install passagemath-standard` gives a working `from sage.all import *`,
      `_sage_worker.py` runs unmodified, all 33 tool domains pass on 10.8.9,
      ~1 GB/3.8 GB/~1 min setup vs the 3 GB image. Two blockers before shipping:
      (1) the star-exports/denylist derivation is layout-sensitive and over-fires
      under the modular layout (the real engineering, ~1–2 days — and it overlaps
      the "classify rather than accept" item below); (2) full suite + corpus
      sweep against the pin. Don't track their latest: 10.8.10/10.8.11 each
      shipped a broken core backend on Linux x86_64 (found in the evaluation, not
      their tracker), so pin + cold-install smoke gate in CI. File the
      `maxima_lib` regression upstream.
      **Blocker (1) + the runtime integration DONE 2026-09-07** (REVIEW_ACTIONS
      69): the layout-aware derivation fix (`sage.interfaces.all` attributed by
      value `__module__`), runtime dispatch (`_artifacts.py` via
      `importlib.metadata`), the passagemath artifact set
      (`allowlist_passagemath.py` / `star_exports_passagemath.py`; the baked
      denylist is shared, with `commence_startup` carried in
      `_DANGEROUS_BARE_NAMES`), the `[passagemath]` exact pin, and
      `make allowlist-passagemath`/`star-exports-passagemath`. Verified a
      byte-for-byte no-op on monolithic and correct end-to-end on passagemath
      10.8.9.
      **Blocker (2) DONE 2026-09-07:** a `passagemath` CI lane (`ci.yml`)
      cold-installs the exact pin and runs the whole suite against it — the real
      worker, the artifact-drift tests and the doctest corpus sweep — as the
      pin-bump smoke gate, no Docker. Getting there took making three drift
      tests runtime-aware (they had imported the monolithic allowlist/star-exports
      and interface list directly; now `_artifacts`-dispatched and layout-aware,
      a strict no-op on monolithic — verified) and fixing `sage_library()` for
      passagemath's namespace-package layout (`sage.__file__` is None). Measured
      against the pin: the whole suite is **1184 passed / 1 skipped**, and the
      corpus sweep is **433,201 examples at 99.02% acceptance** (3232 files),
      clearing every existing floor with margin — no re-baseline needed. The one
      cross-runtime difference was sound (passagemath's symbolic stack *proves* a
      Catalan-constant identity monolithic 10.9 only *supports*; the ladder test
      now accepts either).
      **Blocker (3) DONE 2026-09-07:** the `maxima_lib` regression is filed
      upstream — passagemath/passagemath#2836 — after reproducing it firsthand on
      both 10.8.10 and 10.8.11 (identical `ECL says: THROW: The catch
      MACSYMA-QUIT is undefined` at `maxima_lib.py:361`; 10.8.9 unaffected).
      **All three blockers are now closed.** Move from pinned extra to primary
      install story only after two consecutive passagemath stable releases pass
      the smoke gate on first try — 10.8.10 and 10.8.11 both failed it as first
      released (#2836), so the counter is at zero (§ evaluation blockers).
      **Pin bumped to 10.8.11 on 2026-09-14** after upstream fixed #2836 with the
      yanked-and-reissued `10.8.11.post1` ecl/maxima wheels: the lane passes, the
      allowlist regenerates byte-identical, `inline_plots` (new, from
      `sage.repl.interpreter`) joined `commence_startup` in
      `_DANGEROUS_BARE_NAMES`. A post-release fix is not a first-try pass, so the
      counter still reads zero; 10.8.12 is the first release that can count.
- [x] **`scripts/generate_allowlist.py` classifies rather than accepts.**
      *Done, 2026-09-07.* Four findings had one root cause: the allowlist was
      *whatever survived the namespace scrub*, inheriting every gap in it. The
      generator now classifies each surviving name and **fails generation** on
      anything it cannot place as mathematics — a module object from outside
      `sage`, or a value of foreign provenance not in a small reviewed set
      (`_VETTED_FOREIGN`/`_SAFE_MODULE_NAMES`). A dangerous helper a future Sage
      adds stops the generator with its name instead of being allowlisted
      silently. Calibrated against real Sage so it is **output-neutral**: verified
      byte-identical output on monolithic 10.9 (container) and passagemath 10.8.9
      (both under Python 3.12), so no regeneration and no risk of new refusals.
      The reviewed exceptions on monolithic are the 42 sage catalog-modules
      (`codes`, `groups`, …), `math`/`operator`, and 12 foreign names (`copy`,
      `reduce`, `PariError`, cysignals alarms, …). Guarded by
      `tests/test_generate_allowlist.py` (synthetic, fast) and a real-Sage
      integration test asserting no false positives. **Guard-only** by decision;
      tightening the surface (dropping bare `sage`/`operator`) was deferred.
- [x] Glama: listed and claimed as XBP-Europe (via `glama.json`, #50). Done.
- [x] Official MCP registry: listed as `io.github.XBP-Europe/sagemath-mcp`,
      published by the release pipeline's `mcp-registry` job. Done.

## From the 2026-09-06 external project evaluation

An outside reviewer went through the repo and the source. Roughly a third of
their list was already done (tool annotations, the session ceiling, the
red-team bypass corpus, Dependabot's Docker/Actions coverage, the passagemath
extra evaluation) or wrong; these are the items that survived as legitimate,
prioritised. Correctness first, then packaging/adoption.

**Correctness / product**

- [x] **Plots return MCP image content, not a base64 dict.** *Done, 2026-09-06.*
      `plot_expression`/`plot3d_expression`/`plot_multi_expression` returned
      `{"image_base64": ...}` — JSON text a client showed as a base64 wall
      instead of a picture. They now return a `fastmcp` `Image` (rendered
      `ImageContent`), bounded in size (a PNG dropped ~200 KB → ~25 KB), with an
      `image_format` option for SVG. Verified against real Sage.
- [x] **Audit every tool's return for client-travel.** *Done, 2026-09-06.*
      Swept every tool's return. One real class beyond the known ones: a
      non-finite float (`inf`/`nan`) is invalid JSON (`Infinity`/`NaN` tokens a
      strict client rejects) and, when nested, defeated result reconstruction so
      `calculate_expression("log(0)")` dropped its `numeric` field to a
      double-encoded string. Fixed centrally in `_evaluate_structured` —
      reconstruction accepts `inf`/`nan`, non-finite floats travel as strings.
      Everything else already sound (large ints → decimal strings, plots → image
      content, plain strings fine). `tests/test_codegen.py`.
- [x] **Optional HTTP auth.** *Done, 2026-09-07.* No-auth stays the deliberate
      default (SECURITY.md: the container is the boundary, keep it loopback). On
      top of it, `SAGEMATH_MCP_HTTP_AUTH_TOKEN=<secret>` now requires
      `Authorization: Bearer <secret>` on every MCP request over HTTP — a
      constant-time-compared (`secrets.compare_digest`), never-logged shared
      secret via a `TokenVerifier` provider (`auth.py`, wired through
      `app.py`); `/health` and `/ready` stay open. Verified end-to-end against the
      ASGI app (open probe 200; `/mcp` 401 without/with a wrong token, 200 with
      the right one). The Dockerfile's container-internal `--host 0.0.0.0` is now
      an explicit, noted choice: the server logs a loud warning when it binds a
      non-loopback host with no token (`_exposure_warning`). `tests/test_auth.py`,
      SECURITY.md, USAGE.md.
- [x] **Mutation-test the security policy.** *Done, 2026-09-06.* `make mutation`
      (`scripts/run_mutation_tests.py`) runs cosmic-ray over `security.py`, plus
      Hypothesis property tests (`tests/test_security_property.py`) on top of the
      `test_security_bypass.py` corpus. Scoped to `security.py` only — `allowlist.py`
      is generated *data*, guarded by the Sage-agreement integration test, not
      logic to mutate. Parallelised (~35 min serial → ~2 min, `--workers`), with a
      weekly non-gating CI job publishing `mutation-stats.md`. Published score:
      **61.2% raw, 87.5% effective** (426/696 killed; 209 survivors are equivalent
      `X | None` type-annotation mutants that no test can kill).
- [x] **Close the genuine mutation survivors.** *Done, 2026-09-06.* Nine targeted
      tests in `test_security.py` killed the cleanly-killable, security-relevant
      gaps the first run surfaced (413 → 426 killed, 84.8% → 87.5% effective):
      `_is_dunder`'s `> 4` boundary and its `and` (`____`, `___`, `__x`), the
      source/node/depth limits accepted *at* the limit not only rejected past it,
      `forbid_global`/`forbid_nonlocal` leaving ordinary code alone (the old test
      matched a word a negated `isinstance` still produced), and the attribute-chain
      exemption not shielding a forbidden third segment (`operator.abs.os`, which
      also pinned the caller-owned `and`). The ~60 remaining non-annotation
      survivors were triaged as equivalent or near-equivalent — `== "s"` → `is "s"`
      on interned strings, keyword-only `*` markers read as `Mul`, `index == last`
      where `index <= last`, cosmetic message-formatting flips — none of them a
      reachable behaviour change. Not worth contrived tests; re-triage if a future
      refactor makes any of them reachable.
- [x] **Cheap protocol wins.** *Done, 2026-09-06.* Three MCP prompts
      (`prove_and_verify`, `solve_and_check`, `explore_object`) steer the model
      toward verified, stateful use. And a pre-warmed worker pool
      (`SAGEMATH_MCP_WARM_POOL_SIZE`, default 1) pays the ~1s Sage lazy-init off
      the client's path — the real cost was the first *evaluation*, not the
      import — so a new session's first call drops from ~980ms to ~2ms
      (verified real Sage). `tests/test_prompts.py`, `tests/test_warm_pool.py`.

**Packaging / build hygiene**

- [x] **Dockerfile `COPY . /workspace`.** *Done, 2026-09-06 (#64).* Now copies
      only the wheel-build inputs (`pyproject.toml`, `README.md`, `LICENSE`,
      `src/`), so tests, `external_docs` and the review file stay out of the
      image and the install layer's cache survives doc/test edits; verified the
      built image still passes the stateful smoke and serves all 40 tools. Still
      open: pin the base image by digest, and a slim conda-forge-based variant.
- [x] **Reconcile the tool count across files.** *Done, 2026-09-06 (#64).*
      `server.json` now says 40 (was "34"), and
      `test_hardcoded_tool_counts_match_the_inventory` fails if any stated count
      drifts from `tests/fixtures/tool_inventory.json`, the source of truth.
- [x] **`external_docs/reference_html`** vendors Sage's own HTML (102 KB) into an
      MIT repo — fetch at generation time instead of committing it. *Done,
      2026-09-15 (#91).* Nothing read the files (`lookup_sage_doc` and the docs
      resource link to doc.sagemath.org directly), so the change was a deletion
      rather than a generation step.
      **Adversarial security review, 2026-09-19/20 — eight findings, all fixed
      and released in 0.8.3.** Four parallel reviews over the validator, the
      star-export subsystem, the worker and the deployment surface, with every
      claim re-verified against real SageMath before it was acted on. Two agent
      claims did not survive that check and were dropped.

      The one that mattered: **caller code executed arbitrary Python through
      the `sage` module tree** (item 81) --
      `LazyImport('builtins','eval')('6*7')` returned 42, `('os','environ')`
      disclosed the environment, `('builtins','open')(...)` read files. The
      bare spellings were all correctly refused, so deny-by-default worked as
      designed and the dotted path walked around it. Closing it cost 950 corpus
      examples (99.09% -> 98.83%), declared with its own ceiling. Two more were
      reachable with no credential: the same tree through Sage-only syntax
      (item 83), and **no `Host`/`Origin` validation**, which let a web page
      drive a loopback-bound server by DNS rebinding (item 82).

      The rest: reset not clearing persisted state and the workspace token
      reaching a notification (item 84), the star screen judging a `LazyImport`
      proxy rather than its target (item 85), and the Helm chart running
      seccomp-Unconfined with an API token mounted (item 86).

      **Two patterns worth carrying forward.** Three findings came from
      *enumerations that fell behind what they were meant to cover* -- a list of
      dangerous path segments, a hand-written list of four tools, a screen
      mirroring two policy sets out of three. Prefer refusing a root, or
      deriving the list, over extending it. And two came from *one mechanism not
      inheriting a lesson a neighbouring one had already learned*: the namespace
      scrub resolved lazy imports and the star screen did not; the AST path had
      a `sage`-root guard and the token screen did not.

      **Fuzzing campaign, 2026-09-21/22 — five surfaces, released in 0.8.4**
      (items 90-97). The first findings here that came from generated input
      rather than from review. The AST policy: `del` counted as *binding* a
      name, and `_bound_names` walks unreachable code, so `if False: del eval`
      bought the allowlist exemption for thirteen names (item 90). None
      executed -- the namespace scrub and the restricted builtins held -- but
      the first lock is supposed to hold too. The same rule made `del Integer`
      break `2 + 2` for a whole session, since the preparser rewrites every
      integer literal.

      The worker protocol: any well-formed JSON that is not an object made
      `[].get("type")` an uncaught `AttributeError`, so one malformed frame
      killed the worker and discarded the session's namespace (item 91). The
      session keys: `key_for("A", "x")` and `key_for("A::x", "default")`
      composed to the same storage key, which would have had two clients
      sharing a worker (item 93, latent -- session ids are UUIDs). The
      monitoring redaction was publish-everything-except, so a field added
      later would publish itself (item 95).

      Clean, and worth recording as such: the codegen gates over 150,000
      fragments, the import rewriter over 214,844 programs, the bearer-token
      path, and the session resource against 4,000 generated scopes.

      **The pattern, again.** Items 92 and 95 were both *enumerations that
      cannot know what they have not been told* -- four dangerous `latex`
      attributes refused by name while nine were accepted, three free-text
      metrics fields popped while the rest were published. Both became
      allowlists. That is the same lesson as the 2026-09-19 review, arriving
      in a different subsystem, which is the argument for fixing the shape
      rather than the instance.

      **And one the machinery caught rather than a person.** v0.8.4 failed
      twice on a guard added in that very release: a job with no checkout
      running a repository script, and behind it an argparse flag swallowing
      `-passagemath` as an option name (item 98). The dry-run dispatch exists
      for exactly that and had not been run. `SUPPORT.md` now states plainly
      that nothing here is reviewed by a second person.

- [ ] **Clear the `sagemath-*` PyPI namespace question** with sage-devel now —
      Sage upstream owns `sagemath-standard`/`sagemath-symbolics`/… and this is a
      third-party package in that namespace. A friendly ask today, a forced
      rename after adoption.
- [x] **README is a front door, not a manual.** *Done, 2026-09-07.* Trimmed
      ~1,680 → ~230 lines: what it is, install-and-run per audience (GHCR image
      first, then PyPI, then the passagemath extra), one client config, three
      example prompts, a compact 40-tool index, condensed architecture + security,
      links out. The full per-tool reference, the interpretation notes and the
      complete security model moved into `USAGE.md` (the single manual, per the
      chosen "expand USAGE.md" split); the embedded changelog is dropped for
      `CHANGELOG.md`. `verify_claim` and the 98.6%/432,878 doctest number are
      folded in. Badges kept (they are test-validated); the doc-honesty test for
      blocked modules now asserts against `USAGE.md`. Tool-count and badge
      invariants unchanged; 100% coverage holds.

**Adoption (not code)**

- [ ] Reach the actual audience: announce on sage-devel / the Sage Zulip; talk
      to CoCalc (hosted Sage). Publish the doctest-corpus acceptance % as a
      benchmark (already generated) — the strongest single credibility claim.
- [ ] Citability + community: a JOSS paper, a Zenodo DOI, `CITATION.cff`,
      `SUPPORT.md` (release cadence / what "supported" means), enable GitHub
      Discussions, label good-first-issues. The bus factor (CODEOWNERS names one
      person) is what an enterprise evaluator notices.
      **Partly done, 2026-09-14:** `CITATION.cff` (version-bumped and
      consistency-tested with the other version files), `SUPPORT.md` (states the
      single-maintainer bus factor plainly rather than hiding it), Discussions
      enabled and linked from the issue chooser, README and CONTRIBUTING.
      Still open: (a) **Zenodo DOI** — needs the repository owner to enable the
      GitHub integration at zenodo.org for `XBP-Europe/sagemath-mcp`, after which
      the next tag mints a DOI; then add the concept DOI to `CITATION.cff` (the
      file says where) and a DOI badge to the README. Tracked as **#92**, opened
      blocked; re-checked 2026-09-16 — Zenodo has no record for this repository
      and no integration webhook is installed, so there is nothing to add yet;
      (b) ~~**good-first-issue candidates**~~ **seeded 2026-09-15:** #91 (remove
      the vendored Sage HTML, `good first issue`) and #94 (hash-lock the
      passagemath image, `help wanted`) are both done and closed, as is #93
      (conda-forge recipe) now that the recipe itself is written; #92 (DOI
      wiring, `good first issue`) and #101 (submit the recipe to
      `staged-recipes`, `help wanted`) stay open on owner action; (c) the **JOSS paper**, a separate piece of
      writing once the DOI exists.
- [ ] Extra install paths worth their weekend: a conda-forge recipe (where Sage
      users actually live), a nix flake (`nix run github:…` incl. Sage), and an
      `.mcpb` bundle for one-click Claude Desktop install. Trust signals: PyPI
      Trusted Publishing PEP 740 attestations, an SBOM on releases, SLSA image
      provenance, an OpenSSF Scorecard badge.
      **Trust signals DONE 2026-09-14** (`release.yml`, `scorecard.yml`,
      `DISTRIBUTION.md`): PEP 740 was already live on the 0.7.0 files through
      Trusted Publishing and is now explicit; SPDX SBOMs of the image and of the
      `uv.lock` dependency tree are release assets and the image SBOM plus SLSA
      provenance are attested to the GHCR digest; Scorecard publishes weekly.
      First real exercise is the next tag — the dry-run dispatch covers SBOM
      generation but attests nothing by design. The install paths remain open:
      **conda-forge is SUBMITTED, 2026-09-17** — conda-forge/staged-recipes#34875
      (#101). The recipe is on `main` — `packaging/conda/recipe.yaml`, kept in
      step with `pyproject.toml` by `tests/test_conda_recipe.py`, including the
      sdist hash against PyPI. It was converted to the **v1 `recipe.yaml`
      format** for the submission: staged-recipes deprecated v0 `meta.yaml` in
      August 2026 and says v0 submissions are "less likely to be reviewed in a
      timely manner". Every runtime dependency is on conda-forge, `fastmcp
      3.4.7` included, so it resolves under the `<4` cap today. **The
      submission immediately found a real defect in our sdist** — see item 79;
      the recipe cannot build until a release ships the fix. The maintainer
      listed is `csteinlxbp`, confirmed on the pull request as staged-recipes
      requires, so the owner is publicly on the hook for the feedstock and for
      the bot's pull requests after it. The README / USAGE / DISTRIBUTION
      install lines and the `conda-forge` badge wait on the merge.
      The **`.mcpb` bundle is done** (2026-09-16, `packaging/mcpb`): MCPB `uv` server type, ~2 KB, pinning
      `sagemath-mcp[passagemath]` so the host installs a Sage runtime with it;
      built and attached by every release, schema-validated as it packs, version
      kept in step by the bump script. A **Gemini CLI extension** landed with
      it (`gemini-extension.json` at the root, where `gemini extensions install`
      reads it from a git ref), and `USAGE.md` documents the `codex mcp add`
      one-liner — Codex has no extension or bundle format, only `codex mcp
      add/list/get/remove`, so there is nothing to package for it.
      The **nix flake is deferred** (decided 2026-09-16), and the reason is a
      version mismatch rather than effort: nixpkgs ships `sage` **10.7**, this
      project pins **10.9**, and the caller allowlist is generated from that
      exact namespace — `test_the_caller_allowlist_matches_this_sage` fails
      against a Sage whose namespace differs. So `nix run …` "including Sage"
      would ship a runtime combination nothing here tests and whose own
      guardrails reject it. The three ways round it, none worth taking yet:
      package **only the server** and let the user bring Sage (correct, but
      drops the part of the idea that made it attractive); generate and review
      a **third artifact set** for 10.7 plus a CI lane to keep it honest (the
      passagemath evaluation already priced the *second* set as the recurring
      cost of a second runtime, and this one would trail ours by two releases);
      or wrap the **passagemath** route with uv2nix-style machinery, which is
      real nix work duplicating a path that already works without nix.
      Revisit when nixpkgs' `sage` reaches the version pinned here, or when
      someone actually asks for it — at which point option one is the cheap
      start. `nixpkgs` also has no passagemath package, checked the same day.
      **Post-release trust check, v0.8.0 (2026-09-16).** Every published
      signal was verified from a clean machine, and two defects came out of it.
      What holds: the Cosign signature on both images (`v0.8.0` and the
      multi-arch `v0.8.0-passagemath` index) verifies against
      `release.yml@refs/tags/v0.8.0`; SLSA provenance verifies on both image
      digests, on the released wheel and on the sdist; the SPDX SBOM is attested
      to the primary image digest; and PyPI carries a PEP 740 attestation for
      both files, naming this repository's `release.yml` as publisher. Open
      code-scanning alerts are the eight Scorecard findings already reasoned
      about here, nothing else — the remaining unpinned pip line is
      `pip install --no-deps .`, installing the project itself from the
      checkout, which has no hash to pin. The **`.mcpb` bundle was run the way a
      desktop host runs it**: packed, unzipped, `uv run --directory <dir>
      src/server.py`, then a real MCP handshake — `initialize` returns
      `sagemath-mcp 0.8.0`, `tools/list` returns all 40 tools, and
      `evaluate_sage` on `factor(2^61 - 1)` returns the Mersenne prime in 2 ms
      after the roughly 1 GB first-launch install. The two defects are below
      (dist/ purity, and Signed-Releases), both fixed the same day.

      **The bundle was packed into `dist/`, which would have failed the next
      release (found and fixed 2026-09-16).** The publish job uploads
      `packages-dir: dist`, and twine reads the whole directory: a `.mcpb` there
      raises `InvalidDistribution: Unknown distribution format`, reproduced
      locally with `twine check`. It would have failed in the publish job —
      after the images were pushed and signed — and only on a real tag, since a
      dry run skips publishing. The bundle now packs into `bundle/`, the build
      job refuses anything in `dist/` that is not a wheel or an sdist, and
      `tests/test_mcpb_bundle.py` holds both.

      **Post-release trust check, v0.8.1 (2026-09-17).** Re-run end to end on
      the published artefacts, not the working tree. Cosign verifies both images
      against `release.yml@refs/tags/v0.8.1`; SLSA provenance verifies on both
      image digests and the SPDX SBOM is attested to the primary one; PyPI
      carries PEP 740 for both files; all four SBOM assets parse as SPDX 2.3;
      and all four tags (`v0.8.1`, `v0.8.1-passagemath`, `latest`,
      `latest-passagemath`) resolve anonymously, the passagemath ones as
      `linux/amd64` + `linux/arm64` indexes. The **new provenance asset works as
      designed**: `gh attestation verify <artefact> --bundle
      sagemath-mcp-0.8.1.intoto.jsonl` verifies the `.mcpb` offline, and the
      bundle names all three subjects.

      The **desktop bundle was installed from the release page and driven over
      MCP**: it reports `sagemath-mcp 0.8.1`, lists 40 tools, evaluates
      `factor(2^61 - 1)` correctly, and — the part worth checking — `from
      sage.matroids.advanced import *` followed by `BasisMatroid(...).rank()`
      returns 2 while `libgap` is still refused. So item 77's gain reached a real
      user through a real install, and the drop is not a hole there either.

      One false alarm worth recording: the first attempt failed with `Failed to
      install: passagemath_symbolics-…whl`, which looked like a bundle defect and
      was not. The scratch directory sat on a tmpfs with 3 GB free while the uv
      cache was on another filesystem, so uv full-copied instead of hardlinking
      and ran out of space. Re-run on the cache's own filesystem it installs
      clean. **Test the bundle where hardlinking works**, or the failure mode
      misleads.

      **The dry run earns its keep (2026-09-16).** Re-running
      `release.yml` by dispatch on the fix branch failed immediately: the bundle
      step derived its version by stripping `v` from `GITHUB_REF_NAME`, which on
      a dispatch is the branch name, so a branch with a slash produced a nested
      path and the `ls` after it failed. Fixed by reading `GITHUB_REF_TYPE`. The
      second dispatch went green end to end — build, both images, the arm64
      lane, the manifest, and the dry-run release listing `bundle/` and a clean
      `dist/`. Worth remembering when adding a step to this workflow: a step
      that only a tag reaches is a step nothing tests, and the dispatch is how
      that gets cheap.

      **Scorecard, first published score 5.7 (2026-09-14) — plan and status:**
      - [x] *Pinned-Dependencies 0 → 8 locally, then the pip lines too
        (2026-09-15, #94).* Every `uses:` in all eight workflows pinned to a
        commit SHA with a version comment (Dependabot updates SHA pins); the
        three `FROM` lines pinned by index digest; `Dockerfile.passagemath`
        installs `requirements-passagemath.txt` (exported from `uv.lock` by
        `make passagemath-lock`) with `--require-hashes`, guarded by
        `tests/test_passagemath_lock.py`. **Pin-bump recipe now has one more
        step:** after `uv.lock` changes, run `make passagemath-lock` and commit
        the export, or that test fails. What stays unpinned, deliberately: the
        three `npm install -g` lines in `cli-nightly.yml` (CLI clients for a
        local-only harness).
      - [x] *Token-Permissions 0 → 10 locally.* Top-level `permissions:
        contents: read` on every workflow; write scopes only at job level, only
        where used (`issues: write` moved off the top level in `audit.yml` and
        `cli-nightly.yml`).
      - [x] *SAST 0.* `codeql.yml`: CodeQL for `python` and `actions`,
        security-extended queries, on push/PR/weekly. The score updates once it
        has run on a few commits.
      - *Signed-Releases 0 — the expectation was wrong, and the cause is now
        fixed (2026-09-16).* v0.8.0 was the first release built by the signing
        pipeline, and the Scorecard run ten hours after it still scored 0. The
        reason: the check reads **GitHub release assets only**, matching
        `.asc`/`.minisig`/`.sig`/`.sign`/`.sigstore`/`.sigstore.json` for a
        signature and `.intoto.jsonl` for provenance (`probes/releasesAreSigned`,
        `probes/releasesHaveProvenance`). Everything this project signs lives
        somewhere else — Cosign signatures and SLSA/SBOM attestations on the
        GHCR digest, PEP 740 attestations on PyPI, and the wheel's provenance in
        GitHub's attestation store — so the release page had no file the probe
        could match. The release now attaches
        `sagemath-mcp-<version>.intoto.jsonl`, the Sigstore bundles for the
        wheel, sdist and `.mcpb` that the attestation step already produced.
        **Confirmed 2026-09-17 by v0.8.1**, the first release built with the
        asset attached: Signed-Releases **0 → 2**, overall **7.4 → 7.5**, with
        the reason line reading "1 out of the last 5 releases have a total of 1
        signed artifacts". That is exactly the arithmetic — the score averages
        the last five releases (10 with provenance, 8 signed-only, 0 otherwise,
        floored), so `floor(10/5) = 2` — and it reaches 10 only once five such
        releases are in the window. Nothing further to do but ship.
      - *Branch-Protection −1 (internal error).* Scorecard's default token
        cannot read protection settings; needs the owner to add a fine-grained
        PAT (`administration: read`) as `SCORECARD_TOKEN` and pass it as
        `repo_token`. Owner action, optional.
      - *Code-Review 0, Contributors 3.* The single-maintainer reality
        `SUPPORT.md` states plainly; not fixable by configuration. Would move
        only with a second maintainer reviewing pull requests.
      - *CII-Best-Practices 0.* A self-assessment questionnaire at
        bestpractices.dev; owner action if wanted, most answers are already
        documented here (SECURITY.md, CONTRIBUTING.md, tests, signed releases).
      - *Fuzzing 0.* Not pursued: the AST validator is exercised by the
        432,878-example doctest corpus and a Hypothesis property suite, which is
        the fuzzing this project's shape actually benefits from.
      **Score 7.7 (2026-09-18), and the remaining gap is mostly not ours to
      close.** Signed-Releases reached 4 once v0.8.1 and v0.8.2 both carried the
      provenance asset, and it climbs on its own as releases ship; SAST is 9 and
      rises the same way, since the 7 uncovered commits predate `codeql.yml`.
      Branch-Protection needs the owner's fine-grained PAT, CII-Best-Practices
      is an owner questionnaire, and Code-Review and Contributors are the
      single-maintainer reality `SUPPORT.md` states. Of the four
      Pinned-Dependencies warnings, all four are deliberate: `pip install
      --no-deps .` installs the project itself and has no hash to pin, and the
      three `npm install -g` lines in `cli-nightly.yml` install the CLI clients
      the harness exists to measure — pinning them would measure a client nobody
      runs. The workflow now says so where someone would otherwise "fix" it.
      **Chasing the number further is not worth the review time**; what was
      worth doing is below, and Scorecard does not flag it.
      - [x] *Pin the MCPB packer (2026-09-18).* `release.yml` and `make mcpb`
        fetched `@anthropic-ai/mcpb@latest`. That tool runs inside the release
        and the bundle it emits is attested a few steps later, so an unpinned
        packer meant our signature vouched for whatever npm served that minute,
        and a format change would reach a desktop app without anyone deciding to
        ship it. Pinned to 2.1.2 in both places — verified output-identical to
        the released v0.8.2 bundle, 1,891 bytes and the same three files, so the
        pin changed what we trust and nothing else. npm versions are immutable,
        so this is a real pin even though it is not a hash. A test fails if the
        two places disagree or if `@latest` returns. Scorecard never flagged it,
        because it inspects `npm install`, not `npx`.
- [x] **Measure the tool surface before defending it.** The roadmap argues 40
      tools is a differentiator; the reviewer argues `evaluate_sage` covers most
      of it and a 12-tool build might score the same. Use the CLI harness to
      test a reduced set vs the full catalogue on pass rate before deciding.
      *Measured 2026-09-15* — `make tool-surface`, `tool-surface-stats.md`. The
      23 tool-forcing cases ran through Claude Code, Gemini CLI and Codex in
      three arms: no server (enforced: Claude `--tools ""`, Gemini without
      `--yolo` with its tool stats read, Codex `--json` scanned for command
      executions — all read 0), the server narrowed **on the wire** to
      `evaluate_sage` + session/diagnostic tools (the proxy's `--allow-tools`
      hides the rest from `tools/list` and refuses `tools/call`), and the full
      catalogue. Findings:
      1. **The "tool-forcing" cases no longer force tools for 2026 frontier
         clients.** Without any server: Claude 21/21, Codex 21/21, Gemini 18/21
         — from recall and reasoning, zero tool use observed. Only Gemini shows
         the wrong-confident failure (3: `next_prime(10^30)`, `50! mod 1000003`,
         Bell(25) — all plausible-looking, exactly what `verify_claim` is for).
         The case set needs a harder tier before it can discriminate arms on
         *correctness* (the outcome benchmark's `infeasible` tier is the model;
         its subject was `haiku` for the same reason).
      2. **Full catalogue vs core tools, on client-cases measured in both: full
         is ahead by a few cases, not by a class.** Claude 21/23 → 22/23,
         Gemini 15/23 → 19/23. Where the helpers won, they won by keeping the
         model out of `evaluate_sage` code that tripped friction — Gemini's
         `import` statements (refused), `bessel_J_zeros` (not a Sage name),
         `partitions` (not offered), `'float' object has no attribute 'n'`,
         `unable to convert '6.62607015e-34' to a rational`. That is the real
         value of a dedicated tool: it writes the Sage the model would have
         written wrong. It is also a list of friction to fix in `evaluate_sage`
         itself (each is a "reduce refusals" item).
      3. **Codex could not be measured on the full catalogue**: its workspace
         ran out of credits at the start of that arm (23 ⛔, relabelled after
         verifying the provider error; the runner now classifies
         `out of credits`/`spend limit`/`rate limit` as QUOTA so it cannot pose
         as a wrong answer again). In the core arm Codex ignored the server on
         5 cases and answered from recall.
      **Decision:** keep the catalogue — it does not cost correctness and it
      absorbs the friction a model hits writing Sage by hand — but stop calling
      40 tools a differentiator on *outcomes*; the defensible claims are the
      friction absorption, `verify_claim` against wrong-confident answers, and
      the session model. Follow-ups: a harder case tier; the friction list in
      (2); re-run Codex/full when credits exist (`make tool-surface
      TOOL_SURFACE_CLIS=codex`).
      4. **A hard tier now exists, and it sharpens the conclusion** (added
         2026-09-16; `--tier hard`, 14 cases in `extended_cases.py`, each
         carrying the SageMath expression that re-derives its answer so
         `test_every_hard_case_answer_is_what_sage_computes` checks the lot
         against the installed Sage). Measured against Claude Code:

         | arm | correct | tool calls |
         | --- | ---: | ---: |
         | no server | **4/14** | 0 |
         | core tools | **14/14** | 14 |
         | full catalogue | **14/14** | 14 |

         The tier **does** separate server from no server — +10 of 14, where the
         standard tier managed 60/63 with no server at all — so the arms can be
         compared on correctness again. And **the full catalogue buys nothing
         over core tools on hard mathematics**: identical scores, exactly one
         tool call per case in both arms, no retries. So the +5/46 the standard
         tier showed for the full catalogue was friction absorption on awkward
         Sage, not reach: on problems a model cannot fake, one `evaluate_sage`
         call is enough. The helpers are a usability feature, not a capability
         one, which is a stronger and more defensible claim than the roadmap's
         original one. Hard-tier numbers are Claude only (Codex out of credits,
         Gemini not re-run); it is also markedly slower, one case hitting the
         300-second cap without a server.

Smithery is **not pursued** (decided 2026-08-24). Since its Arcade.dev
acquisition, `smithery.ai/new` publishes only a public HTTPS endpoint — the
GitHub/`smithery.yaml` connect is gone. Listing would mean hosting a public,
authenticated code-execution endpoint with a Sage runtime, which contradicts
the local-only, no-auth posture in `SECURITY.md`. `smithery.yaml` was removed as
dead config. Revisit only if a hosted deployment is built for its own reasons.
