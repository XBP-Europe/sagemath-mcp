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
    result_type: Literal["expression", "statement", "void"]
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


class SessionSnapshot(BaseModel):
    """Diagnostic snapshot stored inside the state resource."""

    session_id: str
    live: bool
    started_at: float
    last_used_at: float
    idle_seconds: float


class MonitoringSnapshot(BaseModel):
    """Aggregated performance and security metrics for Sage evaluations."""

    attempts: int
    successes: int
    failures: int
    security_failures: int
    avg_elapsed_ms: float
    max_elapsed_ms: float
    last_run_at: float | None = None
    last_error: str | None = None
    last_security_violation: str | None = None
    last_error_details: str | None = None


class DocumentationLink(BaseModel):
    """Pointer to external SageMath documentation."""

    title: str
    url: str
    slug: str
    description: str | None = None
