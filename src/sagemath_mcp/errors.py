"""The errors a Sage worker session raises."""

from __future__ import annotations


class SageProcessError(RuntimeError):
    """Raised when the underlying Sage process terminates unexpectedly."""


class SageEvaluationError(RuntimeError):
    """Raised when Sage returns an execution error."""

    def __init__(self, message: str, *, error_type: str, stdout: str, traceback: str):
        super().__init__(message)
        self.error_type = error_type
        self.stdout = stdout
        self.traceback = traceback
