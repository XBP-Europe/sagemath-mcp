# TODO

The live queue: open work only. Shipped changes are in
[CHANGELOG.md](CHANGELOG.md), security work is written up with its reproduction
and regression test in [REVIEW_ACTIONS.md](REVIEW_ACTIONS.md), and items are
removed from here once they ship or are decided against.

- [ ] **Lift the `fastmcp<4` cap — blocked upstream.** On fastmcp 4.x
      `Context.session_id` is a fresh UUID on every tool call, on every
      transport, so no stateful server keeps a client's state between calls.
      Reproduction, cause and the conditions for lifting the cap:
      `docs/fastmcp4_session_regression.md`. Reported as PrefectHQ/fastmcp#5134
      (2026-09-16). Last re-checked 2026-09-23 against 4.0.5, still the newest
      release: three calls on one connection, three session ids, and the issue
      has no replies. `.github/dependabot.yml` ignores major bumps of `fastmcp`
      and `fastmcp-slim` so a weekly PR cannot undo the cap by accident. Lift it
      when a release reports one session id per connection and
      `tests/test_cache_isolation.py` passes against it in the Sage container.

- [ ] **Clear the `sagemath-*` PyPI namespace question** with sage-devel. Sage
      upstream owns `sagemath-standard`/`sagemath-symbolics`/… and this is a
      third-party package in that namespace. A friendly ask today, a forced
      rename after adoption.

- [ ] **Reach the actual audience**: announce on sage-devel and the Sage Zulip;
      talk to CoCalc (hosted Sage). Lead with the doctest-corpus acceptance
      figure — the strongest single credibility claim.

- [ ] **Citability.** The Zenodo webhook is installed and active (#92), so the
      next release tag mints the first DOI. Then run
      `scripts/set_zenodo_doi.py <concept DOI>` to write it into `CITATION.cff`
      and the README badge, and close #92. Then the **JOSS paper**: the skeleton
      is `paper/paper.md`, built to PDF by `.github/workflows/paper.yml`. It is
      blocked on evidence of research use by others (JOSS requires it; our own
      benchmarks are supporting material only), the DOI, and the author's
      ORCID and sign-off on the AI usage disclosure.

- [ ] **conda-forge.** Submitted as conda-forge/staged-recipes#34875 (#101),
      bumped to 0.8.4 and green, waiting on a reviewer. The recipe is
      `packaging/conda/recipe.yaml`, kept in step with `pyproject.toml` by
      `tests/test_conda_recipe.py`. On merge: add the conda install line to
      README / USAGE / DISTRIBUTION, the `conda-forge` badge, and close #101.
