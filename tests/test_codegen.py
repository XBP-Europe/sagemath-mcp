"""Unit tests for the code-building helpers.

These were the least-covered code in the project, and the split made that
visible: the misses did not move, they just stopped hiding inside a 2327-line
module. Everything here runs without a Sage runtime.

The distribution values are asserted against the closed forms from the
literature rather than against whatever the implementation returns, so a wrong
formula fails instead of being blessed.
"""

from __future__ import annotations

import pytest
from fastmcp.exceptions import ToolError

from sagemath_mcp.codegen import (
    _check_matrix,
    _declare_free_symbols,
    _distribution_mean,
    _distribution_variance,
    _encode_literal,
    _exact_int,
    _normal_parameters,
    _normalize_source,
    _reject_if_inexact,
    _sage_prelude,
    _screen_unparseable_fragment,
    _validated_expression,
    _validated_identifier,
)

# distribution, parameters, mean, variance
DISTRIBUTIONS = [
    ("normal", [3.0, 2.0], 3.0, 4.0),                    # mu, sigma^2
    ("normal", [2.0], 0.0, 4.0),                         # lone parameter is sigma
    ("normal", [], 0.0, 1.0),                            # standard normal
    ("exponential", [4.0], 4.0, 16.0),                   # mean mu, variance mu^2
    ("exponential", [], 1.0, 1.0),
    ("uniform", [2.0, 8.0], 5.0, 3.0),                   # (a+b)/2, (b-a)^2/12
    ("chi_squared", [5.0], 5.0, 10.0),                   # k, 2k
    ("chi_squared", [], 1.0, 2.0),
    ("beta", [2.0, 3.0], 0.4, 0.04),                     # a/(a+b), ab/((a+b)^2(a+b+1))
    ("gamma", [3.0, 2.0], 6.0, 12.0),                    # k*theta, k*theta^2
]


@pytest.mark.parametrize(
    "distribution,parameters,mean,variance",
    DISTRIBUTIONS,
    ids=[f"{d}-{len(p)}params" for d, p, _, _ in DISTRIBUTIONS],
)
def test_distribution_moments_match_the_closed_forms(
    distribution: str, parameters: list[float], mean: float, variance: float
) -> None:
    assert _distribution_mean(distribution, parameters) == pytest.approx(mean)
    assert _distribution_variance(distribution, parameters) == pytest.approx(variance)


def test_student_t_moments_and_the_ranges_where_they_do_not_exist() -> None:
    """The mean needs nu > 1 and the variance nu > 2; both are real constraints."""
    assert _distribution_mean("student_t", [3.0]) == 0.0
    assert _distribution_variance("student_t", [4.0]) == pytest.approx(2.0)  # nu/(nu-2)

    with pytest.raises(ToolError, match="mean is undefined"):
        _distribution_mean("student_t", [1.0])
    with pytest.raises(ToolError, match="variance is undefined"):
        _distribution_variance("student_t", [2.0])
    # The no-parameter default (nu = 1) is undefined for both.
    with pytest.raises(ToolError):
        _distribution_mean("student_t", [])
    with pytest.raises(ToolError):
        _distribution_variance("student_t", [])


@pytest.mark.parametrize("distribution", ["uniform", "beta", "gamma"])
def test_two_parameter_distributions_reject_a_short_parameter_list(distribution: str) -> None:
    """Silently defaulting the second parameter would return a plausible number."""
    with pytest.raises(ToolError, match="requires parameters"):
        _distribution_mean(distribution, [1.0])
    with pytest.raises(ToolError, match="requires parameters"):
        _distribution_variance(distribution, [1.0])


def test_unknown_distributions_are_named_in_the_error() -> None:
    with pytest.raises(ToolError, match="cauchy"):
        _distribution_mean("cauchy", [0.0, 1.0])
    with pytest.raises(ToolError, match="cauchy"):
        _distribution_variance("cauchy", [0.0, 1.0])


def test_normal_parameters_defaults() -> None:
    assert _normal_parameters([1.5, 2.5]) == (1.5, 2.5)
    assert _normal_parameters([2.5]) == (0.0, 2.5)
    assert _normal_parameters([]) == (0.0, 1.0)


# ---------------------------------------------------------------------------
# Matrix and integer guards
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rows,message",
    [
        ([], "non-empty list of rows"),
        ("not a list", "non-empty list of rows"),
        ([1, 2, 3], "non-empty list of rows"),          # rows must be lists
        ([[]], "rows must be non-empty"),
        ([[1, 2], [3]], "same length"),
    ],
)
def test_check_matrix_rejects_malformed_input(rows, message: str) -> None:
    """The empty matrix is the dangerous one.

    Sage reads [] as the 0x0 matrix and reports its determinant as 1.0, which
    reads like a real answer rather than a mistake.
    """
    with pytest.raises(ToolError, match=message):
        _check_matrix(rows, "matrix")


def test_check_matrix_accepts_well_formed_matrices() -> None:
    assert _check_matrix([[1, 2], [3, 4]], "matrix") is None
    assert _check_matrix([[1.5]], "matrix") is None


def test_exact_int_accepts_the_documented_spellings() -> None:
    assert _exact_int(7, "a") == 7
    assert _exact_int("7", "a") == 7
    assert _exact_int(7.0, "a") == 7
    assert _exact_int("-12345678901234567890123", "a") == -12345678901234567890123


