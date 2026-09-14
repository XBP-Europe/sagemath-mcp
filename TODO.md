# TODO

The live queue. Completed items are not kept here — every shipped change is in
[CHANGELOG.md](CHANGELOG.md), and the security work is written up with its
reproduction and regression test in [REVIEW_ACTIONS.md](REVIEW_ACTIONS.md). This
file carried 31 ticked boxes duplicating both, several of them years of context
out of date.

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
- [ ] Passagemath runtime extra to cut install footprint. Evaluated 2026-09-06
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
      the smoke gate on first try — 10.8.10 and 10.8.11 both failed it (#2836),
      so the counter is at zero (§ evaluation blockers).
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
- [ ] **`external_docs/reference_html`** vendors Sage's own HTML (102 KB) into an
      MIT repo — fetch at generation time instead of committing it.
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
- [ ] Extra install paths worth their weekend: a conda-forge recipe (where Sage
      users actually live), a nix flake (`nix run github:…` incl. Sage), and an
      `.mcpb` bundle for one-click Claude Desktop install. Trust signals: PyPI
      Trusted Publishing PEP 740 attestations, an SBOM on releases, SLSA image
      provenance, an OpenSSF Scorecard badge.
- [ ] **Measure the tool surface before defending it.** The roadmap argues 40
      tools is a differentiator; the reviewer argues `evaluate_sage` covers most
      of it and a 12-tool build might score the same. Use the CLI harness to
      test a reduced set vs the full catalogue on pass rate before deciding.

Smithery is **not pursued** (decided 2026-08-24). Since its Arcade.dev
acquisition, `smithery.ai/new` publishes only a public HTTPS endpoint — the
GitHub/`smithery.yaml` connect is gone. Listing would mean hosting a public,
authenticated code-execution endpoint with a Sage runtime, which contradicts
the local-only, no-auth posture in `SECURITY.md`. `smithery.yaml` was removed as
dead config. Revisit only if a hosted deployment is built for its own reasons.
