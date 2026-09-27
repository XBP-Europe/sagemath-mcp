"""Running generated code and reading its structured answer back.

The worker replies with a Python literal; this module evaluates the snippet,
records the same monitoring counters ``evaluate_sage`` does, and rebuilds the
value -- keeping large integers exact and non-finite floats representable.
"""

from __future__ import annotations

import ast
import math

from fastmcp.exceptions import ToolError

from . import monitoring
from .numeric import EXACT_JSON_INT_LIMIT


def _exactify_large_ints(value):
    """Return *value* made safe to travel back as JSON, recursively.

    Two hazards, both of which reached a client as a broken or unparseable
    answer, are neutralised here -- the one place every helper tool's result
    passes through (`evaluate_structured`).

    **Large integers.** A JavaScript-based MCP client parses JSON numbers as
    IEEE doubles: bell(30) = 846749014511809332450147 reached the Claude CLI as
    846749014511809388871680 and was shown as the answer. Nothing errored; the
    number was simply wrong, which is the worst way for this to fail. Above 2^53
    the exact value is therefore sent as a decimal string, mirroring what the
    input side already demands. Smaller integers keep their type.

    **Non-finite floats.** `float('inf')`, `-inf` and `nan` serialise to the
    bare tokens `Infinity`/`-Infinity`/`NaN` (Python's json emits them by
    default), which are not valid JSON -- a strict client's `JSON.parse` rejects
    the whole response, so a `distribution_operation` quantile at p=1 or an
    overflowing determinant would make the tool return nothing parseable at all.
    They are sent as the matching strings instead, so the client gets a value it
    can read. Finite floats are unchanged.
    """
    if isinstance(value, bool):
        return value                      # bool is an int subclass
    if isinstance(value, int):
        return str(value) if abs(value) > EXACT_JSON_INT_LIMIT else value
    if isinstance(value, float) and not math.isfinite(value):
        if math.isnan(value):
            return "NaN"
        return "Infinity" if value > 0 else "-Infinity"
    if isinstance(value, dict):
        return {key: _exactify_large_ints(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_exactify_large_ints(item) for item in value]
    return value


async def evaluate_structured(
    session, code: str, timeout_seconds: float | None = None
) -> object:
    """Run a snippet this server generated.

    trusted=True permits sage_eval, which every helper template is built on.
    That is only safe because the caller-supplied fragments interpolated into
    the template are validated separately by validated_expression before they
    get here -- otherwise the helpers would be an unguarded path straight past
    the AST policy, which is exactly what they were.

    Records the same monitoring counters `evaluate_sage` does. Without this the
    ~30 helper tools -- every specialized call in the catalogue -- ran invisibly
    to the metrics resource, so the counters accounted for `evaluate_sage`
    alone and read as near-idle on a server doing steady helper-tool work.
    Imported lazily to avoid a load-order dependency on session.py's error
    types being importable at module import time.
    """
    from .errors import SageEvaluationError, SageProcessError

    try:
        worker_result = await session.evaluate(
            code,
            want_latex=False,
            capture_stdout=False,
            timeout_seconds=timeout_seconds,
            trusted=True,
        )
    except TimeoutError as exc:
        # Same translation as evaluate_sage: every tool should report a timeout
        # as a tool error with the deadline in it, not a bare TimeoutError.
        monitoring.record_failure(str(exc), is_security=False, details="TimeoutError")
        raise ToolError(str(exc)) from exc
    except SageEvaluationError as exc:
        monitoring.record_failure(
            exc.error_type or str(exc),
            is_security=exc.error_type == "SecurityViolation",
            details=exc.traceback or exc.stdout,
        )
        raise
    except SageProcessError as exc:
        monitoring.record_failure(str(exc) or exc.__class__.__name__, is_security=False)
        raise
    monitoring.record_success(worker_result.elapsed_ms)
    if worker_result.result is None:
        return None
    parsed = _reconstruct_result(worker_result.result)
    if parsed is _UNRECONSTRUCTED:
        return worker_result.result
    return _exactify_large_ints(parsed)


# Sentinel: the worker's result was not a reconstructable literal (a Sage object
# repr, say), so the caller keeps the raw string.
_UNRECONSTRUCTED = object()


def _reconstruct_result(text: str):
    """Rebuild the Python value a worker sent back as a ``repr`` string.

    ``ast.literal_eval`` covers the finite case, but it rejects the bare tokens
    ``inf`` and ``nan`` that ``repr`` emits for non-finite floats -- so a whole
    dict like calculate_expression's ``{'string': ..., 'numeric': -inf}`` failed
    to parse and fell back to being stringified, and the tool returned a garbled
    double-encoded string instead of its fields. This falls back to a bounded
    literal evaluator that additionally permits ``inf``/``nan`` at any depth.
    Non-finite floats then reach ``_exactify_large_ints``, which turns them into
    JSON-safe strings. It evaluates only literals, containers, unary +/- and the
    two float names -- no calls, attributes or other names -- so it runs no code.
    """
    try:
        return ast.literal_eval(text)
    except Exception:
        pass
    try:
        node = ast.parse(text, mode="eval").body
    except SyntaxError:
        return _UNRECONSTRUCTED
    try:
        return _eval_literal_allowing_non_finite(node)
    except (ValueError, TypeError):
        return _UNRECONSTRUCTED


_NON_FINITE_NAMES = {"inf": math.inf, "nan": math.nan}


def _eval_literal_allowing_non_finite(node: ast.AST):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name) and node.id in _NON_FINITE_NAMES:
        return _NON_FINITE_NAMES[node.id]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        operand = _eval_literal_allowing_non_finite(node.operand)
        return -operand if isinstance(node.op, ast.USub) else +operand
    if isinstance(node, ast.Dict):
        return {
            _eval_literal_allowing_non_finite(k): _eval_literal_allowing_non_finite(v)
            for k, v in zip(node.keys, node.values, strict=True)
        }
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_eval_literal_allowing_non_finite(e) for e in node.elts]
    raise ValueError("not a permitted literal node")
