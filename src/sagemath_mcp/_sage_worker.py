"""Subprocess worker that executes SageMath code with persistent state."""

from __future__ import annotations

import ast
import contextlib
import importlib
import io
import json
import os
import sys
import time
import traceback
from types import SimpleNamespace
from typing import Any

from sagemath_mcp.allowlist import ALLOWED_CALLER_NAMES
from sagemath_mcp.security import (
    _NAME_INJECTING_METHODS,
    SECURITY_POLICY,
    _bound_names,
    check_source_length,
    normalize_caller_code,
    rewrite_permitted_imports,
    trusted_policy,
    validate_module,
)
from sagemath_mcp.symbols import PREDEFINED_SYMBOLS

PURE_PYTHON = os.getenv("SAGEMATH_MCP_PURE_PYTHON") == "1"
STARTUP_CODE = os.getenv("SAGEMATH_MCP_STARTUP", "from sage.all import *")


_STARTUP_ERROR: str | None = None

# Names the caller bound in code that passed validation.
#
# NOT the namespace diff, which is what this used to be. Diffing trusts anything
# the namespace gained, and `lazy_import('os', 'system')` gains a binding to
# os.system without reading a single forbidden name: call one created it, call two
# read it back as "the caller's own", and ran a shell. Recording what validated
# code *statically bound* closes that for every such primitive, including ones
# nobody has found yet -- a name only becomes trusted by appearing as a target in
# code the policy already approved.
_CALLER_BOUND_NAMES: set[str] = set()
# Snapshot of what the namespace held before any caller code ran.
_WITHHELD_NAMES: frozenset[str] = frozenset()


def _build_namespace() -> dict[str, Any]:
    # NOTE: Each worker keeps its own global namespace. We allow a single
    # preload statement so sessions can bootstrap Sage or the lightweight math
    # shim used during testing. By seeding __builtins__ explicitly we avoid
    # inheriting ambient globals from the worker process.
    global _STARTUP_ERROR
    ns: dict[str, Any] = {"__builtins__": __builtins__}
    preload = "from math import *" if PURE_PYTHON else STARTUP_CODE
    if preload:
        try:
            # The preload needs real builtins: importing sage.all uses
            # __import__, open and more. Restrict only afterwards, so user code
            # never sees them.
            exec(preload, ns)
            _STARTUP_ERROR = None
        except Exception as exc:
            _STARTUP_ERROR = f"Startup code failed: {exc}"
            print(
                json.dumps({"ok": False, "startup_error": _STARTUP_ERROR}),
                file=sys.stderr,
            )
    ns["__builtins__"] = _restricted_builtins()
    _strip_forbidden_modules(ns)
    _strip_dangerous_sage_names(ns)
    if not PURE_PYTHON:
        # Sage's REPL predefines x and importing sage.all does not even provide
        # that. The other three are this server's own convention, matching the
        # prelude the specialised tools have always used -- see symbols.py for
        # why exactly these four and no more.
        for symbol in PREDEFINED_SYMBOLS:
            if symbol not in ns:
                with contextlib.suppress(Exception):
                    ns[symbol] = ns["SR"].var(symbol)
    _CALLER_BOUND_NAMES.clear()      # a fresh namespace has no caller names in it
    global _WITHHELD_NAMES
    _WITHHELD_NAMES = _withheld_names(ns)
    return ns


