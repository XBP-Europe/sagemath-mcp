# conda-forge recipe

`meta.yaml` packages `sagemath-mcp` for [conda-forge](https://conda-forge.org/),
so that people who already run Sage from conda-forge (`conda install sage`) can
add the server to the same environment instead of reaching for pip.

**Status: ready to submit, not yet submitted.** Submitting means opening a pull
request against [conda-forge/staged-recipes](https://github.com/conda-forge/staged-recipes),
which is an external review with its own cycle and lists a maintainer by GitHub
handle — a decision for the repository owner, not something to do by reflex.
Issue #93 tracks it.

## Why it is buildable

Every runtime dependency exists on conda-forge, including the one that caps the
package:

| Dependency | Required | On conda-forge |
| --- | --- | --- |
| `fastmcp` | `>=3.4.7,<4` | 3.4.7 (and 4.0.3, which the cap excludes) |
| `pydantic` | `>=2.13.4` | yes |
| `anyio` | `>=4.14.2` | yes |
| `python` | `>=3.12` | yes |

The `fastmcp` cap is the one to watch: conda-forge's newest is 4.0.3, and this
package cannot use it until the cross-client cache-isolation suite passes on
fastmcp 4 (REVIEW_ACTIONS 68). 3.4.7 is still available, so the recipe resolves
today; if that build were ever removed, the recipe would stop resolving before
the cap is lifted.

## What it deliberately does not do

It does **not** depend on `sage`. The server runs `sage -python` from `PATH` at
run time and works equally with the `[passagemath]` extra or the hardened
container; a hard dependency would force a multi-gigabyte install on everyone.
The `about/description` says so, and the test section only runs `--help`, which
is the one command that works without a Sage runtime.

## Submitting

1. Fork `conda-forge/staged-recipes`, copy this file to
   `recipes/sagemath-mcp/meta.yaml`, and open a pull request.
2. The version and hashes must match the PyPI release being packaged.
   `tests/test_conda_recipe.py` keeps them in step with `pyproject.toml`, so run
   `make test` after any release bump and update this recipe in the same commit.
3. Once merged, conda-forge creates `sagemath-mcp-feedstock` and its bot opens a
   pull request there for every subsequent PyPI release. Add a README install
   line and a `conda-forge` badge at that point.
