"""Tool-forcing CLI cases: questions a model cannot answer from memory.

The existing suite in ``test_cases.py`` validates by grepping the CLI's final
answer. That cannot distinguish "the MCP server computed this" from "the model
already knew it": asked to differentiate x^3 + 2x, every model replies 3x^2 + 2
without touching any tool, and the test passes.

Two changes here:

* Each question has an answer that is impractical to recall or do in-head --
  next_prime(10^30), Bell(25), a 5x5 determinant. A model that skips the tool
  gets it wrong, or refuses.
* Every case additionally asserts, from the proxy's wire log, that the expected
  tool was actually called and did not return an error. That is the part which
  makes this an integration test rather than a quiz.

Expected values were computed with SageMath 10.9 and are exact.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ToolForcingCase:
    id: str
    domain: str
    prompt: str
    # Any one of these in the CLI's answer counts as correct.
    expected_answers: list[str]
    # The tool call the server must actually receive. Several are allowed
    # because a model may legitimately reach the same result another way, for
    # example evaluate_sage instead of the dedicated helper.
    accepted_tools: list[str]
    timeout_seconds: int = 300
    # Substrings that mean the model dodged rather than computed.
    forbidden: list[str] = field(default_factory=lambda: ["cannot", "unable to"])


_SUFFIX = " Use the sagemath MCP server. Reply with ONLY the result, no prose."

EXTENDED_CASES: list[ToolForcingCase] = [
    # ---- number theory -----------------------------------------------------
    ToolForcingCase(
        id="ext-nt-next-prime",
        domain="number_theory",
        # 31 digits: not memorised, and not doable mentally.
        prompt="What is the smallest prime strictly greater than 10^30?" + _SUFFIX,
        expected_answers=["1000000000000000000000000000057"],
        accepted_tools=["number_theory_operation", "evaluate_sage", "calculate_expression"],
    ),
    ToolForcingCase(
        id="ext-nt-factorial-mod",
        domain="number_theory",
        prompt="Compute factorial(50) modulo 1000003." + _SUFFIX,
        expected_answers=["850717"],
        accepted_tools=["evaluate_sage", "calculate_expression", "number_theory_operation"],
    ),
    # ---- combinatorics -----------------------------------------------------
    ToolForcingCase(
        id="ext-comb-bell",
        domain="combinatorics",
        prompt="What is the 25th Bell number?" + _SUFFIX,
        expected_answers=["4638590332229999353"],
        accepted_tools=["combinatorics_operation", "evaluate_sage", "calculate_expression"],
    ),
    ToolForcingCase(
        id="ext-comb-partitions",
        domain="combinatorics",
        prompt="How many integer partitions does 120 have?" + _SUFFIX,
        expected_answers=["1844349560"],
        accepted_tools=["combinatorics_operation", "evaluate_sage", "calculate_expression"],
    ),
    # ---- linear algebra ----------------------------------------------------
    ToolForcingCase(
        id="ext-la-determinant",
        domain="linear_algebra",
        prompt=(
            "Compute the determinant of the 5x5 integer matrix "
            "[[3,1,4,1,5],[9,2,6,5,3],[5,8,9,7,9],[3,2,3,8,4],[6,2,6,4,3]]." + _SUFFIX
        ),
        expected_answers=["-1813"],
        accepted_tools=["matrix_operation", "evaluate_sage"],
    ),
    # ---- elliptic curves ---------------------------------------------------
    ToolForcingCase(
        id="ext-ec-conductor",
        domain="elliptic_curves",
        prompt=(
            "For the elliptic curve with Weierstrass coefficients [0,0,1,-7,6], "
            "what is its conductor?" + _SUFFIX
        ),
        expected_answers=["5077"],
        accepted_tools=["elliptic_curve_operation", "evaluate_sage"],
    ),
    # ---- coding theory -----------------------------------------------------
    ToolForcingCase(
        id="ext-coding-hamming",
        domain="coding_theory",
        prompt=(
            "For the binary Hamming code HammingCode(GF(2),5), give its length "
            "and dimension as 'length,dimension'." + _SUFFIX
        ),
        expected_answers=["31,26", "31, 26"],
        accepted_tools=["coding_theory_operation", "evaluate_sage"],
    ),
    # ---- stateful: impossible to fake ---------------------------------------
    # ---- open problems ------------------------------------------------------
    # A mathematician's questions rather than a calculator's. Each answer needs a
    # real sweep -- none is recallable, and none is doable in-head -- so a model
    # that skips the server cannot bluff its way past the wire-log check. These
    # also exercise the shape the research suite covers: define, sweep, report.
    ToolForcingCase(
        id="ext-open-twin-primes",
        domain="open_problems",
        prompt=(
            "How many twin prime pairs (p, p+2) are there with p+2 below one million? "
            "Twin primes are an open problem, so count them exactly rather than estimating."
        ) + _SUFFIX,
        expected_answers=["8169"],
        accepted_tools=["evaluate_sage", "evaluate_sage_streaming", "number_theory_operation"],
    ),
    ToolForcingCase(
        id="ext-open-collatz-record",
        domain="open_problems",
        prompt=(
            "For the Collatz 3n+1 map, which starting value below 100000 takes the most "
            "steps to reach 1, and how many steps does it take? Answer as 'value, steps'."
        ) + _SUFFIX,
        expected_answers=["77031"],
        accepted_tools=["evaluate_sage", "evaluate_sage_streaming"],
        timeout_seconds=420,
    ),
    ToolForcingCase(
        id="ext-open-prime-gap",
        domain="open_problems",
        prompt=(
            "What is the largest gap between consecutive primes below one million, and "
            "which prime does that gap start at? Answer as 'gap, prime'."
        ) + _SUFFIX,
        expected_answers=["492113"],
        accepted_tools=["evaluate_sage", "evaluate_sage_streaming", "number_theory_operation"],
    ),
    ToolForcingCase(
        id="ext-open-amicable",
        domain="open_problems",
        prompt=(
            "List every amicable pair (a, b) with a < b < 10000, where each number is the "
            "sum of the other's proper divisors."
        ) + _SUFFIX,
        expected_answers=["6232"],
        accepted_tools=["evaluate_sage", "evaluate_sage_streaming"],
    ),
    ToolForcingCase(
        id="ext-open-bsd-rank",
        domain="open_problems",
        prompt=(
            "For the elliptic curve y^2 + y = x^3 - 7x + 6, what is its Mordell-Weil rank "
            "and its conductor? Answer as 'rank, conductor'."
        ) + _SUFFIX,
        expected_answers=["5077"],
        accepted_tools=["elliptic_curve_operation", "evaluate_sage"],
    ),
    ToolForcingCase(
        id="ext-session-state",
        domain="session",
        # Nothing here is knowable without the server actually holding state
        # between two separate tool calls.
        prompt=(
            "Using the sagemath MCP server, first evaluate the code "
            "'blob = 8675309 * 31' and then, in a SECOND separate call to the "
            "same session, evaluate the code 'blob + 1'. "
            "Reply with ONLY the number from the second call."
        ),
        expected_answers=["268934580"],
        accepted_tools=["evaluate_sage"],
    ),
    ToolForcingCase(
        id="ext-session-named",
        domain="session",
        prompt=(
            "Using the sagemath MCP server: start a named session called 'clitest', "
            "evaluate 'q = 1234' in session 'clitest', then evaluate 'q * 1001' in "
            "session 'clitest'. Reply with ONLY the final number."
        ),
        expected_answers=["1235234"],
        accepted_tools=["evaluate_sage"],
    ),
]


def by_domain(domains: set[str] | None) -> list[ToolForcingCase]:
    if not domains:
        return list(EXTENDED_CASES)
    return [case for case in EXTENDED_CASES if case.domain in domains]