# Sage's namespace is thousands of names deep and includes plenty that execute
# code, run a shell, compile, download or touch arbitrary paths. Listing them one
# by one is a losing game -- `cython(get_remote_file(url))` was reachable, and so
# were `sh`, `fortran` and `loads` -- so entries are removed by where they come
# from. A new helper added to any of these modules is unreachable from the day it
# lands, without anyone remembering to add its name.
_DANGEROUS_SAGE_MODULES = (
    "sage.misc.cython",          # compiles and imports arbitrary code
    "sage.misc.inline_fortran",  # same, for Fortran
    "sage.misc.sh",              # runs a shell
    "sage.misc.remote_file",     # downloads
    "sage.misc.persist",         # pickle load/save: code execution from bytes
    "sage.misc.sage_eval",       # evaluates strings
    "sage.repl.load",            # executes files
    "sage.repl.attach",          # executes files, and keeps doing it
    "sage.misc.attached_files",
    "sage.misc.explain_pickle",
    "sage.misc.edit_module",     # launches an editor
    "sage.misc.trace",           # drops into the debugger
    "sage.misc.dev_tools",
    "sage.misc.package",         # inspects the installation
    "sage.misc.lazy_import",     # binds any module attribute to a name
    "sage.misc.fpickle",         # unpickle_function executes what it is given
    "sage.misc.session",         # load_session unpickles a whole session
    "sage.misc.verbose",         # set_verbose_files writes where it is told
    "sage.misc.temporary_file",  # creates files outside our control
    # Modules whose job is resolving an attribute from a name. Listed wholesale
    # rather than by name because that has now missed three rounds running --
    # Python's `operator`, then `attrcall`, then `raw_getattr`/`getattr_debug` --
    # and because a source scan cannot find them: 807 of the allowlisted names
    # are compiled Cython with no readable source, `attrcall` among them.
    "sage.misc.call",        # attrcall, call_method, AttrCallObject
    "sage.cpython.getattr",  # raw_getattr: getattr without the descriptor protocol
    "sage.cpython.debug",    # getattr_debug: a full getattr equivalent
    # Sage's rich-output subsystem. `show` and `view` were removed by name for
    # writing files and launching viewers; these are the rest of it.
    # `get_display_manager()` hands back an object carrying `switch_backend` and
    # `graphics_from_save`, which takes a caller-supplied callable -- neither
    # exploitable on 10.9, since no backend class is reachable to switch to, but
    # the subsystem has no purpose over MCP, where results are strings and plots
    # are base64 PNGs from the plot tools.
    "sage.repl.rich_output.display_manager",
    "sage.repl.rich_output.pretty_print",
    # `maxima_calculus` is a MaximaLib interface bound in the namespace, and an
    # interface object answers to *every* attribute name: it builds a Maxima
    # call out of whatever you ask for, so `hasattr` is True for `system`,
    # `unlink`, `popen`, `fork` and the rest at once. That is why no name-based
    # attribute rule could have covered it, and why the fix is to stop offering
    # the object. It reached the namespace because `sage.interfaces.all` does
    # not re-export it, so the interface scrub never saw it.
    "sage.interfaces.maxima_lib",
    # `logstr` and `preparser` come from here, and both are REPL plumbing with
    # no mathematical content. Found by the same sweep.
    "sage.repl.interpreter",
    # `Pari`, `PariRing` and `PariGroup` are constructors that funnel a
    # caller-controlled string into the `pari` singleton the bare-name list
    # already removes: `sage.rings.pari_ring` holds a module-level `from
    # sage.libs.pari import pari` and does `self.__x = pari(x)`, so `Pari('
    # system("id")')` ran a shell as the container user even though the name
    # `pari` was gone. `sage.groups.pari_group` does the same. Removing the name
    # is not removing the capability; removing the constructors is. See item 50.
    "sage.rings.pari_ring",       # defines Pari, PariRing
    "sage.groups.pari_group",     # defines PariGroup
    # `libgap` is an in-process GAP interface, and an interface object answers to
    # *every* attribute name -- `libgap.Exec("id")` and
    # `libgap.function_factory("Exec")("id")` both shelled out, because only
    # `libgap.eval` was ever refused. Same shape as `maxima_calculus` above: no
    # name-based attribute rule can cover an object that fabricates attributes on
    # demand, so the object has to go. See item 51.
    "sage.libs.gap.libgap",       # defines Gap, libgap
    # `Dokchitser(...).gp()` returns the `gp` interpreter the interface scrub
    # removes -- GP shells out through `system(...)`. Stripping the constructor
    # stops a caller reconstructing it; the `.gp` method is also refused as a
    # forbidden attribute. See item 53.
    "sage.lfunctions.dokchitser", # defines Dokchitser, reduce_load_dokchitser
)

# Names bound in the namespace that no provenance rule catches, because their
# provenance is not a Sage module at all or is one we otherwise want.
#
# `operator` is the important one. Every attribute rule this server has is
# enforced on the AST -- parent and attribute both read out of the source --
# and `attrgetter` takes its path as a runtime string, so none of it applies:
#
#     operator.attrgetter("misc.persist.unpickle_global")(sage)
#
# returned the real function, which is arbitrary code execution. Sage binds
# `sage` itself along with 21 other module objects, so one string-path
# primitive reaches the whole tree; `getattr`, `setattr` and `vars` were
# already refused, which is what left `operator` as the only way in.
#
# The rest each demonstrated a concrete capability under 10.9: `pari` a shell,
# `oeis` a network request, and the display helpers files written to disk.
_DANGEROUS_BARE_NAMES = (
    # `pari` belongs here rather than in the provenance list above, and the
    # distinction is not cosmetic: `pari('system("id")')` runs a shell, but
    # listing `sage.libs.pari.all` removed nothing at all. That derivation takes
    # only names *defined* in a module -- it has to, since `sage.misc.persist`
    # also has `Integer` in scope -- and `pari`, `pari_gen` and `PariError` are
    # every one of them defined in `cypari2`. An integration test now fails on
    # any provenance entry that matches nothing, because an entry that looks
    # like protection and is not is worse than no entry.
    "pari",         # pari('system("id")') ran a shell command as the container user
    "warnings",     # a module object, and a module object has __builtins__
    "oeis",         # queries oeis.org: egress from a sandbox with no network need
    "install_doc",  # writes documentation to a caller-chosen path
    "show",         # renders to a file and tries to launch a viewer
    "view",         # same
    "animate",      # writes an animation file
    "html",         # renders to disk
    # `latex` and `operator` were here and are not any more. Both were removed
    # for something they carry rather than something they are, and in both cases
    # the thing they carry is refused by name in its own right:
    #
    #   latex.eval()          runs the toolchain -- and `eval` is a forbidden
    #                         attribute, so `latex.eval(...)` is still blocked.
    #   operator.attrgetter   is attribute access the AST cannot see -- and
    #                         `attrgetter`, `methodcaller` and `itemgetter` are
    #                         forbidden names in every position.
    #
    # What the removal cost, measured against SageMath's own doctests: `latex`
    # was the single most-refused name in the corpus at 1,387 uses, while
    # `(x^2+1)._latex_()` was allowed and returns the identical string -- the
    # policy blocked the idiom and shipped the result. `operator.le` is how a
    # poset is built, 206 times. See REVIEW_ACTIONS.md item 46.
    "search_src",   # reads the installation
    "search_doc",
    "reference",
    "Profiler",
)

