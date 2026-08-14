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

from sagemath_mcp.security import SECURITY_POLICY, trusted_policy, validate_module

PURE_PYTHON = os.getenv("SAGEMATH_MCP_PURE_PYTHON") == "1"
STARTUP_CODE = os.getenv("SAGEMATH_MCP_STARTUP", "from sage.all import *")


_STARTUP_ERROR: str | None = None


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
    if not PURE_PYTHON and "x" not in ns:
        # Sage's REPL predefines x and callers expect it; importing
        # sage.all does not provide it. Only x -- Sage declares no others,
        # and inventing more would shadow real objects.
        with contextlib.suppress(Exception):
            ns["x"] = ns["SR"].var("x")
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
    "sage.misc.temporary_file",  # creates files outside our control
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
    "Axiom", "ECM", "EmptyNewstyleClass", "EmptyOldstyleClass", "FriCAS", "Gap",
    "Gap3", "Genus2reduction", "Gfan", "Giac", "Gp", "InlineFortran", "Kash",
    "Khoca", "LiE", "Lisp", "Macaulay2", "Magma", "Maple", "Mathematica", "Mathics",
    "Matlab", "Mupad", "Mwrank", "Octave", "PSage", "PackageInfo", "PickleDict",
    "PickleExplainer", "PickleInstance", "PickleObject", "R", "Regina", "Sage",
    "SagePickler", "SageUnpickler", "Sh", "Singular", "TestAppendList",
    "TestAppendNonlist", "TestBuild", "TestBuildSetstate", "TestGlobalFunnyName",
    "TestGlobalNewName", "TestGlobalOldName", "TestReduceGetinitargs",
    "TestReduceNoGetinitargs", "add_attached_file", "atomic_dir", "atomic_write",
    "attach", "attached_files", "axiom", "check_pickle", "compile_and_load",
    "cython", "cython_compile", "cython_import", "cython_import_all",
    "cython_lambda", "db", "db_save", "detach", "dumps", "ecm", "edit",
    "edit_devel", "explain_pickle", "explain_pickle_string", "file_and_line",
    "find_objects_from_name", "fortran", "four_ti_2", "fricas", "frobby", "gap",
    "gap3", "gap3_version", "gap_reset_workspace", "genus2reduction",
    "get_remote_file", "gfan", "giac", "gnuplot", "gp", "gp_version",
    "import_statement_string", "import_statements", "installed_packages",
    "interfaces", "is_loadable_filename", "is_package_installed",
    "is_package_installed_and_updated", "kash", "kash_version", "lie", "lisp",
    "list_packages", "load", "load_attach_mode", "load_attach_path", "load_cython",
    "load_sage_element", "load_sage_object", "load_submodules", "load_wrap",
    "loads", "macaulay2", "magma", "magma_free", "make_None", "maple",
    "mathematica", "mathics", "matlab", "matlab_version", "maxima",
    "modified_file_iterator", "mupad", "mwrank", "name_is_valid", "octave",
    "package_manifest", "package_versions", "picklejar", "pip_installed_packages",
    "pip_remote_version", "pkgname_split", "polymake", "povray", "qepcad",
    "qepcad_formula", "qepcad_version", "r", "r_version", "read_data", "regina",
    "register_unpickle_override", "reload_attached_files_if_modified", "reset",
    "reset_load_attach_path", "runsnake", "sage0", "sage0_version", "sage_eval",
    "sageobj", "sanitize", "save", "scilab", "set_edit_template", "set_editor",
    "sh", "singular", "singular_version", "spkg_type", "spyx_tmp", "tachyon_rt",
    "template_fields", "tmp_dir", "tmp_filename", "trace", "unpickle_all",
    "unpickle_appends", "unpickle_build", "unpickle_extension", "unpickle_global",
    "unpickle_instantiate", "unpickle_newobj", "unpickle_persistent"
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
    try:
        interfaces = importlib.import_module(_EXTERNAL_INTERFACE_EXPORTS)
    except Exception:
        interfaces = None
    if interfaces is not None:
        names.update(n for n in vars(interfaces) if not n.startswith("_"))

    for module_name in _DANGEROUS_SAGE_MODULES:
        try:
            module = importlib.import_module(module_name)
        except Exception:
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
    return frozenset(names)


def _strip_dangerous_sage_names(ns: dict[str, Any]) -> int:
    """Remove Sage helpers that execute, compile, fetch or write.

    Uses the baked-in list: this runs at every worker start, and re-deriving it
    there cost more than the protection was worth.
    """
    removed = 0
    for name in _DANGEROUS_SAGE_NAME_LIST:
        if name in ns:
            del ns[name]
            removed += 1
    return removed


def _strip_forbidden_modules(ns: dict[str, Any]) -> None:
    """Drop module objects the policy forbids from the user namespace.

    `from sage.all import *` binds os, sys and friends as ordinary globals, so
    `m = os` handed caller code the real module. The validator now refuses to
    read those names, and this makes the object unreachable even if it does.
    """
    for name in SECURITY_POLICY.forbidden_attribute_parents:
        ns.pop(name, None)


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
    if PURE_PYTHON:
        return code
    try:
        from sage.repl.preparse import preparse
    except Exception:  # pragma: no cover - no Sage in this interpreter
        return code
    return preparse(code)


def _split_code(code: str, trusted: bool = False) -> SimpleNamespace:
    """Return the executable and tail expression chunks for *code*.

    *trusted* selects the policy for code this server generated itself, which
    needs sage_eval. Caller-supplied code never sets it.
    """

    if not trusted:
        code = _preparse(code)
    # Validate what will actually run: the preparsed source, not what was typed.
    module = ast.parse(code, mode="exec", type_comments=True)
    # NOTE: validate_module enforces our safety policy before compiling. This
    # runs once per request, keeping the execution fast while guarding against
    # disallowed imports/constructs early.
    policy = trusted_policy() if trusted else SECURITY_POLICY
    validate_module(module, code=code, policy=policy)
    ast.fix_missing_locations(module)
    if module.body and isinstance(module.body[-1], ast.Expr):
        prefix = ast.Module(
            body=list(module.body[:-1]),
            type_ignores=list(getattr(module, "type_ignores", [])),
        )
        tail = ast.Expression(body=module.body[-1].value)
        ast.fix_missing_locations(prefix)
        ast.fix_missing_locations(tail)
        return SimpleNamespace(prefix=prefix, tail=tail, is_expr=True)
    return SimpleNamespace(prefix=module, tail=None, is_expr=False)



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
        compiled = _split_code(code, trusted=trusted)
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
        stdout_value = stdout_buffer.getvalue() if stdout_buffer else ""
        result_repr = None if result_obj is None else repr(result_obj)
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
