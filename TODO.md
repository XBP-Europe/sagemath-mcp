# TODO

The live queue. Completed items are not kept here — every shipped change is in
[CHANGELOG.md](CHANGELOG.md), and the security work is written up with its
reproduction and regression test in [REVIEW_ACTIONS.md](REVIEW_ACTIONS.md). This
file carried 31 ticked boxes duplicating both, several of them years of context
out of date.

- [ ] From the 2026-08-24 field survey, one feature remains (roadmap has the
      mechanism): outcome benchmarks (GSM8K/MATH deltas) via the existing CLI
      harness. A passagemath runtime extra to cut install footprint is also
      open. `verify_claim` shipped 2026-09-06 (`tools/verify.py`).
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
