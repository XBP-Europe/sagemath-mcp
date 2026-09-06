# TODO

The live queue. Completed items are not kept here — every shipped change is in
[CHANGELOG.md](CHANGELOG.md), and the security work is written up with its
reproduction and regression test in [REVIEW_ACTIONS.md](REVIEW_ACTIONS.md). This
file carried 31 ticked boxes duplicating both, several of them years of context
out of date.

- [ ] From the 2026-09-06 external review, in its recommended order (foundations
      before features; the fastmcp<4 cap and the verifier's exactness fixes from
      the same review already landed — REVIEW_ACTIONS 68, `tools/verify.py`):
      - **Explicit workspace identity.** The MCP spec has removed protocol-level
        sessions in favour of explicit application handles, and fastmcp 4 already
        broke `ctx.session_id`-based routing once. Give workspaces caller-visible
        handles instead of leaning on transport session identity.
      - **One canonical hardened onboarding path.** `setup_sage_container.sh`
        defaults to a moving image tag with none of the memory/PID/read-only
        hardening compose and Helm apply; the README quick-start `docker run`
        drops the image's host binding. Make the hardened path the copy-paste
        default and mark dev paths as dev.
      - **Nightly CLI checks fail loudly on zero clients.** The 2026-09-06 run
        skipped all three clients (missing keys) and still reported success.
      - **Worker/session robustness.** Worker startup happens outside the
        manager's creation lock (two simultaneous first requests to one session
        can double-launch); no application-level ceiling on session count;
        `/health` and the Helm probe don't exercise a Sage evaluation;
        `_evaluate_structured` bypasses the evaluation metrics.
      - **Release validation.** Gate publication on a real-Sage stateful smoke
        test of the built image; the manual `dry_run` input does not suppress the
        Docker job's `push: true`.
      - **README language.** Replace "run any SageMath code"/"full access" with
        the supported-subset description; surface the helper tools' fresh-
        namespace semantics next to `evaluate_sage`'s "LAST RESORT" guidance
        rather than deep in the session-semantics section.
- [ ] From the 2026-08-24 field survey, one feature remains (roadmap has the
      mechanism): outcome benchmarks (GSM8K/MATH deltas) via the existing CLI
      harness — per the 2026-09-06 review, compare no-tools vs `evaluate_sage`
      only vs the full catalogue, include iterative advanced mathematics beyond
      GSM8K/MATH, and measure wrong-confident answers, refusals, recovery,
      latency and tool-call count. A passagemath runtime extra to cut install
      footprint is also open (evaluation in progress, docs/passagemath_evaluation.md).
      `verify_claim` shipped 2026-09-06 (`tools/verify.py`).
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

Smithery is **not pursued** (decided 2026-08-24). Since its Arcade.dev
acquisition, `smithery.ai/new` publishes only a public HTTPS endpoint — the
GitHub/`smithery.yaml` connect is gone. Listing would mean hosting a public,
authenticated code-execution endpoint with a Sage runtime, which contradicts
the local-only, no-auth posture in `SECURITY.md`. `smithery.yaml` was removed as
dead config. Revisit only if a hosted deployment is built for its own reasons.
