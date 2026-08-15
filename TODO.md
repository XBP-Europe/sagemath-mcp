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

## Letting more legitimate mathematics through

From categorising all 5,266 refusals SageMath's own doctest corpus provokes
(ROADMAP.md has the framing; REVIEW_ACTIONS.md items 45 and 46 have the security
half). Each count is measured, each case reproduced against SageMath 10.9.

- [ ] **`global`.** Its sibling `nonlocal` is done: it rebinds inside an
      enclosing function and provably cannot reach the namespace, so the flag
      refusing it was costing every closure that counts something and nothing
      was defending it. `global` is the half that needs thought, because it
      binds at module scope where the caller's names sit alongside the ones this
      server offers. `_bound_names` already records what it declares and item
      37's withheld-name rule governs what that binding may name, so the work is
      to decide whether those two are enough rather than to write new machinery.

- [ ] **Names created at run time by `inject_variables()`.** 741 refusals of
      undeclared symbols, and this is the honest part: `R.<u, v> = QQ[]` works
      because the preparser binds `u` and `v` statically, but
      `A = SomeAlgebra(...)` followed by `A.inject_variables()` creates names no
      static analysis can see. A namespace diff would find them and must not be
      used — `lazy_import('os', 'system')` gains a binding the same way, which
      is why `_CALLER_BOUND_NAMES` is built from the AST. The narrow version is
      to recognise the call itself and learn the names from the object's own
      `variable_names()`, which is delicate enough to deserve its own pass.

- [ ] **Refusal messages that name the native equivalent.** ~2,300 refusals.
      `gap('SymmetricGroup(5)')` is told only that `gap` is not offered, when
      the answer is `SymmetricGroup(5)` itself or `libgap`; `singular('...')` is
      `I.groebner_basis()`; `attrcall('bruhat_le')` is
      `lambda a, b: a.bruhat_le(b)`. The pattern already exists for imports —
      numpy is pointed at `matrix(RDF, ...)` — and
      `test_the_blocked_interfaces_do_not_block_the_mathematics` already proves
      each equivalent works, so this is writing down what that test knows.

- [ ] **Execute the corpus rather than only validating it.** The sweep proves
      this server would *accept* Sage's mathematics; it does not prove Sage
      computes it. A bounded spike measured 26.5 examples/second and 98.3%
      output agreement using SageMath's own `SageOutputChecker`. Sampled
      nightly, never on the pull-request path. See
      [docs/sage_doctest_corpus.md](docs/sage_doctest_corpus.md) for the three
      things a real harness needs — expected exceptions, block dependencies, and
      warning output — each of which caused a false failure in the spike.
