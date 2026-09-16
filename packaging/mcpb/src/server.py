"""Entry point for the MCPB bundle.

The host runs this with `uv run`, which installs `sagemath-mcp[passagemath]`
from the bundle's `pyproject.toml` first. All this file does is hand over to the
server's own CLI with no arguments, which is stdio -- the transport a desktop
host speaks.
"""

from sagemath_mcp.server import main

if __name__ == "__main__":
    main([])
