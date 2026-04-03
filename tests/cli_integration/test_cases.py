"""All 44 CLI integration test cases covering 18 MCP tools."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MathTestCase:
    id: str
    tool_name: str
    domain: str
    prompt: str
    expected_substrings: list[str]
    timeout_seconds: int = 120
    negative_substrings: list[str] = field(default_factory=list)
    soft_fail_ok: bool = False


# ---------------------------------------------------------------------------
# Calculus
# ---------------------------------------------------------------------------

CALCULUS_CASES = [
    MathTestCase(
        id="diff-01",
        tool_name="differentiate_expression",
        domain="calculus",
        prompt="Differentiate x^3 + 2*x with respect to x using the sagemath MCP tool.",
        expected_substrings=["3*x^2 + 2", "3x² + 2", "3*x**2 + 2"],
    ),
    MathTestCase(
        id="diff-02",
        tool_name="differentiate_expression",
        domain="calculus",
        prompt=(
            "Find the second derivative of sin(x) with respect to x "
            "using the sagemath differentiation tool."
        ),
        expected_substrings=["-sin(x)", "-sin x", "-sin("],
    ),
    MathTestCase(
        id="diff-03",
        tool_name="differentiate_expression",
        domain="calculus",
        prompt="What is the derivative of e^(2*x) with respect to x? Use the sagemath MCP tool.",
        expected_substrings=["2*e^(2*x)", "2e^{2x}", "2*e^(2x)", "2*exp(2*x)"],
    ),
    MathTestCase(
        id="int-01",
        tool_name="integrate_expression",
        domain="calculus",
        prompt=(
            "Compute the indefinite integral of x^2 with respect to x "
            "using the sagemath integration tool."
        ),
        expected_substrings=["x^3/3", "1/3*x^3", "x³/3"],
    ),
    MathTestCase(
        id="int-02",
        tool_name="integrate_expression",
        domain="calculus",
        prompt=(
            "Evaluate the definite integral of x from 0 to 1 "
            "using the sagemath MCP integration tool."
        ),
        expected_substrings=["1/2", "0.5"],
    ),
    MathTestCase(
        id="int-03",
        tool_name="integrate_expression",
        domain="calculus",
        prompt="Integrate sin(x) from 0 to pi using the sagemath integration tool.",
        expected_substrings=["2"],
    ),
    MathTestCase(
        id="lim-01",
        tool_name="limit_expression",
        domain="calculus",
        prompt=(
            "Compute the limit of sin(x)/x as x approaches 0 "
            "using the sagemath limit tool."
        ),
        expected_substrings=["1"],
    ),
    MathTestCase(
        id="lim-02",
        tool_name="limit_expression",
        domain="calculus",
        prompt=(
            "What is the limit of (1 + 1/n)^n as n approaches infinity? "
            "Use the sagemath limit tool."
        ),
        expected_substrings=["e", "2.718"],
    ),
    MathTestCase(
        id="ser-01",
        tool_name="series_expansion",
        domain="calculus",
        prompt=(
            "Find the Taylor series of e^x around x=0 up to order 5 "
            "using the sagemath series tool."
        ),
        expected_substrings=["1/2*x^2", "x^2/2", "1/6*x^3", "x^3/6"],
    ),
    MathTestCase(
        id="ser-02",
        tool_name="series_expansion",
        domain="calculus",
        prompt=(
            "Compute the Maclaurin series of sin(x) to order 7 "
            "using the sagemath series expansion tool."
        ),
        expected_substrings=["x^3/6", "1/6*x^3", "x^5/120", "1/120*x^5"],
    ),
]

# ---------------------------------------------------------------------------
# Algebra & Simplification
# ---------------------------------------------------------------------------

ALGEBRA_CASES = [
    MathTestCase(
        id="sol-01",
        tool_name="solve_equation",
        domain="algebra",
        prompt="Solve x^2 - 5*x + 6 = 0 using the sagemath equation solver tool.",
        expected_substrings=["2", "3"],
    ),
    MathTestCase(
        id="sol-02",
        tool_name="solve_equation",
        domain="algebra",
        prompt=(
            "Solve the system of equations: x + y = 10 and x - y = 4. "
            "Use the sagemath solve tool."
        ),
        expected_substrings=["7", "3"],
    ),
    MathTestCase(
        id="sol-03",
        tool_name="solve_equation",
        domain="algebra",
        prompt="Find the roots of x^3 - 6*x^2 + 11*x - 6 = 0 using the sagemath solver.",
        expected_substrings=["1", "2", "3"],
    ),
    MathTestCase(
        id="simp-01",
        tool_name="simplify_expression",
        domain="algebra",
        prompt="Simplify (x^2 - 1)/(x - 1) using the sagemath simplify tool.",
        expected_substrings=["x + 1"],
    ),
    MathTestCase(
        id="simp-02",
        tool_name="simplify_expression",
        domain="algebra",
        prompt="Simplify sin(x)^2 + cos(x)^2 using the sagemath simplify tool.",
        expected_substrings=["1"],
    ),
    MathTestCase(
        id="exp-01",
        tool_name="expand_expression",
        domain="algebra",
        prompt="Expand (x + 1)^3 using the sagemath expand tool.",
        expected_substrings=[
            "x^3 + 3*x^2 + 3*x + 1",
            "x³ + 3x² + 3x + 1",
            "x^3 + 3x^2 + 3x + 1",
            "x**3 + 3*x**2 + 3*x + 1",
        ],
    ),
    MathTestCase(
        id="exp-02",
        tool_name="expand_expression",
        domain="algebra",
        prompt="Expand (a + b)*(a - b) using the sagemath expand tool.",
        expected_substrings=["a^2 - b^2", "a² - b²"],
    ),
    MathTestCase(
        id="fac-01",
        tool_name="factor_expression",
        domain="algebra",
        prompt="Factor x^2 - 4 using the sagemath factor tool.",
        expected_substrings=["(x - 2)", "(x + 2)"],
    ),
    MathTestCase(
        id="fac-02",
        tool_name="factor_expression",
        domain="algebra",
        prompt=(
            "Factor x^3 - 2*x^2 - x + 2 using the sagemath factor tool."
        ),
        expected_substrings=["(x - 2)", "(x - 1)", "(x + 1)"],
    ),
    MathTestCase(
        id="calc-01",
        tool_name="calculate_expression",
        domain="algebra",
        prompt=(
            "Calculate sqrt(2) + sqrt(3) numerically "
            "using the sagemath calculate expression tool."
        ),
        expected_substrings=["3.146", "3.1462"],
    ),
    MathTestCase(
        id="calc-02",
        tool_name="calculate_expression",
        domain="algebra",
        prompt="Evaluate 2^10 + 3^5 using the sagemath calculate tool.",
        expected_substrings=["1267"],
    ),
]

# ---------------------------------------------------------------------------
# Linear Algebra
# ---------------------------------------------------------------------------

LINEAR_ALGEBRA_CASES = [
    MathTestCase(
        id="mm-01",
        tool_name="matrix_multiply",
        domain="linear_algebra",
        prompt=(
            "Multiply the matrices [[1,2],[3,4]] and [[5,6],[7,8]] "
            "using the sagemath matrix multiply tool."
        ),
        expected_substrings=["19", "22", "43", "50"],
    ),
    MathTestCase(
        id="mm-02",
        tool_name="matrix_multiply",
        domain="linear_algebra",
        prompt=(
            "Compute the product of matrices [[1,0,2],[0,1,0]] "
            "and [[1,2],[3,4],[5,6]] using the sagemath matrix tool."
        ),
        expected_substrings=["11", "14"],
    ),
    MathTestCase(
        id="mop-01",
        tool_name="matrix_operation",
        domain="linear_algebra",
        prompt=(
            "Find the determinant of the matrix [[1,2],[3,4]] "
            "using the sagemath matrix operation tool."
        ),
        expected_substrings=["-2"],
    ),
    MathTestCase(
        id="mop-02",
        tool_name="matrix_operation",
        domain="linear_algebra",
        prompt=(
            "Compute the inverse of the matrix [[1,2],[3,5]] "
            "using the sagemath matrix operation tool."
        ),
        expected_substrings=["5", "-2", "-3", "1"],
    ),
    MathTestCase(
        id="mop-03",
        tool_name="matrix_operation",
        domain="linear_algebra",
        prompt=(
            "Find the eigenvalues of the matrix [[4,1],[2,3]] "
            "using the sagemath matrix operation tool."
        ),
        expected_substrings=["5", "2"],
    ),
]

# ---------------------------------------------------------------------------
# Differential Equations
# ---------------------------------------------------------------------------

ODE_CASES = [
    MathTestCase(
        id="ode-01",
        tool_name="solve_ode",
        domain="ode",
        prompt=(
            "Solve the ordinary differential equation y' + y = 0 "
            "using the sagemath ODE solver tool."
        ),
        expected_substrings=["e^(-x)", "e^{-x}", "exp(-x)", "e^(-1*x)"],
    ),
    MathTestCase(
        id="ode-02",
        tool_name="solve_ode",
        domain="ode",
        prompt=(
            "Solve the differential equation y'' - y = 0 "
            "using the sagemath ODE solver tool."
        ),
        expected_substrings=["e^x", "e^(-x)", "exp(x)", "exp(-x)", "cosh", "sinh"],
    ),
]

# ---------------------------------------------------------------------------
# Number Theory
# ---------------------------------------------------------------------------

NUMBER_THEORY_CASES = [
    MathTestCase(
        id="nt-01",
        tool_name="number_theory_operation",
        domain="number_theory",
        prompt="Is 97 a prime number? Use the sagemath number theory tool.",
        expected_substrings=["true", "True", "yes", "Yes", "is prime", "is a prime"],
    ),
    MathTestCase(
        id="nt-02",
        tool_name="number_theory_operation",
        domain="number_theory",
        prompt="Is 100 a prime number? Use the sagemath number theory tool.",
        expected_substrings=[
            "false", "False", "no", "No", "not prime",
            "not a prime", "is not prime", "is not a prime",
        ],
    ),
    MathTestCase(
        id="nt-03",
        tool_name="number_theory_operation",
        domain="number_theory",
        prompt="Factor the integer 360 into primes using the sagemath number theory tool.",
        expected_substrings=["2^3", "3^2", "5"],
    ),
    MathTestCase(
        id="nt-04",
        tool_name="number_theory_operation",
        domain="number_theory",
        prompt="What is the next prime number after 100? Use the sagemath number theory tool.",
        expected_substrings=["101"],
    ),
    MathTestCase(
        id="nt-05",
        tool_name="number_theory_operation",
        domain="number_theory",
        prompt=(
            "Compute the greatest common divisor (GCD) of 48 and 36 "
            "using the sagemath number theory tool."
        ),
        expected_substrings=["12"],
    ),
    MathTestCase(
        id="nt-06",
        tool_name="number_theory_operation",
        domain="number_theory",
        prompt=(
            "What is the least common multiple (LCM) of 12 and 18? "
            "Use the sagemath number theory tool."
        ),
        expected_substrings=["36"],
    ),
]

# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

STATISTICS_CASES = [
    MathTestCase(
        id="stat-01",
        tool_name="statistics_summary",
        domain="statistics",
        prompt=(
            "Compute descriptive statistics for the dataset [2, 4, 6, 8, 10] "
            "using the sagemath statistics tool."
        ),
        expected_substrings=["6"],  # mean=6
    ),
    MathTestCase(
        id="stat-02",
        tool_name="statistics_summary",
        domain="statistics",
        prompt=(
            "Give me the mean, median, and standard deviation of [1, 1, 2, 3, 5, 8, 13] "
            "using the sagemath statistics tool."
        ),
        expected_substrings=["4.71", "3"],  # mean~4.71, median=3
    ),
]

# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------

PLOTTING_CASES = [
    MathTestCase(
        id="plot-01",
        tool_name="plot_expression",
        domain="plotting",
        prompt="Plot the function sin(x) from -6.28 to 6.28 using the sagemath plot tool.",
        expected_substrings=["base64", "image", "png", "plot", "PNG"],
    ),
    MathTestCase(
        id="plot-02",
        tool_name="plot_expression",
        domain="plotting",
        prompt="Create a graph of x^2 from -5 to 5 using the sagemath plot tool.",
        expected_substrings=["base64", "image", "png", "plot", "PNG"],
    ),
]

# ---------------------------------------------------------------------------
# General computation (evaluate_sage)
# ---------------------------------------------------------------------------

EVALUATE_SAGE_CASES = [
    MathTestCase(
        id="eval-01",
        tool_name="evaluate_sage",
        domain="general",
        prompt=(
            "Using the sagemath evaluate_sage tool, compute the "
            "chromatic number of the Petersen graph."
        ),
        expected_substrings=["3"],
    ),
    MathTestCase(
        id="eval-02",
        tool_name="evaluate_sage",
        domain="general",
        prompt="Use the sagemath evaluate_sage tool to compute binomial(20, 10).",
        expected_substrings=["184756"],
    ),
    MathTestCase(
        id="eval-03",
        tool_name="evaluate_sage",
        domain="general",
        prompt=(
            "Compute the first 10 prime numbers using the sagemath evaluate_sage tool."
        ),
        expected_substrings=["2", "3", "5", "7", "11", "13", "17", "19", "23", "29"],
    ),
]

# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

SESSION_CASES = [
    MathTestCase(
        id="rst-01",
        tool_name="reset_sage_session",
        domain="session",
        prompt=(
            "Using sagemath tools: first evaluate 'my_var = 42', "
            "then reset the sage session, then try to evaluate 'my_var'. "
            "Tell me what happened."
        ),
        expected_substrings=[
            "reset", "cleared", "not defined", "undefined", "NameError", "error",
        ],
        soft_fail_ok=True,
    ),
    MathTestCase(
        id="can-01",
        tool_name="cancel_sage_session",
        domain="session",
        prompt=(
            "Using sagemath tools: cancel the current sage session. "
            "Confirm that it was cancelled and restarted."
        ),
        expected_substrings=["cancel", "restart", "cleared", "Session"],
        soft_fail_ok=True,
    ),
]

# ---------------------------------------------------------------------------
# Combined list
# ---------------------------------------------------------------------------

ALL_TEST_CASES: list[MathTestCase] = [
    *CALCULUS_CASES,
    *ALGEBRA_CASES,
    *LINEAR_ALGEBRA_CASES,
    *ODE_CASES,
    *NUMBER_THEORY_CASES,
    *STATISTICS_CASES,
    *PLOTTING_CASES,
    *EVALUATE_SAGE_CASES,
    *SESSION_CASES,
]

DOMAINS = {
    "calculus": CALCULUS_CASES,
    "algebra": ALGEBRA_CASES,
    "linear_algebra": LINEAR_ALGEBRA_CASES,
    "ode": ODE_CASES,
    "number_theory": NUMBER_THEORY_CASES,
    "statistics": STATISTICS_CASES,
    "plotting": PLOTTING_CASES,
    "general": EVALUATE_SAGE_CASES,
    "session": SESSION_CASES,
}
