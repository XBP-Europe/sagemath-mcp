# TODO

The live queue: open work only. Shipped changes are in
[CHANGELOG.md](CHANGELOG.md), security work is written up with its reproduction
and regression test in [REVIEW_ACTIONS.md](REVIEW_ACTIONS.md), and items are
removed from here once they ship or are decided against.

- [ ] **Lift the `fastmcp<4` cap by removing our dependence on per-connection
      identity.** On fastmcp 4.x `Context.session_id` is a fresh UUID on every
      tool call, so the default session loses its variables between calls. The
      root cause, confirmed against 4.0.8 on 2026-09-24: the client picks the
      protocol era, and on the 2026-07-28 era every request gets its own
      `Connection`. By design, nothing lasts as long as the client session, so
      waiting for upstream (PrefectHQ/fastmcp#5134) is no longer the plan.
      Details in `docs/fastmcp4_session_regression.md`. The work:
      anchor the default session to the process on stdio (one client per
      process); on HTTP, where one process serves many clients, refuse a call
      without a `workspace_token` on the modern era and point to
      `start_sage_session` rather than hand out a fresh session per call. Lift
      the cap when `tests/test_cache_isolation.py` passes under 4.x in the Sage
      container on both transports. Until then the cap is harmless: 3.4.7 only
      speaks the handshake, so every client uses the legacy era, and
      `.github/dependabot.yml` ignores fastmcp major bumps so a weekly PR
      cannot undo it.

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
