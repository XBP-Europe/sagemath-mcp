"""The allowlist generator classifies rather than accepts.

The generator used to emit whatever survived the namespace scrub, inheriting
every gap in it. It now refuses to allowlist a name it cannot place as
mathematics -- a module object from outside ``sage``, or a value of foreign
provenance that is not one of a small reviewed set -- and fails generation
instead. These tests exercise that classifier on synthetic values, with no Sage
runtime, so a regression in the guard is caught in the fast unit job.

The output-is-unchanged half of the contract (today's real namespace still
generates byte-identically) is covered by the integration drift test against real
Sage; here we pin the *rule*.
"""

from __future__ import annotations

import importlib.util
import types
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "generate_allowlist.py"
_spec = importlib.util.spec_from_file_location("generate_allowlist", _MODULE_PATH)
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)


def _sage_value():
    def f() -> None: ...
    f.__module__ = "sage.rings.integer"
    return f


class _Lazy:
    """Mimics sage.misc.lazy_import.LazyImport: named LazyImport, resolves via
    _get_object()."""

    def __init__(self, obj: object | None, *, fail: bool = False) -> None:
        self._obj = obj
        self._fail = fail

    def _get_object(self) -> object:
        if self._fail:
            raise ImportError("optional feature not installed")
        return self._obj


_Lazy.__name__ = "LazyImport"


def test_sage_provenance_is_accepted():
    assert gen._classification_failure("Integer", _sage_value()) is None


def test_a_sage_module_object_is_accepted():
    m = types.ModuleType("sage.coding.codes_catalog")
    assert gen._classification_failure("codes", m) is None


def test_a_foreign_module_object_is_refused():
    reason = gen._classification_failure("os", types.ModuleType("os"))
    assert reason is not None
    assert "os" in reason


def test_a_named_safe_module_is_accepted():
    # `math` and `operator` are the general modules the namespace legitimately
    # binds; any attribute access on them is still governed by the AST policy.
    assert gen._classification_failure("operator", types.ModuleType("operator")) is None
    assert gen._classification_failure("math", types.ModuleType("math")) is None


def test_builtins_provenance_is_accepted():
    # A path string / constant -- type().__module__ is 'builtins'. Safe here
    # because classification runs after the scrub, so no dangerous builtin remains.
    assert gen._classification_failure("SAGE_ROOT", "/opt/sage") is None


def test_unvetted_foreign_provenance_is_refused():
    def f() -> None: ...
    f.__module__ = "requests"
    reason = gen._classification_failure("get", f)
    assert reason is not None
    assert "requests" in reason


def test_a_vetted_foreign_name_is_accepted():
    def f() -> None: ...
    f.__module__ = "copy"
    assert gen._classification_failure("copy", f) is None


def test_an_unresolvable_lazy_import_is_accepted_by_name():
    # An optional Sage feature whose wheel is absent (e.g. giac) will not resolve;
    # it is kept by name, not treated as dangerous.
    assert gen._classification_failure("libgiac", _Lazy(None, fail=True)) is None


def test_a_lazy_import_is_classified_by_its_resolved_object():
    dangerous = _Lazy(types.ModuleType("subprocess"))
    reason = gen._classification_failure("sp", dangerous)
    assert reason is not None
    assert "subprocess" in reason


def test_the_vetted_sets_are_the_reviewed_exceptions():
    # A guard against silently widening the exceptions: these are the names a
    # human signed off on. Changing them is a deliberate edit, not a drift.
    assert gen._SAFE_MODULE_NAMES == frozenset({"math", "operator"})
    assert "sleep" in gen._VETTED_FOREIGN and "PariError" in gen._VETTED_FOREIGN
