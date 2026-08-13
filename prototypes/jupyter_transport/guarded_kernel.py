"""A SageMath IPython kernel that enforces the project's AST policy.

Stock ipykernel executes whatever arrives on its shell socket. That is fine for
a notebook the user drives, and unacceptable here: the AST validator is this
project's main differentiator, and a Jupyter transport would otherwise reduce it
to an advisory client-side check.

Validating in ``do_execute`` means every execute_request is checked no matter
which client sent it, closing the socket bypass that a client-side check leaves
open.

Launched as:
    sage -python -m guarded_kernel -f {connection_file}
"""

from __future__ import annotations

import ast

from ipykernel.ipkernel import IPythonKernel
from ipykernel.kernelapp import IPKernelApp

from sagemath_mcp.security import SECURITY_POLICY, validate_module


class GuardedSageKernel(IPythonKernel):
    """IPython kernel that refuses code the security policy rejects."""

    implementation = "sagemath-mcp-guarded"
    implementation_version = "0.1.0"

    def _validate(self, code: str) -> dict | None:
        """Return an error reply if *code* violates policy, else None."""
        try:
            module = ast.parse(code, mode="exec", type_comments=True)
            validate_module(module, code=code, policy=SECURITY_POLICY)
        except SyntaxError as exc:
            return {
                "status": "error",
                "ename": "SyntaxError",
                "evalue": str(exc),
                "traceback": [f"SyntaxError: {exc}"],
                "execution_count": self.execution_count,
            }
        except Exception as exc:
            return {
                "status": "error",
                "ename": type(exc).__name__,
                "evalue": str(exc),
                "traceback": [f"{type(exc).__name__}: {exc}"],
                "execution_count": self.execution_count,
            }
        return None

    async def do_execute(  # type: ignore[override]
        self,
        code,
        silent,
        store_history=True,
        user_expressions=None,
        allow_stdin=False,
        **kwargs,
    ):
        rejection = self._validate(code)
        if rejection is not None:
            return rejection
        return await super().do_execute(
            code,
            silent,
            store_history=store_history,
            user_expressions=user_expressions,
            allow_stdin=allow_stdin,
            **kwargs,
        )


if __name__ == "__main__":
    IPKernelApp.launch_instance(kernel_class=GuardedSageKernel)
