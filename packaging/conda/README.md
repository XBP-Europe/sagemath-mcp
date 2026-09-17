# conda-forge recipe

`recipe.yaml` packages `sagemath-mcp` for [conda-forge](https://conda-forge.org/),
so that people who already run Sage from conda-forge (`conda install sage`) can
add the server to the same environment instead of reaching for pip.

It is in the **v1 recipe format** ([CEP 13]/[CEP 14], built by
[rattler-build]). staged-recipes marked the older v0 `meta.yaml` format
deprecated in August 2026 and says v0 submissions are "less likely to be
reviewed in a timely manner", so v1 is what gets submitted and therefore the
only copy kept here.

**Status: submitted 2026-09-17.** Issue #101 tracks the review.

[CEP 13]: https://github.com/conda/ceps/blob/main/cep-0013.md
[CEP 14]: https://github.com/conda/ceps/blob/main/cep-0014.md
[rattler-build]: https://rattler-build.prefix.dev

## Why it is buildable

Every runtime dependency exists on conda-forge, including the one that caps the
package (re-checked 2026-09-17):

| Dependency | Required | On conda-forge |
| --- | --- | --- |
| `fastmcp` | `>=3.4.7,<4` | 3.4.7 still available; 4.0.4 is latest and the cap excludes it |
| `pydantic` | `>=2.13.4` | 2.13.5 |
| `anyio` | `>=4.14.2` | 4.15.1 |
| `hatchling` | `>=1.32.0` | 1.32.0 |
| `python` | `>=3.12` | yes |

The `fastmcp` cap is the one to watch. This package cannot use fastmcp 4 until
`Context.session_id` stops changing on every tool call
([PrefectHQ/fastmcp#5134], REVIEW_ACTIONS 68), so the recipe resolves to 3.4.7.
If conda-forge ever dropped that build, the recipe would stop resolving before
the cap can be lifted.

[PrefectHQ/fastmcp#5134]: https://github.com/PrefectHQ/fastmcp/issues/5134

## What it deliberately does not do

It does **not** depend on `sage`. The server runs `sage -python` from `PATH` at
run time and works equally with the `[passagemath]` extra or the hardened
container; a hard dependency would force a multi-gigabyte install on everyone.
The `about/description` says so, and the test section only runs `--help`, which
is the one command that works without a Sage runtime.

## Submitting, and what happens after

1. Fork `conda-forge/staged-recipes`, copy this recipe to
   `recipes/sagemath-mcp/recipe.yaml`, and open a pull request.
2. The version and hash must match the PyPI release being packaged.
   `tests/test_conda_recipe.py` keeps them in step with `pyproject.toml` and
   checks the hash against PyPI, so run `make test` after any release bump and
   update this recipe in the same commit.
3. `extra/recipe-maintainers` lists a real GitHub handle, and whoever is listed
   is publicly on the hook for the feedstock — including the bot's pull requests
   and any user issues. A test asserts the handle rather than leaving it to a
   copy-paste.
4. Once merged, conda-forge creates `sagemath-mcp-feedstock` and its bot opens a
   pull request there for every subsequent PyPI release. Add a README install
   line and a `conda-forge` badge at that point.
