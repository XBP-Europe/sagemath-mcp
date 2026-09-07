"""Runtime-specific security artifacts: the allowlist and star-exports for the
installed Sage.

Two runtimes are supported. Monolithic SageMath (the Docker image this
repository tests against) and passagemath (the pip `[passagemath]` extra) ship
different ``sage.all`` namespaces -- 1875 vs 1856 public names, a 24-name
difference -- so each has its own generated, never-hand-edited allowlist and
star-export map: ``allowlist.py`` / ``star_exports.py`` for monolithic,
``allowlist_passagemath.py`` / ``star_exports_passagemath.py`` for passagemath.

The set to load is chosen once, at import, by whether ``passagemath-standard``
is installed -- the same probe the generators and the drift tests use, and the
same one described in ``docs/passagemath_evaluation.md``. Every consumer imports
``ALLOWED_CALLER_NAMES`` and ``STAR_EXPORTS`` from here, so nothing downstream
needs to know which runtime it is on.

The baked denylist (``_DANGEROUS_SAGE_NAME_LIST`` in ``_sage_worker.py``) does
*not* need a second copy: passagemath's danger set is covered by the monolithic
baked list plus the hand-maintained ``_DANGEROUS_BARE_NAMES`` (which carries the
one passagemath-only name, ``commence_startup``), so the same strip is correct
on both -- names absent from a runtime are simply not there to strip.
"""

from __future__ import annotations

import importlib.metadata


def _is_installed(distribution: str) -> bool:
    try:
        importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return False
    return True


#: True when running on passagemath rather than monolithic SageMath.
IS_PASSAGEMATH = _is_installed("passagemath-standard")

# The passagemath branch runs only under the passagemath CI lane, never in the
# monolithic coverage-gated suite, so it is exempt from coverage.
if IS_PASSAGEMATH:  # pragma: no cover
    from .allowlist_passagemath import ALLOWED_CALLER_NAMES
    from .star_exports_passagemath import STAR_EXPORTS
else:
    from .allowlist import ALLOWED_CALLER_NAMES
    from .star_exports import STAR_EXPORTS

__all__ = ["ALLOWED_CALLER_NAMES", "IS_PASSAGEMATH", "STAR_EXPORTS"]
