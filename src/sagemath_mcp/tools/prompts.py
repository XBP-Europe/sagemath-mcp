"""MCP prompts: reusable instructions that steer a client toward what this
server is uniquely good at -- **verified** answers and **stateful** exploration.

Almost no MCP server ships prompts, and they are the cheapest way to shape
usage: a client surfaces them in its prompt picker, so a user gets a
well-formed request without having to know the tool surface. Each one points the
model at the tools that make the difference -- `verify_claim` for certainty,
`evaluate_sage` in one session for building an object and exploring it -- rather
than leaving it to guess.

One of the tool modules imported by :mod:`sagemath_mcp.server` for its
registration side effect; it decorates against the shared ``mcp`` object like
the tool modules do. Prompts return plain instruction text the model reads --
never executed code -- so the free-text arguments are interpolated directly,
with no security gate.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from ..app import mcp


@mcp.prompt(
    name="prove_and_verify",
    description="Prove a mathematical identity or claim, then confirm it independently "
    "with the verify_claim tool.",
)
def prove_and_verify(
    claim: Annotated[
        str,
        Field(
            description="The identity or claim to establish, "
            "for example sin(x)^2 + cos(x)^2 == 1"
        ),
    ],
) -> str:
    return (
        "Establish the following claim. Show the key steps of the argument, then "
        "check it independently by calling the `verify_claim` tool with the exact "
        "claim string, and read its verdict honestly:\n"
        "- `proved` or `refuted` is an exact decision -- if it is `refuted`, your "
        "argument is wrong; reconcile it before you answer.\n"
        "- `supported` means the evidence is consistent with the claim but does not "
        "prove it, and `undecided` means the tool could not settle it. Neither is "
        "evidence that your argument is wrong -- an inconclusive CAS result is not a "
        "refutation. Say what was and was not established (for a `float_comparison` "
        "result, restate the claim over exact numbers for a decisive check), and do "
        "not present an unproven identity as established.\n\n"
        f"Claim: {claim}"
    )


@mcp.prompt(
    name="solve_and_check",
    description="Solve a problem step by step, then sanity-check the result with the tools "
    "before presenting it.",
)
def solve_and_check(
    problem: Annotated[
        str,
        Field(description="The problem to solve, for example the real roots of x^3 - 2x + 1 = 0"),
    ],
) -> str:
    return (
        "Solve the following problem step by step, working in a single Sage session "
        "so intermediate values carry over. Prefer the specialised tools "
        "(`solve_equation`, `integrate_expression`, `find_root`, ...) where they fit, "
        "and `evaluate_sage` for the connective steps. Before presenting the answer, "
        "check it: substitute a solution back in, compare a symbolic result against a "
        "numeric one, or state the claim to `verify_claim`. Report the check you ran, "
        "not just the answer.\n\n"
        f"Problem: {problem}"
    )


@mcp.prompt(
    name="explore_object",
    description="Construct a mathematical object once and explore its properties across "
    "calls in one persistent session.",
)
def explore_object(
    construction: Annotated[
        str,
        Field(
            description="How to build the object, for example the elliptic curve "
            "y^2 = x^3 - x, or the number field Q(cbrt(2))"
        ),
    ],
) -> str:
    return (
        "Build the object described below once with `evaluate_sage`, assigning it to a "
        "variable, then explore it over several calls in the **same** session so the "
        "construction is not repeated -- the specialised tools evaluate in a fresh "
        "namespace and cannot see it, so keep the work in `evaluate_sage`. Compute its "
        "salient invariants, note anything surprising, and verify any identity you "
        "claim about it with `verify_claim`.\n\n"
        f"Object: {construction}"
    )
