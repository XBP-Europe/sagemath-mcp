# conda-forge recipe

`recipe.yaml` packages `sagemath-mcp` for [conda-forge](https://conda-forge.org/),
so that people who already run Sage from conda-forge (`conda install sage`) can
add the server to the same environment instead of reaching for pip.

It is in the **v1 recipe format** ([CEP 13]/[CEP 14], built by
[rattler-build]). staged-recipes marked the older v0 `meta.yaml` format
deprecated in August 2026 and says v0 submissions are "less likely to be
reviewed in a timely manner", so v1 is what gets submitted and therefore the
only copy kept here.

**Status: on conda-forge since 2026-10-09.** conda-forge/staged-recipes#34875
merged and conda-forge created
[`sagemath-mcp-feedstock`](https://github.com/conda-forge/sagemath-mcp-feedstock),
which now owns the published recipe. This copy is the one the submission came
from, and stays here because `tests/test_conda_recipe.py` checks it against
`pyproject.toml` on every run; a dependency change shows up here first.

[CEP 13]: https://github.com/conda/ceps/blob/main/cep-0013.md
[CEP 14]: https://github.com/conda/ceps/blob/main/cep-0014.md
[rattler-build]: https://rattler-build.prefix.dev

## Why it is buildable

Every runtime dependency exists on conda-forge (re-checked 2026-10-09):

| Dependency | Required | On conda-forge |
| --- | --- | --- |
| `fastmcp` | `>=4.0.8,<5` | 4.1.0 |
| `pydantic` | `>=2.13.4` | 2.14.0 |
| `anyio` | `>=4.14.2` | 4.15.1 |
| `hatchling` | `>=1.32.0` | 1.32.4 |
| `python` | `>=3.12` | yes |

The `fastmcp` cap is the one to watch: a fastmcp 5 release on conda-forge does
not reach this package until the recipe's `<5` is lifted, here and on the
feedstock.

## What it deliberately does not do

It does **not** depend on `sage`. The server finds `sage` at run time -- on
`PATH`, or beside its own Python in the same environment -- and works equally
with the `[passagemath]` extra or the hardened container; a hard dependency
would force a multi-gigabyte install on everyone.
The `about/description` says so, and the test section only runs `--help`, which
is the one command that works without a Sage runtime.

## Keeping the feedstock in step

1. After each PyPI release, conda-forge's bot opens a version pull request on
   the feedstock with the new version and sdist hash. CI there builds and tests
   it; a maintainer merges it and the package publishes.
2. The bot is reliable only for the version and hash. A change to the runtime
   dependencies or the Python floor in `pyproject.toml` has to be made on the
   feedstock by hand, in the bot's pull request or one of its own; update this
   copy in the same release so the test keeps describing what is published.
3. `extra/recipe-maintainers` lists `csteinlxbp`, who is publicly on the hook
   for the feedstock, including the bot's pull requests and any user issues.
   conda-forge grants that list push access through the `sagemath-mcp` team.
   A test asserts the handle rather than leaving it to a copy-paste.
