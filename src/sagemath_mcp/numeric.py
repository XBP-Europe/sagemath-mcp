"""Exact-number guards for tool arguments.

JSON numbers are IEEE doubles in JavaScript-based clients, so an integer past
2^53 or a float standing in for an integer arrives already wrong. These refuse
lossy input rather than compute with it.
"""

from __future__ import annotations

from fastmcp.exceptions import ToolError

# Beyond 2^53 a JSON number is no longer exactly representable as an IEEE
# double, which is what JavaScript-based MCP clients parse numbers into.
# JavaScript's Number.MAX_SAFE_INTEGER. 2^53 itself is NOT safe as an inbound
# value: 2^53 + 1 rounds to exactly 2^53, so a client that meant either sends the
# same digits and the server cannot tell them apart. The boundary has to be the
# largest integer whose neighbours are also representable.
EXACT_JSON_INT_LIMIT = 2**53 - 1


def exact_int(value: int | str | float, name: str) -> int:
    """Coerce a tool argument to an exact integer, refusing lossy input.

    A float here means the value already went through a double. 10^30 arrives
    as 1000000000000000019884624838656, and next_prime() on that returns a
    perfectly plausible wrong answer -- the failure mode is a wrong number, not
    an error, which is why this rejects rather than rounds.
    """
    if isinstance(value, bool):  # bool is an int subclass; never meant here
        raise ToolError(f"'{name}' must be an integer, got a boolean")
    if isinstance(value, str):
        text = value.strip().replace("_", "")
        try:
            return int(text, 10)
        except ValueError:
            raise ToolError(f"'{name}' is not a decimal integer: {value!r}") from None
    if isinstance(value, float):
        if not value.is_integer():
            raise ToolError(f"'{name}' must be a whole number, got {value!r}")
        return reject_if_inexact(int(value), name)
    # An int is not automatically safe. A JavaScript client rounds the value
    # BEFORE serialising and then emits the rounded digits as a JSON integer, so
    # the float branch above is never reached: 10^30 arrives as the int
    # 1000000000000000019884624838656 and looks perfectly ordinary.
    return reject_if_inexact(int(value), name)


def reject_if_inexact(value: int, name: str) -> int:
    """Refuse any JSON-borne number too large to have survived a double."""
    if abs(value) > EXACT_JSON_INT_LIMIT:
        raise ToolError(
            f"'{name}' is larger than 2^53, where JSON numbers stop being exact: "
            "a JavaScript-based client will already have rounded it before sending. "
            f'Pass it as a decimal string instead, for example "{value}".'
        )
    return value


def exact_matrix_entries(rows, name: str):
    """Return *rows* with integer entries kept exact.

    The schemas took `float`, so an exact integer was rounded to a double before
    Sage ever saw it: matrix(SR, [[9007199254740993]]) became
    matrix(SR, [[9007199254740992.0]]) and the determinant was quietly wrong.
    Integers and decimal strings now stay integers; genuine floats stay floats.
    """
    converted = []
    for row in rows:
        if not isinstance(row, (list, tuple)):
            raise ToolError(f"'{name}' must be a list of rows")
        out = []
        for entry in row:
            if isinstance(entry, bool):
                raise ToolError(f"'{name}' entries must be numbers, got a boolean")
            if isinstance(entry, float):
                out.append(entry)          # a float was asked for; keep it
            else:
                out.append(exact_int(entry, name))
        converted.append(out)
    return converted


def check_matrix(rows: list[list[float]], name: str) -> None:
    """Reject shapes Sage would only complain about obscurely, or not at all.

    An empty matrix is the dangerous one: Sage treats [] as the 0x0 matrix and
    reports its determinant as 1.0, which looks like a real answer.
    """
    if not rows or not all(isinstance(row, (list, tuple)) for row in rows):
        raise ToolError(f"'{name}' must be a non-empty list of rows")
    if not rows[0]:
        raise ToolError(f"'{name}' rows must be non-empty")
    width = len(rows[0])
    if any(len(row) != width for row in rows):
        widths = sorted({len(row) for row in rows})
        raise ToolError(
            f"'{name}' rows must all have the same length; found lengths {widths}"
        )