# Sage's interfaces to other computer algebra systems. Each one spawns the real
# program, and those programs have their own shell escapes:
#     gp('system("id")')      wrote a file as the container user
#     maxima('system("id")')  did the same
# sage.interfaces.all is Sage's own list of them, so everything it exports is
# removed -- including whatever a future release adds, which a hand-written list
# of names would miss.
_EXTERNAL_INTERFACE_EXPORTS = "sage.interfaces.all"


# The names those modules and sage.interfaces.all actually define, baked in.
#
# Deriving this at startup meant importing sixteen modules in every worker, and
# on slower CI hardware that pushed the first evaluation past its timeout -- a
# hardening step is not allowed to cost the thing it protects. The derivation
# still exists below and a test re-runs it against the installed Sage, so a
# version that adds or renames a helper fails the suite rather than the user.
_DANGEROUS_SAGE_NAME_LIST: frozenset[str] = frozenset({
    "AttrCallObject", "AttributeErrorMessage", "Axiom", "DisplayException", "DisplayManager",
    "Dokchitser", "ECM", "EmptyNewstyleClass", "EmptyOldstyleClass", "FriCAS", "Gap", "Gap3",
    "Genus2reduction", "Gfan", "Giac", "Gp", "InlineFortran", "InterfaceShellTransformer",
    "Kash", "Khoca", "LazyImport", "LiE", "Lisp", "Macaulay2", "Magma", "Maple", "Mathematica",
    "Mathics", "Matlab", "MaximaLib", "MaximaLibElement", "MaximaLibElementFunction", "Mupad",
    "Mwrank", "Octave", "OutputTypeException", "PSage", "PackageInfo", "Pari", "PariGroup",
    "PariRing", "PickleDict", "PickleExplainer", "PickleInstance", "PickleObject", "R",
    "Regina", "RichReprWarning", "Sage", "SageCrashHandler", "SageNotebookInteractiveShell",
    "SagePickler", "SagePreparseTransformer", "SageShellOverride", "SageTerminalApp",
    "SageTerminalInteractiveShell", "SageTestShell", "SageUnpickler", "SequencePrettyPrinter",
    "Sh", "Singular", "TestAppendList", "TestAppendNonlist", "TestBuild", "TestBuildSetstate",
    "TestGlobalFunnyName", "TestGlobalNewName", "TestGlobalOldName", "TestReduceGetinitargs",
    "TestReduceNoGetinitargs", "add_attached_file", "atomic_dir", "atomic_write", "attach",
    "attached_files", "attrcall", "attributes", "axiom", "call_method", "call_pickled_function",
    "check_pickle", "clean_namespace", "code_ctor", "compile_and_load", "cython",
    "cython_compile", "cython_import", "cython_import_all", "cython_lambda", "db", "db_save",
    "detach", "dir_with_other_class", "dummy_integrate", "dumps", "ecm", "edit", "edit_devel",
    "ensure_startup_finished", "explain_pickle", "explain_pickle_string", "file_and_line",
    "find_objects_from_name", "finish_startup", "fortran", "four_ti_2", "fricas", "frobby",
    "gap", "gap3", "gap3_version", "gap_reset_workspace", "genus2reduction",
    "get_display_manager", "get_remote_file", "get_star_imports", "get_test_shell",
    "get_verbose", "get_verbose_files", "getattr_debug", "getattr_from_other_class", "gfan",
    "giac", "gnuplot", "gp", "gp_version", "import_statement_string", "import_statements",
    "init", "installed_packages", "interface_shell_embed", "interfaces", "is_during_startup",
    "is_loadable_filename", "is_package_installed", "is_package_installed_and_updated", "kash",
    "kash_version", "lazy_import", "libgap", "lie", "lisp", "list_packages", "load",
    "load_attach_mode", "load_attach_path", "load_cython", "load_sage_element",
    "load_sage_object", "load_session", "load_submodules", "load_wrap", "loads", "logstr",
    "macaulay2", "magma", "magma_free", "make_None", "maple", "mathematica", "mathics",
    "matlab", "matlab_version", "max_at_to_sage", "max_harmonic_to_sage",
    "max_pochhammer_to_sage", "max_to_sr", "max_to_string", "maxima", "maxima_calculus",
    "maxima_lib", "mdiff_to_sage", "mlist_to_sage", "modified_file_iterator", "mqapply_to_sage",
    "mrat_to_sage", "mupad", "mwrank", "name_is_valid", "octave", "package_manifest",
    "package_versions", "parse_max_string", "pickleMethod", "pickleModule", "pickle_function",
    "picklejar", "pip_installed_packages", "pip_remote_version", "pkgname_split", "polymake",
    "povray", "preparser", "pretty_print", "pyobject_to_max", "qepcad", "qepcad_formula",
    "qepcad_version", "r", "r_version", "raw_getattr", "read_data", "reduce_code",
    "reduce_load_MaximaLib", "reduce_load_dokchitser", "regina", "register_unpickle_override",
    "reload_attached_files_if_modified", "reset", "reset_load_attach_path", "restricted_output",
    "runsnake", "sage0", "sage0_version", "sage_eval", "sage_rat", "sageobj", "sanitize",
    "save", "save_cache_file", "save_session", "scilab", "set_edit_template", "set_editor",
    "set_verbose", "set_verbose_files", "sh", "shortrepr", "show", "show_identifiers",
    "singular", "singular_version", "spkg_type", "spyx_tmp", "sr_to_max", "stdout_to_string",
    "tachyon_rt", "template_fields", "test_fake_startup", "test_max_equal", "test_max_notequal",
    "test_max_relation", "tmp_dir", "tmp_filename", "trace", "type_debug", "unpickleMethod",
    "unpickleModule", "unpickle_all", "unpickle_appends", "unpickle_build",
    "unpickle_extension", "unpickle_function", "unpickle_global", "unpickle_instantiate",
    "unpickle_newobj", "unpickle_persistent", "unset_verbose_files", "verbose",
})


