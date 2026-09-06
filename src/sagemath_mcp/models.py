"""Pydantic models exposed through the MCP interface."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class EvaluateRequest(BaseModel):
    """Input payload for executing Sage code."""

    code: str = Field(..., description="SageMath code snippet to execute.")
    capture_stdout: bool = Field(
        default=True,
        description="Capture stdout emitted by the Sage interpreter.",
    )
    want_latex: bool = Field(
        default=False,
        description="Attempt to convert expression results to LaTeX.",
    )
    timeout: float | None = Field(
        default=None,
        description="Override the evaluation timeout (seconds).",
        ge=0.1,
    )


class EvaluateResult(BaseModel):
    result_type: Literal["expression", "statement"]
    result: str | None = Field(
        default=None,
        description="String representation of the expression result if available.",
    )
    latex: str | None = Field(
        default=None,
        description="LaTeX serialization of the result when requested and supported.",
    )
    stdout: str = Field(
        default="",
        description="Captured stdout emitted during execution.",
    )
    elapsed_ms: float = Field(
        ..., description="Wall-clock execution time in milliseconds."
    )


class ResetResponse(BaseModel):
    message: str = Field(default="Session cleared")


class WorkspaceHandle(BaseModel):
    """A started workspace plus the portable handle that addresses it.

    The handle is a server-issued, unguessable token. Passed back as a tool's
    ``session`` argument it reaches this exact workspace independently of the
    transport-level MCP session id -- so a client keeps its state across a
    reconnect, or a transport that hands out a fresh session id per call (which
    is what fastmcp 4 did, and where relying on the transport id alone lost
    state). Holding the token is what grants access, so it is unguessable and
    must be treated as a secret; it is never logged or exposed through the
    monitoring or session resources.
    """

    message: str = Field(description="Human-readable confirmation.")
    workspace_token: str = Field(
        description="Opaque handle for this workspace. Pass it as the 'session' "
        "argument of later tool calls to reach the same state regardless of the "
        "transport session. Treat it as a secret."
    )
    name: str = Field(description="The workspace name this handle was opened for.")


class SessionSnapshot(BaseModel):
    """Diagnostic snapshot stored inside the state resource."""

    session_id: str
    live: bool
    started_at: float
    last_used_at: float
    idle_seconds: float


class MonitoringSnapshot(BaseModel):
    """Aggregated performance and security metrics for Sage evaluations.

    Deliberately carries no per-client free text (error message, rejected code,
    stdout). Those fields exist on the internal `EvaluationMetrics` for
    server-side logging, but `_METRICS` is process-global, so emitting them
    through the unscoped monitoring resource would hand one client another
    client's inputs and outputs. See REVIEW_ACTIONS item 58.
    """

    attempts: int
    successes: int
    failures: int
    security_failures: int
    avg_elapsed_ms: float
    max_elapsed_ms: float
    last_run_at: float | None = None


class VerifyClaimResult(BaseModel):
    """Outcome of independently re-checking a stated mathematical claim.

    The honesty rules live in the vocabulary. ``proved`` and ``refuted`` are
    exact decisions; ``supported`` means the evidence is consistent with the
    claim without deciding it, and always says what that evidence was;
    ``undecided`` means the ladder ran out. A prover answering False is never
    reported as ``refuted`` -- refutation requires an exhibited counterexample
    or an exact decision.
    """

    claim: str = Field(description="The claim that was checked, whitespace-folded.")
    verdict: Literal["proved", "refuted", "supported", "undecided"] = Field(
        description="proved/refuted are exact; supported is evidence short of proof; "
        "undecided means every rung of the ladder was inconclusive."
    )
    method: str | None = Field(
        default=None,
        description="The rung that decided: exact_comparison, symbolic_prover, "
        "exact_difference, exact_algebraic, certified_interval, numeric_sampling, "
        "float_comparison (operands were machine floats, so the result is only "
        "supported, never exact) or exhausted.",
    )
    evidence: str | None = Field(
        default=None,
        description="What the deciding rung actually established, including the "
        "counterexample for a sampled refutation.",
    )
    samples: int | None = Field(
        default=None,
        description="Number of sample points supporting a numeric-sampling verdict.",
    )
    precision_bits: int | None = Field(
        default=None,
        description="Interval-arithmetic precision behind a numeric verdict.",
    )


class DocumentationLink(BaseModel):
    """Pointer to external SageMath documentation."""

    title: str
    url: str
    slug: str
    description: str | None = None
