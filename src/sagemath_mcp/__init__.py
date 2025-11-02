"""SageMath MCP server package."""

from importlib.metadata import PackageNotFoundError, version

try:  # pragma: no cover - executed during packaging only
    __version__ = version("sagemath-mcp")
except PackageNotFoundError:  # pragma: no cover - local dev fallback
    __version__ = "0.1.0"

__all__ = ["__version__"]
