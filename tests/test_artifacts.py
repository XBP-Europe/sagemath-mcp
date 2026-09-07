"""The runtime artifact dispatch and the committed passagemath artifact set.

`_artifacts.py` chooses the allowlist / star-exports for the installed Sage.
These are pure-Python guards -- no Sage runtime -- over the dispatch logic and
the *shape* of the generated passagemath files. Their agreement with an actual
passagemath install is checked by the passagemath CI lane, the way
`allowlist.py` is checked against monolithic Sage.
"""

from __future__ import annotations

from sagemath_mcp import _artifacts
from sagemath_mcp.allowlist import ALLOWED_CALLER_NAMES as MONOLITHIC_ALLOWLIST


def test_dispatch_selects_the_monolithic_set_off_passagemath() -> None:
    """The unit environment has no passagemath, so the monolithic set is loaded."""
    assert _artifacts.IS_PASSAGEMATH is False
    assert _artifacts.ALLOWED_CALLER_NAMES is MONOLITHIC_ALLOWLIST


def test_is_installed_true_and_false() -> None:
    """Both arms of the probe: a package that is present and one that is not."""
    assert _artifacts._is_installed("pytest") is True
    assert _artifacts._is_installed("a-package-that-is-not-installed-xyzzy") is False


def test_passagemath_allowlist_is_a_frozenset_of_names() -> None:
    from sagemath_mcp import allowlist_passagemath

    names = allowlist_passagemath.ALLOWED_CALLER_NAMES
    assert isinstance(names, frozenset)
    assert len(names) > 1000
    assert all(isinstance(n, str) for n in names)


def test_passagemath_allowlist_excludes_the_denylisted_interfaces() -> None:
    """The interface classes and the passagemath-only startup helper must not be
    offered -- a guard that the file was generated with the denylist in place."""
    from sagemath_mcp import allowlist_passagemath

    names = allowlist_passagemath.ALLOWED_CALLER_NAMES
    for forbidden in ("Maxima", "Mathics3", "mathics3", "commence_startup"):
        assert forbidden not in names, f"{forbidden} leaked into the passagemath allowlist"


def test_passagemath_star_exports_shape() -> None:
    from sagemath_mcp import star_exports_passagemath

    star = star_exports_passagemath.STAR_EXPORTS
    assert isinstance(star, dict)
    assert len(star) == 15
    for module, exported in star.items():
        assert module.startswith("sage.")
        assert isinstance(exported, frozenset)
        assert exported and all(isinstance(n, str) for n in exported)
