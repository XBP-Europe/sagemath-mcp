# TODO

The live queue: open work only. Shipped changes are in
[CHANGELOG.md](CHANGELOG.md), security work is written up with its reproduction
and regression test in [REVIEW_ACTIONS.md](REVIEW_ACTIONS.md), and items are
removed from here once they ship or are decided against.

- [ ] **Clear the `sagemath-*` PyPI namespace question** with sage-devel. Sage
      upstream owns `sagemath-standard`/`sagemath-symbolics`/… and this is a
      third-party package in that namespace. A friendly ask today, a forced
      rename after adoption.

- [ ] **Reach the actual audience**: announce on sage-devel and the Sage Zulip;
      talk to CoCalc (hosted Sage). Lead with the doctest-corpus acceptance
      figure — the strongest single credibility claim.

- [ ] **Reduce Gemini's intermittent client errors** and compare guidance
      changes using the repeated-run method in [TESTING.md](TESTING.md). A
      single run is not evidence that a change reliably reduces retries; the
      [2026-11-23 comparison](docs/gemini_client_comparison_2026-11-23.md)
      records the earlier small-sample baseline; the
      [PARI guidance comparison](docs/gemini_pari_guidance_comparison_2026-11-23.md)
      records a follow-up.

- [ ] **Directory listings that need the maintainer's accounts** (see
      [DISTRIBUTION.md](DISTRIBUTION.md#directories-and-plugin-catalogs)):
      submit the Claude Code plugin at claude.ai/directory/manage; claim the
      MCP Market and LobeHub listings; optionally claim the HOL listing.

- [ ] **The JOSS paper.** The skeleton is `paper/paper.md`, built to PDF by
      `.github/workflows/paper.yml`. The Zenodo concept DOI now exists
      (10.5281/zenodo.22939422, recorded 2026-09-24), so what still blocks it
      is evidence of research use by others (JOSS requires it; our own
      benchmarks are supporting material only), and the author's ORCID and
      sign-off on the AI usage disclosure.
