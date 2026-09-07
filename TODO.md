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
- [ ] Consider making `scripts/generate_allowlist.py` classify rather than accept.
      Four separate findings had one root cause: the allowlist is generated as
      *whatever survives the namespace scrub*, so it inherits every gap in that
      scrub. A generator that refused to allowlist what it cannot classify as
      mathematical — module objects, callables whose provenance is not `sage.*` —
      would turn each of those into a loud failure at generation time instead of
      a probe finding it later. Bigger than any of the individual fixes, and it
      needs its own round of testing against real Sage.
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
- [ ] **Optional HTTP auth.** The posture (SECURITY.md: no auth, the container
      is the boundary, keep it loopback) is deliberate and stays the default,
      but an optional bearer-token FastMCP auth provider — and making the
      Dockerfile's `0.0.0.0` bind an explicit, loudly-noted opt-in — is a fair
      refinement for anyone fronting it. Not a blocker; a deliberate opt-in.
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
- [ ] **README is a manual, not a front door** (1,593 lines, 17 badges). Trim to
      ~150: what it is, one working install path (lead with the GHCR image
      one-liner, which bundles Sage), one client config, three example prompts,
      links out. Move the tool reference to `docs/`, drop the embedded changelog,
      trim badges. Fold in the verified `verify_claim` + doctest-corpus number.

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
