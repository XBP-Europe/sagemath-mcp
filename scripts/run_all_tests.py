"""Run local and Sage-backed test suites."""

from __future__ import annotations

import subprocess
import sys


def run(cmd: list[str]) -> int:
    print("→", " ".join(cmd), flush=True)
    return subprocess.call(cmd)


def main() -> int:
    local = run(["uv", "run", "pytest"])
    docker = run(
        [
            "docker",
            "exec",
            "sage-mcp",
            "bash",
            "-lc",
            "cd /workspace && sage -python -m pytest",
        ]
    )
    if local != 0 or docker != 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