def _dangerous_sage_names() -> frozenset[str]:
    """Names defined by the dangerous modules, resolved from those modules only.

    The first version of this walked the whole namespace reading ``__module__``
    off every entry. That is how you find them, but Sage's namespace is built
    from lazy imports and reading an attribute resolves one: worker startup went
    from instant to 1.8 seconds, and the delay landed inside the caller's first
    evaluation. Importing fifteen small modules and asking what each defines
    costs nothing and touches nothing else.
    """
    names: set[str] = set()
    # Several of these cannot be imported on their own -- `sage.interfaces.
    # maxima_lib` raises `module 'sage' has no attribute 'functions'` unless the
    # library is already up. The loop below swallows an ImportError and moves on,
    # which is how `maxima_calculus` stayed reachable after its module was
    # listed: the entry looked like protection and contributed nothing. Loading
    # sage.all first costs a second here and this function runs offline, in the
    # generator and the drift test, never at worker startup.
    sage_all = None
    with contextlib.suppress(Exception):
        sage_all = importlib.import_module("sage.all")

    failed: list[str] = []
    try:
        interfaces = importlib.import_module(_EXTERNAL_INTERFACE_EXPORTS)
    except Exception:
        interfaces = None
        failed.append(_EXTERNAL_INTERFACE_EXPORTS)
    if interfaces is not None:
        names.update(n for n in vars(interfaces) if not n.startswith("_"))

    for module_name in _DANGEROUS_SAGE_MODULES:
        try:
            module = importlib.import_module(module_name)
        except Exception:
            failed.append(module_name)
            continue
        for name, value in vars(module).items():
            if name.startswith("_"):
                continue
            # Defined here, not merely imported here: sage.misc.persist also has
            # Integer and ZZ in scope, and removing those would break the maths
            # this server exists to do.
            home = getattr(value, "__module__", None)
            if isinstance(home, str) and (
                home == module_name or home.startswith(module_name + ".")
            ):
                names.add(name)

    # Second pass, over the namespace itself, because the first pass can only
    # see a name where it is *defined*. Two shapes escape it:
    #
    #   sage/calculus/all.py:  from .calculus import maxima as maxima_calculus
    #   sage/all.py:           lazy_import('sage.x', 'y')
    #
    # An alias is defined nowhere, and a LazyImport reports
    # `sage.misc.lazy_import` as its type's module -- so every provenance check
    # in this file classifies it as harmless and moves on. `maxima_calculus` is
    # what that cost: a live MaximaLib interface, offered to callers, answering
    # to `system`, `unlink`, `popen` and every other attribute an interface
    # object fabricates on demand.
    #
    # Resolving the namespace is the 1.8-second cost this function exists to
    # keep out of worker startup, and it is free here: this runs in the
    # generator and the drift test, never at start.
    for name, value in list(vars(sage_all).items()) if sage_all else []:
        if name.startswith("_") or name in names:
            continue
        try:
            resolved = value._get_object() if type(value).__name__ == "LazyImport" else value
            home = getattr(resolved, "__module__", None)
        except Exception:
            continue
        if isinstance(home, str) and any(
            home == module or home.startswith(module + ".")
            for module in (*_DANGEROUS_SAGE_MODULES, _EXTERNAL_INTERFACE_EXPORTS)
        ):
            names.add(name)

    if failed:
        # Not raised: the drift test needs a value to compare. Reported, because
        # a module that cannot be imported protects nothing, and silence here is
        # what let that happen once already.
        print(
            f"could not import for denylist derivation: {', '.join(failed)}",
            file=sys.stderr,
        )
    return frozenset(names)


def _strip_dangerous_sage_names(ns: dict[str, Any]) -> int:
    """Remove Sage helpers that execute, compile, fetch or write.

    Uses the baked-in list: this runs at every worker start, and re-deriving it
    there cost more than the protection was worth.
    """
    removed = 0
    for name in (*_DANGEROUS_SAGE_NAME_LIST, *_DANGEROUS_BARE_NAMES):
        if name in ns:
            del ns[name]
            removed += 1
    # And from `sage.all`, which is where sage_eval looks. See
    # _strip_from_sage_all: without this the whole denylist is decorative on
    # every path that goes through a generated template.
    if not PURE_PYTHON:
        with contextlib.suppress(Exception):
            _strip_from_sage_all((*_DANGEROUS_SAGE_NAME_LIST, *_DANGEROUS_BARE_NAMES))
    return removed


