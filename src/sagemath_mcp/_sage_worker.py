"""Subprocess worker that executes SageMath code with persistent state."""

from __future__ import annotations

import ast
import contextlib
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
    return ns


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


def _restricted_builtins() -> dict[str, Any]:
    """Builtins for user code: everything except the dangerous handful.

    __import__ deliberately stays. Sage imports lazily on first use, so removing
    it breaks ordinary mathematics well after startup. The name is unreachable
    from caller code anyway: the policy blocks dunder references outright.
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


def _split_code(code: str, trusted: bool = False) -> SimpleNamespace:
    """Return the executable and tail expression chunks for *code*.

    *trusted* selects the policy for code this server generated itself, which
    needs sage_eval. Caller-supplied code never sets it.
    """

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
