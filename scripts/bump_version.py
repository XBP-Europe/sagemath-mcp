#!/usr/bin/env python3
"""Utility for bumping the project version."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from re import Pattern

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = PROJECT_ROOT / "pyproject.toml"
INIT_PATH = PROJECT_ROOT / "src" / "sagemath_mcp" / "__init__.py"
CHART_PATH = PROJECT_ROOT / "charts" / "sagemath-mcp" / "Chart.yaml"
SERVER_JSON_PATH = PROJECT_ROOT / "server.json"

PYPROJECT_VERSION_PATTERN: Pattern[str] = re.compile(
    r'^(version\s*=\s*)"(?P<version>\d+\.\d+\.\d+)"\s*$', re.MULTILINE
)
INIT_VERSION_PATTERN: Pattern[str] = re.compile(
    r'^(\s*__version__\s*=\s*)"(?P<version>\d+\.\d+\.\d+)"\s*$', re.MULTILINE
)
# The chart carries the version twice. Both were left behind by this script,
# so the chart silently drifted from the package at every release.
CHART_VERSION_PATTERN: Pattern[str] = re.compile(
    r"^(version:\s*)(?P<version>\d+\.\d+\.\d+)\s*$", re.MULTILINE
)
CHART_APP_VERSION_PATTERN: Pattern[str] = re.compile(
    r'^(appVersion:\s*)"(?P<version>\d+\.\d+\.\d+)"\s*$', re.MULTILINE
)


@dataclass(frozen=True)
class Version:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, raw: str) -> Version:
        parts = raw.strip().split(".")
        if len(parts) != 3:
            raise ValueError(f"Expected semantic version (major.minor.patch), got '{raw}'")
        try:
            major, minor, patch = (int(part) for part in parts)
        except ValueError as exc:
            raise ValueError(f"Version components must be integers, got '{raw}'") from exc
        return cls(major, minor, patch)

    def bump(self, segment: str) -> Version:
        if segment == "major":
            return Version(self.major + 1, 0, 0)
        if segment == "minor":
            return Version(self.major, self.minor + 1, 0)
        if segment == "patch":
            return Version(self.major, self.minor, self.patch + 1)
        raise ValueError(f"Unsupported segment '{segment}'. Use major, minor, or patch.")

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


def _read_version(path: Path, pattern: Pattern[str]) -> str:
    content = path.read_text(encoding="utf-8")
    match = pattern.search(content)
    if not match:
        raise RuntimeError(f"Unable to find version in {path}")
    return match.group("version")


def _write_version(
    path: Path, pattern: Pattern[str], new_version: str, *, quoted: bool = True
) -> None:
    content = path.read_text(encoding="utf-8")
    if not pattern.search(content):
        raise RuntimeError(f"Unable to locate version declaration in {path}")
    replacement = f'"{new_version}"' if quoted else new_version
    updated = pattern.sub(lambda m: f"{m.group(1)}{replacement}", content)
    path.write_text(updated, encoding="utf-8")


def _write_server_json(new_version: str) -> None:
    """Update both version fields in the MCP registry manifest.

    The release workflow rewrites these in its own temporary checkout, so the
    version committed by the bump pull request stayed stale -- the manifest in
    git disagreed with the package it describes.
    """
    if not SERVER_JSON_PATH.exists():
        return
    manifest = json.loads(SERVER_JSON_PATH.read_text(encoding="utf-8"))
    manifest["version"] = new_version
    for package in manifest.get("packages", []):
        package["version"] = new_version
    SERVER_JSON_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def _write_all(new_version: str) -> None:
    """Update every file that carries the version.

    Keep this list complete: the Helm chart was missing, so it stayed on the
    previous version through every release, and server.json had the same bug.
    """
    _write_version(PYPROJECT_PATH, PYPROJECT_VERSION_PATTERN, new_version)
    _write_version(INIT_PATH, INIT_VERSION_PATTERN, new_version)
    _write_version(CHART_PATH, CHART_VERSION_PATTERN, new_version, quoted=False)
    _write_version(CHART_PATH, CHART_APP_VERSION_PATTERN, new_version)
    _write_server_json(new_version)


def bump_version(segment: str) -> Version:
    current_raw = _read_version(PYPROJECT_PATH, PYPROJECT_VERSION_PATTERN)
    current = Version.parse(current_raw)
    bumped = current.bump(segment)
    _write_all(str(bumped))
    return bumped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bump the project version.")
    parser.add_argument(
        "--segment",
        choices=("major", "minor", "patch"),
        default="patch",
        help="Version segment to increment (default: patch).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the new version without modifying files.",
    )
    args = parser.parse_args(argv)

    current_raw = _read_version(PYPROJECT_PATH, PYPROJECT_VERSION_PATTERN)
    current = Version.parse(current_raw)
    bumped = current.bump(args.segment)

    if args.dry_run:
        print(bumped)
        return 0

    _write_all(str(bumped))

    print(bumped)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