def _reseal_namespace(ns: dict[str, Any], introduced: frozenset[str] = frozenset()) -> None:
    """Re-apply the startup scrub, and re-take the withheld snapshot.

    The generated prelude runs `from sage.all import *` in this same persistent
    namespace, which puts back every name the startup scrub removed. That was
    remote code execution: `unpickle_global` is guarded by the scrub alone --
    unlike `cython` or `pari`, which the AST rules refuse by name -- so after
    any specialised tool call it was reachable again by a caller who had bound
    the name in dead code.

    Sealing at startup is therefore not enough; the namespace has to be resealed
    whenever something has run that could have repopulated it. Caller-created
    names are left alone: they are the point of a stateful session, and they
    cannot reintroduce a scrubbed helper, because caller code cannot import.
    """
    _strip_forbidden_modules(ns)
    _strip_dangerous_sage_names(ns)
    # A name trusted code introduced is not the caller's, whatever they bound
    # earlier. Without this a caller can reserve the templates' internals in
    # dead code -- `if False: _fig = 1` -- and collect the objects a later tool
    # call builds under them. Diffing the namespace is sound used this way: to
    # distrust what appeared, never to trust it.
    _CALLER_BOUND_NAMES.difference_update(introduced)
    global _WITHHELD_NAMES
    _WITHHELD_NAMES = frozenset(
        name for name in ns
        if name not in ALLOWED_CALLER_NAMES and name not in _CALLER_BOUND_NAMES
    )


def _strip_from_sage_all(names: Any) -> int:
    """Remove names from `sage.all` itself, not only from the worker namespace.

    The scrub protects caller code, which runs `exec` against the worker
    namespace. It does *not* protect a tool's fragment, because every generated
    template is built on `sage_eval` -- and `sage_eval` resolves against
    `sage.all`'s own globals, never consulting the namespace it was handed. So
    with the namespace scrubbed clean, this still returned the real function:

        sage_eval('unpickle_global')   -> cython_function_or_method

    and the same for `cython`, `sh`, `attrcall`, `os` and `maxima_calculus`.
    Every name the denylist removes was reachable that way. Nothing was
    *exploitable*: a caller string reaching a template must first pass
    `_validated_expression`, which enforces the allowlist. But that made the
    gate the only lock on that path rather than the second, and this file's
    whole model is that the object should not be there either.

    Process-local and deliberate: this worker exists to run untrusted
    mathematics, so its own copy of `sage.all` has no business holding a shell.
    """
    import sage.all

    removed = 0
    for name in names:
        if name in _TRUSTED_TEMPLATE_IMPORTS:
            continue
        if name in sage.all.__dict__:
            del sage.all.__dict__[name]
            removed += 1
    return removed


# What generated code imports from `sage.all` by name, and must keep finding
# there. `sage_eval` is on the denylist -- it comes from `sage.misc.sage_eval`,
# which the scrub removes wholesale -- and every template is built on it, so
# stripping it from the module broke all 31 Sage-backed tools at once. The
# templates import it explicitly under the trusted policy; callers cannot,
# because `sage_eval` is a forbidden call name for them and no import of theirs
# survives validation.
_TRUSTED_TEMPLATE_IMPORTS = frozenset({"sage_eval", "preparse", "sage_input", "latex"})


def _strip_forbidden_modules(ns: dict[str, Any]) -> None:
    """Drop module objects the policy forbids from the user namespace.

    `from sage.all import *` binds os, sys and friends as ordinary globals, so
    `m = os` handed caller code the real module. The validator now refuses to
    read those names, and this makes the object unreachable even if it does.

    One module survives, and only in pieces. `operator` stays a forbidden parent
    -- `m = operator` is refused, and so is every attribute of it -- except for
    the arithmetic and comparison functions named in
    `SecurityPolicy.allowed_module_attributes`, which the validator lets through
    one at a time. Keeping the object in the namespace is what makes those
    spellings resolve; keeping the module forbidden is what makes everything
    else about it, including anything a future Python adds, refused by default.
    """
    permitted = {module for module, _ in SECURITY_POLICY.allowed_module_attributes}
    forbidden = [
        name for name in SECURITY_POLICY.forbidden_attribute_parents
        if name not in permitted
    ]
    for name in forbidden:
        ns.pop(name, None)
    if not PURE_PYTHON:
        with contextlib.suppress(Exception):
            _strip_from_sage_all(forbidden)


# Builtins that are dangerous in this context and have no place in a maths
# expression. The AST policy blocks these names too; removing them from the
# namespace is the backstop for when it misses a spelling -- as it did for
# `f = open`, which the validator only caught in call position.
_DENIED_BUILTINS = frozenset(
    {
        "open",
        "eval",
        "exec",
        "compile",
        "input",
        "breakpoint",
        "globals",
        "locals",
        "vars",
        "memoryview",
        "help",
        "exit",
        "quit",
    }
)

