"""Fuzz the gates that decide what reaches a generated Sage template.

`fuzz_validate.py` covers `evaluate_sage`'s path. This covers the other one,
and it is the one with the higher consequence: generated templates run under
`trusted_policy()`, which **permits `sage_eval`**, so a caller string that
reaches a template unscreened is arbitrary execution. A structural test
already enforces that every interpolated string passes one of the three gates.
Nothing tested what those gates *accept*.

Two of the three return a value that is then interpolated **verbatim**:

    tools/discrete.py:  f"_G = {_validated_expression(group)}\\n"
    tools/algebra.py:   f"_R = PolynomialRing({_validated_expression(base)}, '{vars}')\\n"

So the gate's contract is not only "the fragment is safe to evaluate". It is
also "the returned text cannot change the shape of the line it lands in" --
a newline would add a statement (item 56), and an unbalanced bracket in a call
argument would close the call and append something else.

That second half is where the soft spot is, and `_validated_expression` says
so itself: a fragment that will not parse is screened at **token** level and
returned, because the documented equation form `x^2 - 1 = 0` is deliberately
not a Python expression. A token screen sees names, not structure.

So the oracles here are structural:

1. Only `ToolError` escapes. Any other exception is a gate that is not being
   applied, and the tools turn it into a 500 rather than a refusal.
2. The returned text contains no newline.
3. Interpolating it into the two real template shapes does not change the
   statement count, and adds no call the fragment did not itself contain.
4. The gate is idempotent: re-gating its own output returns the same text. A
   gate whose output it would itself reject is one normalisation away from
   disagreeing with what actually runs.

Run it:

    uv run python fuzz/fuzz_codegen.py --iterations 200000
"""

from __future__ import annotations

import argparse
import ast
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastmcp.exceptions import ToolError

from sagemath_mcp.codegen import _validated_expression
from sagemath_mcp.security import SECURITY_POLICY

JUDGED = 0

#: Names that must never survive a gate into a template.
DENIED: tuple[str, ...] = tuple(sorted(SECURITY_POLICY.forbidden_call_names))

#: Fragment shapes. The Sage-only spellings matter most: they do not parse as
#: Python, so they take the token-screen path that has no tree to inspect.
_SHAPES = (
    "{n}", "{n}(1)", "{n}.attr", "[{n}..1]", "{n}^2", "x^2 - 1 = 0",
    "matrix([[1,2],[3,4]])", "QQ", "{n} or 1", "(1, {n})", "[{n} for i in [1]]",
    "1 if {n} else 2", "{{'k': {n}}}", "f'{{{n}}}'", "{n} if 1 else {n}",
    # Shapes aimed at the interpolation site rather than the evaluator: an
    # argument list that closes early, a statement separator, a comment that
    # swallows the rest of the generated line.
    "QQ), {n}(", "QQ); {n}(1); (", "QQ) #", "QQ, 'x'), {n}(", "QQ\\n{n}(1)",
    "1) if 1 else (2", "QQ]", "QQ}}", "1 + (2",
    # Balanced injections, which the bracket check cannot refuse: these add an
    # argument and a call to the template's own call without breaking the
    # parse. They are allowed -- the call comes from the fragment, and every
    # name in it is screened -- so they exist here to keep the oracle honest
    # about the difference between "the fragment brought a call" and "the
    # interpolation conjured one".
    "QQ, factor(1)", "QQ, 'z'", "(QQ)", "QQ, *[1]", "QQ if 1 else RR",
    "factor(1)", "matrix([[1]])", "1,", "(1,)", "QQ,",
)

_INJECT = (
    ") ", "; ", " #", "\\n", "\\r", "\\\\", "'", '"', "\\u2028", "\\x00",
    "\\t", " \\\\\n ", "]", "}", "(",
)


def _statements(code: str) -> list[ast.stmt] | None:
    try:
        return ast.parse(code).body
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        return None


def _calls(tree: list[ast.stmt]) -> int:
    return sum(
        isinstance(node, ast.Call) for stmt in tree for node in ast.walk(stmt)
    )


def check(fragment: str) -> None:
    """One iteration. Raises AssertionError on a finding."""
    global JUDGED
    try:
        result = _validated_expression(fragment)
    except ToolError:
        return  # a refusal is the gate working
    except RecursionError:
        return
    except Exception as exc:
        raise AssertionError(
            f"gate raised {type(exc).__name__}, not ToolError, on {fragment!r}: {exc}"
        ) from exc
    JUDGED += 1

    if not isinstance(result, str):
        return

    # 2. A newline in the returned text becomes a statement break in the
    #    template it is interpolated into (item 56).
    assert "\n" not in result and "\r" not in result, (
        f"gate returned a newline for {fragment!r}: {result!r}"
    )

    # 4. Idempotence: the gate must accept what it produced, unchanged.
    try:
        again = _validated_expression(result)
    except ToolError as exc:
        raise AssertionError(
            f"gate rejected its own output for {fragment!r}: {result!r} -> {exc}"
        ) from exc
    assert again == result, f"gate is not idempotent on {fragment!r}: {result!r} -> {again!r}"

    # 3. Interpolated into the two real template shapes, the result must not
    #    add a statement or a call. `_G = <x>` is one Assign; a fragment that
    #    closes the call in `PolynomialRing(<x>, 'y')` would add a second
    #    statement or an extra Call node.
    for template, baseline in (
        ("_G = {}\n", "_G = None\n"),
        ("_R = PolynomialRing({}, 'y')\n", "_R = PolynomialRing(None, 'y')\n"),
    ):
        generated = _statements(template.format(result))
        if generated is None:
            continue  # the template will not compile; the worker refuses it
        expected = _statements(baseline)
        assert expected is not None
        assert len(generated) == len(expected), (
            f"{fragment!r} -> {result!r} turned one statement into "
            f"{len(generated)} in {template!r}"
        )
        # Every call in the generated line must come from the fragment itself
        # or from the template's own baseline.
        own = _statements(f"_x = {result}\n")
        own_calls = _calls(own) if own else 0
        assert _calls(generated) <= _calls(expected) + own_calls, (
            f"{fragment!r} -> {result!r} added a call in {template!r}"
        )


def campaign(iterations: int = 5000, seed: int = 0) -> int:
    rng = random.Random(seed)
    for _ in range(iterations):
        shape = rng.choice(_SHAPES)
        fragment = shape.format(n=rng.choice(DENIED)) if "{n}" in shape else shape
        for _ in range(rng.randint(0, 2)):
            where = rng.randint(0, len(fragment))
            fragment = fragment[:where] + rng.choice(_INJECT) + fragment[where:]
        check(fragment)
    if JUDGED < 1:
        raise AssertionError(
            "the campaign judged nothing: every fragment was refused, so a "
            "clean result says nothing about what the gate accepts"
        )
    print(
        f"codegen campaign clean: {JUDGED} of {iterations} fragments accepted and "
        f"checked, over {len(_SHAPES)} shapes x {len(DENIED)} denied names (seed {seed})"
    )
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Fuzz the codegen gates.")
    parser.add_argument("--iterations", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)
    return campaign(args.iterations, args.seed)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
