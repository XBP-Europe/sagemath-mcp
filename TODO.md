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

- [ ] **The JOSS paper.** The skeleton is `paper/paper.md`, built to PDF by
      `.github/workflows/paper.yml`. The Zenodo concept DOI now exists
      (10.5281/zenodo.22939422, recorded 2026-09-24), so what still blocks it
      is evidence of research use by others (JOSS requires it; our own
      benchmarks are supporting material only), and the author's ORCID and
      sign-off on the AI usage disclosure.

- [ ] **conda-forge.** Submitted as conda-forge/staged-recipes#34875 (#101),
      bumped to 0.9.1 and green on 2026-09-26, waiting on a reviewer. The recipe is
      `packaging/conda/recipe.yaml`, kept in step with `pyproject.toml` by
      `tests/test_conda_recipe.py`. On merge: add the conda install line to
      README / USAGE / DISTRIBUTION, the `conda-forge` badge, and close #101.
