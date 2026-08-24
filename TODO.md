# TODO

The live queue. Completed items are not kept here — every shipped change is in
[CHANGELOG.md](CHANGELOG.md), and the security work is written up with its
reproduction and regression test in [REVIEW_ACTIONS.md](REVIEW_ACTIONS.md). This
file carried 31 ticked boxes duplicating both, several of them years of context
out of date.

- [ ] From the 2026-08-24 field survey, two features remain (roadmap has the
      mechanisms): a `verify_claim` tool that re-checks a stated claim through a
      proof ladder, and outcome benchmarks (GSM8K/MATH deltas) via the existing
      CLI harness. A third, a passagemath runtime extra to cut install footprint,
      is also open.
- [ ] Consider making `scripts/generate_allowlist.py` classify rather than accept.
      Four separate findings had one root cause: the allowlist is generated as
      *whatever survives the namespace scrub*, so it inherits every gap in that
      scrub. A generator that refused to allowlist what it cannot classify as
      mathematical — module objects, callables whose provenance is not `sage.*` —
      would turn each of those into a loud failure at generation time instead of
      a probe finding it later. Bigger than any of the individual fixes, and it
      needs its own round of testing against real Sage.
- [ ] Smithery: the publish flow changed since `smithery.yaml` was committed —
      current docs describe hosted-URL and MCPB-bundle publishing, no longer the
      GitHub/`smithery.yaml` connect. Check smithery.ai/new for a legacy GitHub tab
      before choosing between hosting an endpoint and wrapping an MCPB bundle.
- [ ] Glama: `glama.json` is merged (#50, the org-repo claiming route); the
      browser-side Claim flow on the auto-indexed listing is the remaining step.
