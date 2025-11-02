#!/usr/bin/env python3
"""Utility for bumping the project version."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from re import Pattern

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = PROJECT_ROOT / "pyproject.toml"
INIT_PATH = PROJECT_ROOT / "src" / "sagemath_mcp" / "__init__.py"

PYPROJECT_VERSION_PATTERN: Pattern[str] = re.compile(
    r'^(version\s*=\s*)"(?P<version>\d+\.\d+\.\d+)"\s*$', re.MULTILINE
)
INIT_VERSION_PATTERN: Pattern[str] = re.compile(
    r'^(\s*__version__\s*=\s*)"(?P<version>\d+\.\d+\.\d+)"\s*$', re.MULTILINE
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


def _write_version(path: Path, pattern: Pattern[str], new_version: str) -> None:
    content = path.read_text(encoding="utf-8")
    if not pattern.search(content):
        raise RuntimeError(f"Unable to locate version declaration in {path}")
    updated = pattern.sub(lambda m: f'{m.group(1)}"{new_version}"', content)
    path.write_text(updated, encoding="utf-8")


def bump_version(segment: str) -> Version:
    current_raw = _read_version(PYPROJECT_PATH, PYPROJECT_VERSION_PATTERN)
    current = Version.parse(current_raw)
    bumped = current.bump(segment)
    _write_version(PYPROJECT_PATH, PYPROJECT_VERSION_PATTERN, str(bumped))
    _write_version(INIT_PATH, INIT_VERSION_PATTERN, str(bumped))
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

    _write_version(PYPROJECT_PATH, PYPROJECT_VERSION_PATTERN, str(bumped))
    _write_version(INIT_PATH, INIT_VERSION_PATTERN, str(bumped))

    print(bumped)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
