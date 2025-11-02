#!/usr/bin/env python3
"""Build source and wheel distributions with documentation included."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = PROJECT_ROOT / "dist"


def _run_build(cmd: list[str]) -> tuple[int, str]:
    proc = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True)
    output = "\n".join(part for part in (proc.stdout or "", proc.stderr or "") if part)
    return proc.returncode, output


def _ensure_build_backend() -> None:
    try:
        __import__("hatchling.build")
    except ModuleNotFoundError:
        print("Installing hatchling build backend...", file=sys.stderr)
        installers = (
            ["uv", "pip", "install", "hatchling>=1.26"],
            [sys.executable, "-m", "pip", "install", "hatchling>=1.26"],
        )
        last_error: str | None = None
        last_exc: Exception | None = None
        for cmd in installers:
            try:
                subprocess.run(cmd, check=True, text=True, capture_output=True)
                return
            except FileNotFoundError:
                continue
            except subprocess.CalledProcessError as exc:
                last_error = exc.stderr.decode(errors="ignore") if exc.stderr else str(exc)
                last_exc = exc
        message = last_error or "Unable to install hatchling"
        raise RuntimeError(message) from last_exc


def main() -> int:
    print("==> Preparing documented release build")
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    base_cmd = [
        sys.executable,
        "-m",
        "build",
        "--sdist",
        "--wheel",
        "--outdir",
        str(DIST_DIR),
    ]

    print("Running:", " ".join(base_cmd))
    code, output = _run_build(base_cmd)
    if code == 0:
        print("Artifacts written to", DIST_DIR)
        return 0

    if "ensurepip" in output:
        print(
            "Missing ensurepip support; retrying build without isolation...",
            file=sys.stderr,
        )
        try:
            _ensure_build_backend()
        except RuntimeError as exc:
            print(f"Failed to install build backend: {exc}", file=sys.stderr)
            return 1
        fallback_cmd = [*base_cmd, "--no-isolation"]
        print("Running:", " ".join(fallback_cmd))
        code, output = _run_build(fallback_cmd)
        if code == 0:
            print("Artifacts written to", DIST_DIR)
            return 0
        if output:
            sys.stderr.write(output + "\n")
        return code

    if output:
        sys.stderr.write(output + "\n")
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
