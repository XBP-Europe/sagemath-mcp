"""Every setting must be documented, and every documented setting must exist.

Ten of the twenty-four environment variables this server reads were
undocumented until 2026-09-21, and four of those turn parts of the security
policy off: `SAGEMATH_MCP_SECURITY_NAME_ALLOWLIST` disables deny-by-default,
`SAGEMATH_MCP_SECURITY_ALLOW_IMPORTS` re-enables imports. `CLAUDE.md` already
required security toggles to be documented; nothing enforced it.

The other direction matters too, and is how this was found: `USAGE.md` told
readers to adjust settings "as documented in `README.md`", and `README.md`
mentions no environment variable at all. A pointer at documentation that does
not exist is worse than silence, because it stops the reader looking.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
USAGE = (ROOT / "USAGE.md").read_text(encoding="utf-8")

#: The modules that read configuration from the environment.
_SOURCES = (
    "config.py",
    "security.py",
    "session.py",
    "server.py",
    "app.py",
    "auth.py",
)

_ENV = re.compile(r"SAGEMATH_MCP_[A-Z_]+")


def _settings_in_code() -> set[str]:
    found: set[str] = set()
    for name in _SOURCES:
        path = ROOT / "src" / "sagemath_mcp" / name
        if path.exists():
            found |= set(_ENV.findall(path.read_text(encoding="utf-8")))
    return found


def test_every_setting_is_documented() -> None:
    documented = set(_ENV.findall(USAGE))
    missing = sorted(_settings_in_code() - documented)
    assert not missing, (
        "these settings are read from the environment but appear nowhere in "
        "USAGE.md's configuration reference. A security toggle nobody "
        "documents is a switch an operator finds by reading source:\n  "
        + "\n  ".join(missing)
    )


def test_no_documented_setting_is_imaginary() -> None:
    """The converse. A row for a variable nothing reads is a promise the
    server does not keep."""
    in_code = _settings_in_code()
    # Only rows in the reference table, so prose examples elsewhere in the
    # manual are not mistaken for claims about a setting's existence.
    reference = USAGE[USAGE.index("## Configuration reference") :]
    reference = reference[: reference.index("## Troubleshooting Tips")]
    documented = set(_ENV.findall(reference))
    imaginary = sorted(documented - in_code)
    assert not imaginary, f"USAGE.md documents settings nothing reads: {imaginary}"


def test_the_security_toggles_are_marked_as_weakening() -> None:
    """Listing them is not enough. Each one moves away from the posture
    SECURITY.md describes, and the table has to say so where the reader is."""
    reference = USAGE[USAGE.index("## Configuration reference") :]
    assert "These weaken the policy" in reference
    for toggle in (
        "SAGEMATH_MCP_SECURITY_ENABLED",
        "SAGEMATH_MCP_SECURITY_NAME_ALLOWLIST",
        "SAGEMATH_MCP_SECURITY_ALLOW_IMPORTS",
    ):
        assert toggle in reference, f"{toggle} is missing from the security table"


def test_usage_does_not_send_readers_to_a_section_that_does_not_exist() -> None:
    """The bug that started this: USAGE.md pointed at `README.md` for the
    environment variables, and README.md has none."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    if not _ENV.search(readme):
        assert "as documented in `README.md`" not in USAGE, (
            "USAGE.md refers the reader to README.md for environment "
            "variables, and README.md documents none"
        )
