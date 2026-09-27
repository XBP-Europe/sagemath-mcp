"""Descriptive statistics and probability distributions.

One of the tool modules imported by :mod:`sagemath_mcp.server` for its
registration side effect. Decorating against the shared ``mcp`` object keeps
every tool name exactly as it was; FastMCP's mount/import_server composition
would have prefixed them.
"""

from __future__ import annotations

import textwrap
from typing import Annotated

from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import Field

from .. import runtime
from ..app import mcp
from ..gates import encode_literal
from ..manager import DEFAULT_SESSION_NAME
from ..prelude import sage_prelude
from ..text import SESSION_ARG_DESC as _SESSION_ARG_DESC
from ..transport import evaluate_structured
from .hints import COMPUTES


def _normal_parameters(parameters: list[float]) -> tuple[float, float]:
    """Return (mu, sigma) for the documented [mu, sigma] parameter list."""
    if len(parameters) >= 2:
        return float(parameters[0]), float(parameters[1])
    if len(parameters) == 1:
        # A single parameter is the standard deviation, matching how the
        # previous implementation treated a one-element list.
        return 0.0, float(parameters[0])
    return 0.0, 1.0


def _distribution_mean(distribution: str, parameters: list[float]) -> float:
    """Analytic mean for the supported continuous distributions."""
    p = [float(v) for v in parameters]
    if distribution == "normal":
        return _normal_parameters(p)[0]
    if distribution == "exponential":
        # Sage parameterises RealDistribution('exponential', mu) by the mean.
        return p[0] if p else 1.0
    if distribution == "uniform":
        if len(p) < 2:
            raise ToolError("uniform requires parameters [a, b]")
        return (p[0] + p[1]) / 2
    if distribution == "chi_squared":
        return p[0] if p else 1.0
    if distribution == "student_t":
        nu = p[0] if p else 1.0
        if nu <= 1:
            raise ToolError("student_t mean is undefined for degrees of freedom <= 1")
        return 0.0
    if distribution == "beta":
        if len(p) < 2:
            raise ToolError("beta requires parameters [a, b]")
        return p[0] / (p[0] + p[1])
    if distribution == "gamma":
        if len(p) < 2:
            raise ToolError("gamma requires parameters [shape, scale]")
        return p[0] * p[1]
    raise ToolError(f"No analytic mean available for distribution '{distribution}'")


def _distribution_variance(distribution: str, parameters: list[float]) -> float:
    """Analytic variance for the supported continuous distributions."""
    p = [float(v) for v in parameters]
    if distribution == "normal":
        return _normal_parameters(p)[1] ** 2
    if distribution == "exponential":
        mu = p[0] if p else 1.0
        return mu**2
    if distribution == "uniform":
        if len(p) < 2:
            raise ToolError("uniform requires parameters [a, b]")
        return (p[1] - p[0]) ** 2 / 12
    if distribution == "chi_squared":
        return 2 * (p[0] if p else 1.0)
    if distribution == "student_t":
        nu = p[0] if p else 1.0
        if nu <= 2:
            raise ToolError("student_t variance is undefined for degrees of freedom <= 2")
        return nu / (nu - 2)
    if distribution == "beta":
        if len(p) < 2:
            raise ToolError("beta requires parameters [a, b]")
        a, b = p[0], p[1]
        return a * b / ((a + b) ** 2 * (a + b + 1))
    if distribution == "gamma":
        if len(p) < 2:
            raise ToolError("gamma requires parameters [shape, scale]")
        return p[0] * p[1] ** 2
    raise ToolError(f"No analytic variance available for distribution '{distribution}'")


@mcp.tool(annotations=COMPUTES, description=(
        "Descriptive statistics for a list of numbers: mean, median, population "
        "and sample variance and standard deviation, min and max. Prefer this "
        "over evaluate_sage for summary statistics."
    ))
async def statistics_summary(
    data: Annotated[list[float], Field(description="List of numeric values")],
    session: Annotated[str, Field(description=_SESSION_ARG_DESC)] = DEFAULT_SESSION_NAME,
    ctx: Context | None = None,
) -> dict:
    runtime.require_context(ctx, "for stateful execution")
    # Without this the generated code raised a bare "list index out of range"
    # from the median calculation, which says nothing about what to send instead.
    if not data:
        raise ToolError("statistics_summary requires at least one value in 'data'")
    session = await runtime.session_for(ctx, session)
    code = (
        sage_prelude()
        + textwrap.dedent(
            f"""
        _data = {encode_literal(data)}
        _n = len(_data)
        _mean = float(mean(_data))
        _sorted = sorted(_data)
        _mid = _n // 2
        _median = float((_sorted[_mid] + _sorted[~_mid]) / 2)
        _pvar = float(sum((x - _mean)**2 for x in _data) / _n)
        _svar = float(sum((x - _mean)**2 for x in _data) / (_n - 1)) if _n > 1 else 0.0
        {{
            'mean': _mean,
            'median': _median,
            'population_variance': _pvar,
            'sample_variance': _svar,
            'population_std_dev': float(sqrt(_pvar)),
            'sample_std_dev': float(sqrt(_svar)),
            'min': float(min(_data)),
            'max': float(max(_data)),
        }}
        """
        )
    )
    return await evaluate_structured(session, code)


