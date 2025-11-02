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

from sagemath_mcp.security import SECURITY_POLICY, validate_module

PURE_PYTHON = os.getenv("SAGEMATH_MCP_PURE_PYTHON") == "1"
STARTUP_CODE = os.getenv("SAGEMATH_MCP_STARTUP", "from sage.all import *")


def _build_namespace() -> dict[str, Any]:
    # NOTE: Each worker keeps its own global namespace. We allow a single
    # preload statement so sessions can bootstrap Sage or the lightweight math
    # shim used during testing. By seeding __builtins__ explicitly we avoid
    # inheriting ambient globals from the worker process.
    ns: dict[str, Any] = {"__builtins__": __builtins__}
    preload = "from math import *" if PURE_PYTHON else STARTUP_CODE
    if preload:
        exec(preload, ns)
    return ns


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


def _split_code(code: str) -> SimpleNamespace:
    """Return the executable and tail expression chunks for *code*."""

    module = ast.parse(code, mode="exec", type_comments=True)
    # NOTE: validate_module enforces our safety policy before compiling. This
    # runs once per request, keeping the execution fast while guarding against
    # disallowed imports/constructs early.
    validate_module(module, code=code, policy=SECURITY_POLICY)
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


def _execute(
    code: str,
    want_latex: bool,
    capture_stdout: bool,
    namespace: dict[str, Any],
) -> dict[str, Any]:
    stdout_buffer = io.StringIO() if capture_stdout else None
    start = time.perf_counter()

    try:
        compiled = _split_code(code)
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
    for raw in sys.stdin:
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