@pytest.mark.parametrize(
    "value,message",
    [
        (True, "must be an integer, got a boolean"),   # bool is an int subclass
        ("twelve", "not a decimal integer"),
        ("1e5", "not a decimal integer"),
        (7.5, "whole number"),
    ],
)
def test_exact_int_rejects_what_it_cannot_represent(value, message: str) -> None:
    with pytest.raises(ToolError, match=message):
        _exact_int(value, "a")


def test_reject_if_inexact_guards_the_json_number_boundary() -> None:
    """Above 2^53 a JSON number stops being exact, so it must arrive as a string."""
    limit = 2**53
    assert _reject_if_inexact(limit - 1, "a") == limit - 1
    with pytest.raises(ToolError, match="2\\^53"):
        _reject_if_inexact(limit + 1, "a")
    with pytest.raises(ToolError, match="2\\^53"):
        _reject_if_inexact(-(limit + 1), "a")


# ---------------------------------------------------------------------------
# Validation gates
# ---------------------------------------------------------------------------


def test_validated_expression_passes_non_strings_and_blanks_through() -> None:
    assert _validated_expression(5) == 5
    assert _validated_expression(None) is None
    assert _validated_expression("   ") == "   "


def test_validated_expression_accepts_the_sage_equation_spelling() -> None:
    """A single '=' is not a Python expression but is the documented input."""
    assert _validated_expression("x^2 - 1 = 0") == "x^2 - 1 = 0"
    assert _validated_expression("x + y = 3") == "x + y = 3"


def test_validated_expression_rejects_payloads_in_either_spelling() -> None:
    with pytest.raises(ToolError, match="security policy"):
        _validated_expression("__import__('os').getuid()")
    # Unparseable, so screened at token level instead.
    with pytest.raises(ToolError, match="security policy"):
        _validated_expression("R.<a> = os.getuid()")


def test_screen_unparseable_fragment_reports_unreadable_input() -> None:
    """Tokenizing can fail outright; that must be an error, not a pass."""
    with pytest.raises(ToolError, match="Could not read"):
        _screen_unparseable_fragment("'unterminated")


def test_screen_unparseable_fragment_allows_clean_sage_only_syntax() -> None:
    assert _screen_unparseable_fragment("R.<a,b> = QQ[]") is None


@pytest.mark.parametrize("name", ["x", "alpha", "t1", "_v"])
def test_validated_identifier_accepts_identifiers(name: str) -> None:
    assert _validated_identifier(name, "variable") == name


@pytest.mark.parametrize("name", ["x', sage_eval('1'), 'y", "x y", "2x", "", "x-1", 5])
def test_validated_identifier_rejects_everything_else(name) -> None:
    with pytest.raises(ToolError, match="plain identifier"):
        _validated_identifier(name, "variable")


def test_encode_literal_validates_strings_inside_lists() -> None:
    assert _encode_literal(["x", "y"]) == '["x", "y"]'
    with pytest.raises(ToolError, match="security policy"):
        _encode_literal(["x", "__import__('os')"])


def test_normalize_source_strips_and_flattens() -> None:
    assert _normalize_source("  x + 1  ") == "x + 1"
    assert _normalize_source(["  a ", "b"]) == ["a", "b"]
    assert _normalize_source(3) == 3


def test_sage_prelude_declares_the_default_symbols() -> None:
    prelude = _sage_prelude()
    for name in ("'x'", "'y'", "'z'", "'t'"):
        assert name in prelude


def test_declare_free_symbols_handles_both_kinds_of_name() -> None:
    """Short index-style names are declared outright; longer ones only if Sage
    does not already define them, so `gamma` keeps meaning the function."""
    declared = _declare_free_symbols("sum(k, k, 1, n)")
    assert "_sage_ns" in declared
    assert _declare_free_symbols(None) == "" or "_sage_ns" in _declare_free_symbols(None)


def test_validated_expression_screens_a_fragment_with_no_equals_to_rewrite() -> None:
    """The other unparseable route: no "=" to rewrite, so screen the tokens.

    "R.<a,b>" is Sage's generator syntax. Python cannot parse it, but it
    tokenizes cleanly, so it reaches the token screen rather than the
    unreadable-input error.
    """
    assert _validated_expression("R.<a,b>") == "R.<a,b>"
    with pytest.raises(ToolError, match="security policy"):
        _validated_expression("R.<a,b> os.getuid()")


def test_validated_expression_allows_sage_generator_syntax_with_an_equals() -> None:
    """"=" is rewritten to "==", that still will not parse, and the tokens are clean."""
    assert _validated_expression("R.<a,b> = QQ[]") == "R.<a,b> = QQ[]"


def test_encode_literal_passes_non_string_values_straight_to_json() -> None:
    """Numbers carry no code, so there is nothing to validate."""
    assert _encode_literal(5) == "5"
    assert _encode_literal([1, 2.5]) == "[1, 2.5]"


def test_declare_free_symbols_with_only_short_names_emits_no_conditional_clause() -> None:
    """Short index names are declared outright; only longer ones get the guard.

    "n" and "N" are numerical_approx in Sage's namespace, so summing to n used
    to resolve the bound to a function instead of a symbol. Short names
    therefore win, and need no hasattr check.
    """
    declared = _declare_free_symbols("k + n")
    assert "'k', 'n'" in declared
    assert "hasattr" not in declared, "a short name should not need the Sage-name check"


def test_declare_free_symbols_guards_names_sage_might_already_define() -> None:
    """gamma, sin and friends must keep meaning the Sage object."""
    declared = _declare_free_symbols("gamma(alpha)")
    assert "hasattr" in declared, "a spelled-out name must be checked before shadowing"