# __import__ is NOT in that list, and removing it was tried and reverted.
# Item 18 escalated through it, so denying it looks right -- but Sage needs it
# from this namespace: with it removed, Singular's polynomial string formatting
# raises KeyError('__import__') from inside sage.libs.singular, and that is
# Cython internals rather than anything the caller wrote. The defence against
# item 18 is therefore the validation gate on every string that reaches a
# trusted template, not the namespace backstop, which cannot cover this name.


def _restricted_builtins() -> dict[str, Any]:
    """Builtins for user code: everything except the dangerous handful.

    The AST policy blocks these names too; removing them from the namespace is
    what still holds when the policy cannot see the code at all -- which is the
    case for any string handed to sage_eval at runtime.
    """
    source = __builtins__ if isinstance(__builtins__, dict) else vars(__builtins__)
    return {name: value for name, value in source.items() if name not in _DENIED_BUILTINS}


def _format_result(value: Any) -> str:
    """Render a result the way the Sage REPL renders it.

    `repr` stacks a sequence of matrices one after another; Sage lays them out
    side by side, in columns, and that is what its own doctests record:

        (
        [1 0]  [0 1]  [0 0]  [0 0]
        [0 0], [0 0], [1 0], [0 1]
        )

    The difference is not cosmetic for a server whose entire output is text --
    a basis of eight 3x3 matrices is 32 lines one way and 4 the other. It was
    found by executing SageMath's doctests rather than by reading them, and it
    was the only class of disagreement left in that suite.

    Sage's own `format_list` does it, so nothing here reimplements the layout:
    it returns the tall form when the entries are tall and plain `repr`
    otherwise, so `[1, 2, 3]` is untouched. The formatter lives in
    `sage.repl.display`, which callers do not get -- this is the worker
    importing it internally, as it already does for `latex` when a tool asks
    for LaTeX.
    """
    if not PURE_PYTHON and isinstance(value, (list, tuple)) and value:
        try:
            if _wants_tall_layout(value):
                from sage.repl.display.util import format_list

                return format_list(value)
        except Exception:
            pass
    return repr(value)


def _wants_tall_layout(sequence: Any) -> bool:
    """Sage's own condition for laying a sequence out in columns.

    Not every multi-line repr gets the treatment, and guessing which do was
    wrong twice: a list of morphisms has a multi-line repr and Sage prints it
    stacked, while a list of matrices gets columns. The rule is in
    `sage.repl.display.fancy_repr.TallListRepr` and it is an opt-in -- an
    element, or the parent it comes from, has to say it is ascii art:

        o._repr_option('ascii_art')            # the element says so
        o.parent()._repr_option('element_ascii_art')   # its parent does

    MatrixSpace sets the second; morphisms set neither. Reading that rather
    than approximating it is the difference between matching SageMath's
    doctests and inventing a third layout.
    """
    for element in sequence:
        for probe in (
            lambda o: o._repr_option("ascii_art"),
            lambda o: o.parent()._repr_option("element_ascii_art"),
        ):
            try:
                if probe(element):
                    return True
            except (AttributeError, TypeError):
                continue
    return False


def _latex(result: Any) -> str | None:
    if result is None:
        return None
    try:
        if PURE_PYTHON:
            # Optional sympy support for nicer formatting during tests/dev.
            from sympy import latex as sympy_latex  # type: ignore

            return sympy_latex(result)  # pragma: no cover - requires sympy
        from sage.all import latex as sage_latex  # type: ignore

        return sage_latex(result)
    except Exception:  # pragma: no cover - best effort only
        return None


def _preparse(code: str) -> str:
    """Turn caller code into the Python that Sage's own REPL would run.

    Without this the tool advertised "SageMath code" and executed plain Python:
    `2^3` was 1 rather than 8, `K.<a> = NumberField(...)` was a syntax error, and
    integer literals were machine ints rather than Sage Integers. The specialised
    tools have always preparsed, via sage_eval, so the two paths disagreed about
    the language they accepted.

    Caller code only. Server-generated templates are already plain Python -- a
    lint keeps `^` out of them -- and preparsing them would change their meaning.
    """
    code = normalize_caller_code(code)
    if PURE_PYTHON:
        return code
    try:
        from sage.repl.preparse import preparse
    except Exception:  # pragma: no cover - no Sage in this interpreter
        return code
    return preparse(code)


def _withheld_names(ns: dict[str, Any]) -> frozenset[str]:
    """Names present at startup that callers are not offered.

    Under the default startup this is only dunders, because the allowlist is
    generated from exactly this namespace. It stops being only dunders the
    moment anything else puts a name here -- a custom `SAGEMATH_MCP_STARTUP`,
    or a Sage upgrade landing before the allowlist is regenerated -- and those
    names must stay unreachable rather than becoming reachable to any caller who
    happens to assign to them.

    Taken once, before any caller code runs. Recomputing it per call would sweep
    up the caller's own variables: they live in this same namespace, so `total`
    would be withheld on the call after the one that created it.
    """
    return frozenset(n for n in ns if n not in ALLOWED_CALLER_NAMES)


