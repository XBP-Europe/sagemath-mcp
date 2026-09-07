# passagemath as an alternative runtime — evaluation

Evaluated 2026-09-06, against passagemath 10.8.9/10.8.10/10.8.11 on Linux
x86_64 (Python 3.12, uv), with the monolithic comparison namespace taken from
the `sagemath/sagemath:10.9` container this repository tests against. Every
number below marked *measured* was produced on this machine during the
evaluation; everything else cites its source. This is the evaluation the
roadmap item "passagemath runtime extra" (field survey, 2026-08-24) asked for.

## Verdict

**Adopt — pinned to a verified release, after two pieces of prework.** The
technical fit is better than the roadmap sketch assumed: `pip install
passagemath-standard` yields a runtime where `from sage.all import *` works,
this repository's `_sage_worker.py` runs **unmodified** (passagemath even ships
a `sage` script that accepts `-python`, so the existing launch path needs no
change), and all 33 Sage-backed tool domains pass an end-to-end sweep on
10.8.9 — GAP groups, PARI elliptic curves including `rank()`, Singular Gröbner
bases, Maxima calculus, `QQbar`/`AA`, interval fields, plotting to PNG, all of
it. The allowlist diff between the two runtimes is 24 names. What forbids
tracking passagemath's latest release is passagemath's own release QA: the two
most recent stable releases *each* shipped a broken core backend on Linux
x86_64 (10.8.10/10.8.11 regress the Maxima library interface, breaking
`solve`/`integrate`/`limit`/`desolve`; 10.8.11 is missing its GAP wheel for
cp311–cp313 manylinux x86_64). Both were found here, not in their tracker. The
answer is an exact version pin verified by a cold-install smoke gate in CI —
which converts their release risk into this project's existing engine-bump
discipline — plus one real piece of engineering: the star-exports/denylist
derivation is layout-sensitive and over-fires under passagemath (6 of 15
modules survive, for reasons that are artifacts of the derivation, not
dangers). Blockers and triggers are at the end.

## 1. Current state of passagemath (verified 2026-09-06)

- **Project.** Compatible fork of SageMath by the modularization author,
  created October 2024; the pip modularization was completed in passagemath
  10.5.29 (May 2025). Main repo: <https://github.com/passagemath/passagemath>
  (105 stars, ~150 open issues, active daily). 100+ distributions under
  <https://pypi.org/org/passagemath/>.
