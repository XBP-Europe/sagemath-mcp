# TODO

The live queue. Completed items are not kept here — every shipped change is in
[CHANGELOG.md](CHANGELOG.md), and the security work is written up with its
reproduction and regression test in [REVIEW_ACTIONS.md](REVIEW_ACTIONS.md). This
file carried 31 ticked boxes duplicating both, several of them years of context
out of date.

- [ ] **Release blocker: cut 0.5.1.** Several security fixes are unreleased while
      0.5.0 is the live version on PyPI and GHCR, and they are not minor ones —
      `pari('system("id")')` executed a shell and `operator.attrgetter` reached
      arbitrary Sage internals ([review items 30-34](REVIEW_ACTIONS.md)). The
      behaviour change in the same window (`x, y, z, t` predefined; callers lost
      imports, `show`, `latex` and the CAS interfaces) is user-visible and needs
      the changelog entry it already has.
- [ ] Consider making `scripts/generate_allowlist.py` classify rather than accept.
      Four separate findings had one root cause: the allowlist is generated as
      *whatever survives the namespace scrub*, so it inherits every gap in that
      scrub. A generator that refused to allowlist what it cannot classify as
      mathematical — module objects, callables whose provenance is not `sage.*` —
      would turn each of those into a loud failure at generation time instead of
      a probe finding it later. Bigger than any of the individual fixes, and it
      needs its own round of testing against real Sage.
- [ ] Smithery: connect the repository at https://smithery.ai/new with an account that owns it; `smithery.yaml` is already in place and read from the default branch.
- [ ] Glama: already auto-indexed; claim the listing at https://glama.ai with a GitHub account that owns the repository ([review item 7](REVIEW_ACTIONS.md)) — needs repository-owner access.