@mcp.tool(
    annotations=COMPUTES,
    description="Probability distribution operations: PDF, CDF, quantile, mean, variance, sampling"
)
async def distribution_operation(
    distribution: Annotated[
        str,
        Field(
            description="Distribution name: normal, exponential, poisson, "
            "chi_squared, student_t, uniform, beta, gamma"
        ),
    ],
    parameters: Annotated[
        list[float], Field(description="Distribution parameters (e.g. [0, 1] for standard normal)")
    ],
    operation: Annotated[
        str, Field(description="One of: pdf, cdf, quantile, mean, variance, sample")
    ],
    x: Annotated[float | None, Field(description="Point for pdf/cdf/quantile evaluation")] = None,
    n: Annotated[int | None, Field(description="Number of samples (for sample operation)")] = None,
    session: Annotated[str, Field(description=_SESSION_ARG_DESC)] = DEFAULT_SESSION_NAME,
    ctx: Context | None = None,
) -> dict:
    runtime.require_context(ctx, "for stateful execution")
    operation = operation.strip()
    session = await runtime.session_for(ctx, session)
    params_str = ", ".join(str(p) for p in parameters)
    # "normal" takes [mu, sigma]. The previous mapping passed parameters[0] as
    # sigma only when exactly one parameter was given and otherwise hardcoded
    # 1, so [0, 3] silently computed with sigma=1, and mu was never applied at
    # all. Sage's gaussian is always centred on 0, so mu is applied by shifting
    # the evaluation point.
    normal_mu, normal_sigma = _normal_parameters(parameters)
    dist_map = {
        "normal": f"RealDistribution('gaussian', {normal_sigma})",
        "exponential": f"RealDistribution('exponential', {parameters[0] if parameters else 1})",
        "uniform": f"RealDistribution('uniform', [{params_str}])",
        "chi_squared": f"RealDistribution('chisquared', {parameters[0] if parameters else 1})",
        "student_t": f"RealDistribution('t', {parameters[0] if parameters else 1})",
        "beta": f"RealDistribution('beta', [{params_str}])",
        "gamma": f"RealDistribution('gamma', [{params_str}])",
    }
    # For distributions not directly in RealDistribution, use scipy-like Sage constructs
    if distribution == "poisson":
        # Poisson is discrete; handle separately
        lam = parameters[0] if parameters else 1
        op_code = {
            "pdf": (
                f"float(exp(-{lam}) * {lam}**{x} / factorial(int({x})))"
                if x is not None else "0"
            ),
            "cdf": (
                f"float(sum(exp(-{lam}) * {lam}**k / factorial(k)"
                f" for k in range(int({x}) + 1)))"
                if x is not None else "0"
            ),
            "mean": f"float({lam})",
            "variance": f"float({lam})",
            "sample": f"[int(numpy_rng.poisson({lam})) for _ in range({n or 1})]",
        }
        if operation not in op_code:
            raise ToolError(f"Unknown operation '{operation}' for Poisson distribution")
        code = sage_prelude() + op_code.get(operation, "None") + "\n"
    elif distribution in dist_map:
        dist_expr = dist_map[distribution]
        # Only the normal distribution carries a location parameter here; for
        # every other distribution the shift is 0 and these read unchanged.
        shift = normal_mu if distribution == "normal" else 0.0
        shifted = None if x is None else f"({x}) - ({shift})"
        unshift = f"({shift}) + " if distribution == "normal" else ""
        op_code = {
            "pdf": f"float(_d.distribution_function({shifted}))" if x is not None else "None",
            "cdf": (
                f"float(_d.cum_distribution_function({shifted}))"
                if x is not None else "None"
            ),
            "quantile": (
                f"float({unshift}_d.cum_distribution_function_inv({x}))"
                if x is not None else "None"
            ),
            # mean/variance are computed analytically. They previously
            # returned float(_d.get_random_element()) and None respectively,
            # so "mean" reported a random draw from the distribution -- a
            # different wrong answer on every call -- and "variance" was
            # always null.
            "mean": f"float({_distribution_mean(distribution, parameters)})",
            "variance": f"float({_distribution_variance(distribution, parameters)})",
            "sample": f"[float(_d.get_random_element()) for _ in range({n or 1})]",
        }
        if operation not in op_code:
            raise ToolError(
                f"Unknown operation '{operation}'. "
                "Use: pdf, cdf, quantile, mean, variance, sample"
            )
        code = sage_prelude() + f"_d = {dist_expr}\n" + op_code[operation] + "\n"
    else:
        raise ToolError(
            f"Unknown distribution '{distribution}'. "
            "Use: normal, exponential, poisson, chi_squared, student_t, uniform, beta, gamma"
        )
    result = await evaluate_structured(session, code)
    return {"distribution": distribution, "operation": operation, "result": result}