- **Release cadence and Sage tracking.** Stable series 10.8.x; 10.8.10
  released 2026-08-25, 10.8.11 released 2026-09-05, i.e. roughly every 2–3
  weeks with rc0–rc4 phases (<https://github.com/passagemath/passagemath/releases>).
  10.8.x branched from SageMath 10.9.beta3 and 10.8.11 carries backports from
  SageMath 10.10.beta9 — one beta behind this repository's beta channel
  target. A 10.10.x development series exists (10.10.1a0 on PyPI, sparse
  wheels).
- **Structure.** `passagemath-standard` is a metapackage:
  `passagemath-standard-no-symbolics` + `passagemath-symbolics` +
  `passagemath-maxima`, plus ~70 optional extras (gap3, macaulay2, latte,
  databases, …) (*measured*, from its PyPI `requires_dist`:
  <https://pypi.org/project/passagemath-standard/>). The transitive
  passagemath set for a plain install is 50 distributions.
- **Platforms** (spot-checked at 10.8.9 for `passagemath-{symbolics, pari,
  singular, maxima, flint, plot}`): cp312 wheels exist for manylinux x86_64
  **and** aarch64, macOS x86_64 **and** arm64. Native Windows is partial
  (`plot` yes; `pari`/`singular`/`maxima` no) — consistent with the README's
  "partial functionality" claim for native Windows. Python 3.11–3.14 for
  10.8.x (`requires_python: <3.15,>=3.11`, *measured*).
- **`uvx` story.** Maintainer-confirmed stable pattern:
  `uvx --from "passagemath-environment[sage]" sage`
  (<https://github.com/passagemath/passagemath/issues/2373>). This is exactly
  the peer-parity mechanism the field survey wanted.

## 2. Minimal install providing `sage.all` (measured)

`uv pip install "passagemath-standard==10.8.10"` on Python 3.12, Linux x86_64:

| Quantity | Value |
| --- | --- |
| Packages installed | 125 (50 passagemath + scientific stack) |
| Compressed download, passagemath wheels only | **1.00 GB** |
| Download + prepare time (this connection) | 44.6 s |
| Install (link) time after download | 8.1 s |
| venv on disk | **3.8 GB** |
| `sagemath/sagemath:10.9` Docker image, for comparison | 3.02 GB |
| `from sage.all import *`, cold interpreter | 2.4 s |

Two honest corrections to the roadmap's framing:

- **`import sage.all` works outright.** Not just submodule imports:
  `passagemath-standard` provides the full aggregating `sage.all`, and the
  worker's `from sage.all import *` preload runs as-is (*measured*). The
  per-distribution `sage.all__sagemath_*` modules exist but are not needed.
- **The win is distribution mechanics, not disk.** 3.8 GB installed is *more*
  than the 3.02 GB image. What changes is everything around it: a 1 GB
  download instead of a 3 GB image pull, no Docker daemon, no local Sage
  build, uv cache reuse across venvs, and a `uvx`-shaped one-liner. A
  significantly smaller install would mean hand-picking distributions per tool
  domain (dropping the ~190 MB of GAP data wheels, eclib, etc.) — possible,
  but each dropped distribution is a tool that silently degrades; not worth it
  for the first iteration.

`passagemath-environment` installs `sage`, `sage-python` and friends into the
venv's `bin/`, and `sage -python` works (*measured*) — so
`SageSession._launch_worker`'s non-pure path (`sage -python -m
sagemath_mcp._sage_worker`) functions with **zero code change** when the venv
is on `PATH`.

## 3. Coverage of the 33 Sage-backed tool domains (measured)

An end-to-end sweep on **10.8.9** — one probe per tool domain, run through
`preparse()` exactly as `evaluate_sage` would — passed **33 of 33**: solve,
integrate/definite integral/limit/series/`simplify_full`/`desolve`/symbolic
sum (Maxima via ECL), matrices and eigenvalues, PARI number theory
(`factor(2^64+1)`, `is_prime(2^127-1)`), combinatorics, graphs including
`automorphism_group` (GAP-backed) and `chromatic_number`, permutation groups /
`SymmetricGroup` conjugacy classes / direct `libgap` (GAP as a wheel, incl.
small/primitive/transitive-groups data wheels), elliptic curves including
`E.rank()` (eclib/mwrank ships as `passagemath-eclib`), `codes.HammingCode` +
`minimum_distance`, `propcalc` truth tables, Gröbner bases and multivariate
factoring (Singular as a wheel), `QQbar`/`AA` with `minpoly`,
`RealIntervalField(128)`/`ComplexIntervalField` (what `verify_claim` needs),
`find_root`, gradients, `plot`/`plot3d` saved to PNG (matplotlib), polyhedra,
`RealDistribution`, `LLL`, `NumberField.class_number()`, the preparser
(`2^10` → `Integer(2)**Integer(10)`), and `sage_eval`.

The repository's actual worker was also run unmodified against 10.8.9 over its
JSON protocol: preparsed evaluation, a Maxima-backed `solve`, and the security
refusal path all behave identically to the monolithic container (*measured*;
the refusal message for a non-offered name is byte-identical in shape).

**All five load-bearing backends ship as wheels**: GAP (`passagemath-gap`,
104 MB wheel + data wheels), PARI (`passagemath-pari`, 87 MB), Singular
(`passagemath-singular`, 33 MB, pulled via `passagemath-schemes`), Maxima +
ECL (`passagemath-maxima` 31 MB + `passagemath-ecl` 88 MB), matplotlib via
`passagemath-plot`. None of them needs a system package.

## 4. Known gaps and issues

### Found in this evaluation (both on the newest releases)

- **10.8.10 and 10.8.11: `maxima_lib` fails at import on Linux x86_64**
  (*measured on 10.8.10; 10.8.11 ships the same Maxima 5.49/ECL 26.5.5 pair
  and is presumed affected, unverified*). `import sage.interfaces.maxima_lib`
  triggers ECL compilation of Maxima's Lisp share modules
  (`load(linearalgebra)`) into `~/.maxima/binary/...`; the compile emits
  `.c`/`.data`/`.eclh` but never a `.fas` (the link stage fails even with gcc
  present), and after ~60 s the import dies with `RuntimeError: ECL says:
  THROW: The catch MACSYMA-QUIT is undefined`. That takes down `solve`,
  `integrate`, `limit`, `series` (via Maxima paths), `simplify_full`,
  `desolve` — the machinery behind at least 8 of this server's tools. The
  regression came in with the Maxima 5.49 / ECL 26.5.5 upgrade merged for
  10.8.10 (<https://github.com/passagemath/passagemath/issues/2679>, closed
  2026-08-23). **10.8.9 is unaffected** — first `solve` answers in 1.0 s with
  no compile step. As of 2026-09-06 no matching issue exists in their tracker
  (searched `MACSYMA-QUIT`, `maxima_lib`); verified on one host only
  (Debian-family glibc, tmpfs venv, gcc available), so a platform-specific
  component cannot be excluded. Worth filing upstream either way.
- **10.8.11: `passagemath-gap` is missing manylinux x86_64 wheels for
  cp311–cp313** (*measured* from PyPI: 20 files vs 31 for 10.8.10; cp314
  x86_64 and all aarch64/macOS wheels are present). Since the metapackage pins
  `~=10.8.11.0`, installing 10.8.11 on Python 3.12/x86_64 forces an sdist
  build of GAP. Possibly a still-uploading artifact — the release was cut
  2026-09-05 — but rc3 had the same gap, and it is exactly the failure mode an
  exact-pin-plus-smoke-gate protects against.

### Structural differences from monolithic Sage (measured, 10.8.10 vs 10.9)

`sage.all` namespaces: 1856 public names (passagemath) vs 1875 (monolithic).

- **Missing under passagemath (24):** optional-database wrappers
  (`SteinWatkinsAllData/PrimeData`, `JonesDatabase`, `SymbolicData`,
  `cunningham_prime_factors`, the five modular-polynomial/correspondence
  database classes, `zeta_zeros` — their data packages are extras, not part of
  `standard`), optional interfaces (`Mathics`/`mathics`, `libgiac`, `sympow`,
  `install_doc`), and a few names that entered Sage after 10.9.beta3
  (`TamariBlossomingTree(s)`, `carlitz_bernoulli/factorial`,
  `PseudoDifferentialOperatorRing`, `is_ProductProjectiveSpaces`,
  `richcmp_method`). None backs a tool; all were already refusable names.
- **New under passagemath (5):** `Maxima`, `Mathics3`, `mathics3`, `runsnake`,
  `x`. `runsnake` is already on the baked denylist. `Maxima`, `Mathics3`,
  `mathics3` are **not** — they are interface classes/objects (a `Maxima`
  instance evaluates arbitrary Maxima input) and belong on the passagemath
  denylist, not its allowlist. `x` is predefined in passagemath's `sage.all`
  itself; harmless (the worker binds `PREDEFINED_SYMBOLS` regardless), but the
  worker's comment that "importing sage.all does not even provide x" is
  monolithic-specific, and the `symbols.py` agreement test should be run
  against both runtimes.

Doctest compatibility was not independently measured; the doctest corpus sweep
(`docs/sage_doctest_corpus.md`) should simply be run against the pinned
passagemath before the extra ships — the guardrail already exists.

## 5. Security-artifact implications (measured)

Both generators were run **unmodified** against the passagemath venv
(`PYTHONPATH=src <venv>/bin/python scripts/generate_allowlist.py`) — they
depend only on the stdlib and this package, so no porting was needed.

- **Allowlist**: 1872 names generated vs 1890 baked. Diff to review: **+3 /
  −21** — and all three additions (`Maxima`, `Mathics3`, `mathics3`) are
  denylist material, which is precisely the review the generation docs already
  prescribe. The passagemath namespace is, to within those 24 names, the same
  reviewed surface. The ongoing burden is a two-column version of the review
  that already happens per engine bump, over a diff this size.
- **Star exports**: only **6 of 15** curated modules screen clean under
  passagemath, and the drops are derivation artifacts, not new dangers.
  Diagnosed cause: `_dangerous_sage_names()` derives "names defined in the
  dangerous modules", and passagemath's modularized layout changes what those
  modules' namespaces contain — under 10.8.9 the derived danger set swallows
  ordinary names like `Integer`, `prod`, `parent`, `copy`, `cputime`, which
  then fail e.g. `sage.modular.dims` and `sage.rings.polynomial.real_roots`
  wholesale. Additionally `sage.misc.attached_files` (a
  `_DANGEROUS_SAGE_MODULES` provenance entry) does not import under
  passagemath, so the matches-no-names integration test would fail as written.
  **This is the one real engineering item**: the derivation needs to become
  layout-aware (attribute names by the value's `__module__`, tolerate a
  provenance module that is legitimately absent from the runtime) before a
  passagemath star-exports artifact is generated rather than accepted at 6/15.
- **Baked denylist**: the worker's scrub runs fine (names absent from the
  namespace are simply not there to strip), but the integration test that
  re-derives the list from the installed Sage needs a passagemath variant for
  the same two reasons (new interface names, one missing provenance module).

Estimated ongoing review burden per engine bump, once the prework is done: one
extra generated diff of the same order as today's (the 10.8.10 diff was 24
allowlist names + 3 denylist candidates), plus one extra weekly drift lane.
The roadmap priced this in; the measurement says the price is small.

## 6. Anyone else doing this

No MCP server or comparable LLM tool shipping passagemath as a runtime was
found (GitHub repo/code search for `passagemath` + MCP, web search,
2026-09-06). Downstream adoption so far is mathematical software curated by
the project itself (<https://github.com/passagemath/passagemath/issues/248>).
This project would be the first — which cuts both ways: differentiation, and
nobody else finding their regressions first (both issues in §4 were found
here).

## Integration sketch

Matched to the current codebase; the worker and launch path need no changes.

1. **pyproject extra** — exact pins, not ranges, because §4 shows why:

   ```toml
   [project.optional-dependencies]
   passagemath = [
       "passagemath-standard==10.8.9",   # bump only through the smoke gate
   ]
   ```

2. **Runtime selection** — `SageSession._launch_worker` already resolves
   `sage` on `PATH`, and passagemath provides it; the only genuinely new probe
   is *which artifact set to load*, decided inside the worker/security modules
   at import: `importlib.metadata.version("passagemath-standard")` (present ⇒
   passagemath set, absent ⇒ monolithic set). Ship
   `allowlist_passagemath.py` / `star_exports_passagemath.py` and a
   passagemath block for the baked denylist next to the existing files, same
   generated-never-hand-edited contract.
3. **Artifact generation** — the existing scripts already run against a
   passagemath venv; add a `--runtime` output-path switch and the
   layout-aware derivation fix from §5. `make allowlist-passagemath` becomes
   `uv run --with passagemath-standard==<pin> ...` — no Docker needed, which
   is new.
4. **CI** — a `passagemath` job on a plain runner: `uv pip install
   .[passagemath]`, then the integration suite and the doctest corpus sweep
   against it. Cold setup is ~1 minute (§2), versus pulling the 3 GB Sage
   image — this lane will be the *fast* one. The same job, run against a
   candidate pin, is the smoke gate for bumping it.
5. **Weekly drift job** — second lane in `audit.yml`'s allowlist job
   installing the pinned passagemath instead of exec-ing into the container;
   same fail-into-an-issue plumbing.
6. **Docs** — README/USAGE install matrix (per Key Conventions), including
   the honest numbers: 1 GB download, 3.8 GB disk, Linux/macOS wheels, native
   Windows not supported for this server's tool set (no pari/singular/maxima
   wheels there).

### Cost table

| Cost | When | Size |
| --- | --- | --- |
| Layout-aware star-exports/denylist derivation (§5) | one-time | the real work; 1–2 focused days incl. tests |
| Second artifact set: generate + review | one-time | small — measured diff is 24 + 3 names |
| Denylist additions (`Maxima`, `Mathics3`, `mathics3`) + tests | one-time | small |
| Runtime probe + artifact dispatch | one-time | small; one metadata check |
| CI passagemath lane + pin-bump smoke gate | one-time | moderate; reuses the integration suite |
| Weekly drift lane ×2 | one-time setup, then recurring | small |
| Docs (README, USAGE, monitoring) | one-time | small |
| Per engine bump: regenerate/review two artifact sets | recurring | ~2× a small diff review |
| Per pin bump: cold-install smoke gate + corpus sweep | recurring | automated; human time only on failure |
| Upstream breakage triage (this project finds it first) | recurring | unpredictable; the pin caps the blast radius |

## Blockers before shipping, and reopen/advance triggers

Blocking the extra (all actionable now):

1. ~~The star-exports/denylist derivation fix (§5)~~ **DONE 2026-09-07**
   (REVIEW_ACTIONS 69). The `sage.interfaces.all` pass now attributes each name
   by the value's own `__module__` instead of adding the module's whole
   namespace, so the modularized layout no longer poisons the danger set with
   `Integer`/`parent`/`prod`. Verified a byte-for-byte no-op on monolithic (17
   agreement tests pass, artifacts regenerate identically) and 6/15 → 15/15 on
   `passagemath-standard==10.8.9`, real interfaces still flagged.
2. Pin verification: full integration suite + doctest corpus sweep against
   `passagemath-standard==10.8.9` (this evaluation ran a 33-domain probe and
   the worker protocol, not the full suites).
3. File the `maxima_lib` regression upstream and record the answer — it
   determines whether 10.8.10+ is ever pinnable or the pin waits for their
   Maxima 5.50 work (<https://github.com/passagemath/passagemath/issues/2632>).

Not blocking, but gating any move from "pinned extra" to "recommended install
path": two consecutive passagemath stable releases passing this project's
cold-install smoke gate on first try. The two most recent did not (§4); the
release *before* them did. If that record holds for a couple of cycles, the
pin can track stable with a one-release lag and this becomes the primary
distribution story the field survey asked for.