def _split_code(
    code: str, trusted: bool = False,
    session_names: frozenset[str] | set[str] = frozenset(),
    withheld: frozenset[str] = frozenset(),
) -> SimpleNamespace:
    """Return the executable and tail expression chunks for *code*.

    *trusted* selects the policy for code this server generated itself, which
    needs sage_eval. Caller-supplied code never sets it.
    """

    if not trusted:
        # The caller's own length first, so the number in the message is the one
        # they can measure.
        check_source_length(code)
        code = _preparse(code)
    # Validate what will actually run: the preparsed source, not what was typed.
    # Before parsing, not after: the parser gives up on a long enough snippet
    # and reports a RecursionError, which tells the caller nothing they can act
    # on and leaves the length limit decorative.
    # And again on what will actually be parsed: the preparser can expand a
    # snippet under the limit into one far over it, and the parser gives up with
    # a RecursionError that tells the caller nothing.
    check_source_length(code, after_preparse=not trusted)
    module = ast.parse(code, mode="exec", type_comments=True)
    # NOTE: validate_module enforces our safety policy before compiling. This
    # runs once per request, keeping the execution fast while guarding against
    # disallowed imports/constructs early.
    policy = trusted_policy() if trusted else SECURITY_POLICY
    if not trusted:
        # Drop the imports that would change nothing -- an unused reflex line, a
        # name the namespace already holds -- *before* validating, so that what
        # is checked is still exactly what runs. The rewrite only removes
        # imports and binds names already offered, so it can never widen what
        # the validator then sees.
        module = rewrite_permitted_imports(
            module, offered=ALLOWED_CALLER_NAMES, policy=policy
        )
    validate_module(
        module, code=code, policy=policy,
        extra_allowed_names=session_names, withheld_names=withheld,
    )
    bound_here: frozenset[str] = frozenset()
    if trusted:
        # Every name generated code binds belongs to it, whether the binding
        # creates the name or replaces one the caller had. Read statically,
        # because a namespace diff sees only the first kind.
        bound_here = frozenset(_bound_names(module))
    else:
        # Approved, so what it binds is readable on later calls in this session
        # -- except a name that is already live and not offered, which the
        # caller is shadowing rather than creating.
        _CALLER_BOUND_NAMES.update(_bound_names(module) - withheld)
    # `A.inject_variables()` creates names while the snippet runs. The validator
    # lets the snippet read them; this tells _execute to find out what they were,
    # so the *next* call can read them too -- which is what makes a session a
    # session rather than a sequence of snippets.
    injects = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _NAME_INJECTING_METHODS
        for node in ast.walk(module)
    )
    ast.fix_missing_locations(module)
    # `bound_here` rides along so _execute can hand it to the reseal.
    if module.body and isinstance(module.body[-1], ast.Expr):
        prefix = ast.Module(
            body=list(module.body[:-1]),
            type_ignores=list(getattr(module, "type_ignores", [])),
        )
        tail = ast.Expression(body=module.body[-1].value)
        ast.fix_missing_locations(prefix)
        ast.fix_missing_locations(tail)
        return SimpleNamespace(bound_here=bound_here, prefix=prefix, tail=tail,
                               is_expr=True, injects=injects)
    return SimpleNamespace(bound_here=bound_here, prefix=module, tail=None,
                           is_expr=False, injects=injects)



class _StreamingStdout(io.StringIO):
    """Captures stdout while emitting each completed line as it is produced.

    The worker answers one JSON response per request, so a caller previously saw
    nothing until the computation finished -- the streaming tool split the output
    only after awaiting the whole evaluation. Emitting line events on the same
    channel lets the parent forward progress while the computation is still
    running.
    """

    def __init__(self, msg_id: str, sink) -> None:
        super().__init__()
        self._msg_id = msg_id
        self._sink = sink          # the real stdout, captured before redirection
        self._pending = ""

    def write(self, text: str) -> int:  # type: ignore[override]
        written = super().write(text)   # keep the full text for the final response
        self._pending += text
        while "\n" in self._pending:
            line, self._pending = self._pending.split("\n", 1)
            self._emit(line)
        return written

    def flush(self) -> None:  # type: ignore[override]
        if self._pending:
            self._emit(self._pending)
            self._pending = ""

    def _emit(self, line: str) -> None:
        print(
            json.dumps({"type": "stdout", "id": self._msg_id, "text": line}),
            file=self._sink,
            flush=True,
        )


def _execute(
    code: str,
    want_latex: bool,
    capture_stdout: bool,
    namespace: dict[str, Any],
    trusted: bool = False,
    stream_id: str | None = None,
) -> dict[str, Any]:
    if _STARTUP_ERROR:
        return {
            "ok": False,
            "stdout": "",
            "error": {
                "type": "StartupError",
                "message": _STARTUP_ERROR,
                "traceback": "",
            },
        }
    # stream_id turns the buffer into one that also emits line events.
    if capture_stdout and stream_id is not None:
        stdout_buffer: io.StringIO | None = _StreamingStdout(stream_id, sys.stdout)
    elif capture_stdout:
        stdout_buffer = io.StringIO()
    else:
        stdout_buffer = None
    start = time.perf_counter()

    try:
        compiled = _split_code(
            code, trusted=trusted, session_names=_CALLER_BOUND_NAMES,
            withheld=_WITHHELD_NAMES,
        )
    except Exception as exc:
        return {
            "ok": False,
            "stdout": stdout_buffer.getvalue() if stdout_buffer else "",
            "error": {
                "type": exc.__class__.__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(),
            },
        }

    before_trusted = frozenset(namespace) if trusted else frozenset()
    before_execution = set(namespace) if compiled.injects and not trusted else set()
    try:
        with contextlib.redirect_stdout(stdout_buffer or io.StringIO()):
            exec(compile(compiled.prefix, "<sagecell>", "exec"), namespace)
            if isinstance(stdout_buffer, _StreamingStdout):
                stdout_buffer.flush()   # emit a trailing line with no newline
            result_obj = None
            result_type = "statement"
            if compiled.is_expr and compiled.tail is not None:
                result_obj = eval(compile(compiled.tail, "<sagecell>", "eval"), namespace)
                result_type = "expression"
        if compiled.injects and not trusted:
            # Only for a snippet that *asked* for an injection, and only for
            # names that were not there before it ran. A namespace diff is not
            # trusted in general -- `lazy_import('os', 'system')` gains a
            # binding without reading a forbidden name, which is why
            # _CALLER_BOUND_NAMES is built from the AST -- so this is gated on
            # the caller having written the call, and `lazy_import` itself is
            # scrubbed from the namespace and refused by name.
            _CALLER_BOUND_NAMES.update(set(namespace) - before_execution)
        stdout_value = stdout_buffer.getvalue() if stdout_buffer else ""
        if result_obj is not None and not trusted:
            # `_` is the previous result, as in every REPL Sage ships. It was
            # refused 694 times across SageMath's own doctests -- `_.parent()`,
            # `_.simplify()` -- and never for a security reason: this worker
            # simply never bound it. A session that keeps variables between
            # calls can keep this one. Caller code only: a tool's generated
            # snippet must not move it, or `_` would mean whichever helper the
            # model happened to call in between.
            namespace["_"] = result_obj
            _CALLER_BOUND_NAMES.add("_")
        result_repr = None if result_obj is None else _format_result(result_obj)
        latex_repr = _latex(result_obj) if result_obj is not None and want_latex else None
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        return {
            "ok": True,
            "result_type": result_type,
            "result": result_repr,
            "latex": latex_repr,
            "stdout": stdout_value,
            "elapsed_ms": elapsed_ms,
        }
    except KeyboardInterrupt:
        # SIGINT from the parent means "abandon this computation", not "die".
        # KeyboardInterrupt is a BaseException, so the handler below does not
        # catch it; without this the worker would exit and take the namespace
        # with it, which is exactly what interrupting is meant to avoid.
        return {
            "ok": False,
            "stdout": stdout_buffer.getvalue() if stdout_buffer else "",
            "error": {
                "type": "Interrupted",
                "message": "Computation interrupted; session state is preserved.",
                "traceback": "",
            },
        }
    except Exception as exc:  # pragma: no cover - error path
        stdout_value = stdout_buffer.getvalue() if stdout_buffer else ""
        return {
            "ok": False,
            "stdout": stdout_value,
            "error": {
                "type": exc.__class__.__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(),
            },
        }


    finally:
        if trusted:
            # The prelude runs `from sage.all import *` in this namespace and
            # runs *first*, so a tool call that raises has already repopulated
            # it by the time it fails. Sealing only on the success path left
            # every failing call -- a singular matrix, a bad bound, an
            # interrupted computation -- holding the door open, and that was
            # remote code execution. KeyboardInterrupt is a BaseException, so
            # this has to be `finally` rather than a cleanup in `except`.
            # Two sources, because neither is complete on its own: the AST
            # catches an overwrite of a name the caller already had, and the
            # key diff catches what `from sage.all import *` brings in, which
            # no AST walk enumerates.
            _reseal_namespace(
                namespace,
                (frozenset(namespace) - before_trusted) | compiled.bound_here,
            )

def _main() -> int:
    namespace = _build_namespace()
    while True:
        try:
            raw = sys.stdin.readline()
        except KeyboardInterrupt:
            # An interrupt that lands while the worker is idle has nothing to
            # cancel. Swallow it and keep serving rather than exiting.
            continue
        if not raw:
            break
        raw = raw.strip()
        if not raw:
            continue
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": {
                            "type": "JSONDecodeError",
                            "message": "Invalid JSON payload",
                        },
                    }
                ),
                flush=True,
            )
            continue
        msg_type = message.get("type")
        msg_id = message.get("id")

        if msg_type == "execute":
            response = _execute(
                code=message["code"],
                want_latex=bool(message.get("want_latex", False)),
                capture_stdout=bool(message.get("capture_stdout", True)),
                namespace=namespace,
                trusted=bool(message.get("trusted", False)),
                stream_id=msg_id if message.get("stream") else None,
            )
            response["id"] = msg_id
            print(json.dumps(response), flush=True)
        elif msg_type == "reset":
            namespace = _build_namespace()
            print(json.dumps({"ok": True, "id": msg_id}), flush=True)
        elif msg_type == "shutdown":
            print(json.dumps({"ok": True, "id": msg_id}), flush=True)
            return 0
        else:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "id": msg_id,
                        "error": {
                            "type": "ValueError",
                            "message": f"Unsupported message type: {msg_type}",
                        },
                    }
                ),
                flush=True,
            )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    sys.exit(_main())
