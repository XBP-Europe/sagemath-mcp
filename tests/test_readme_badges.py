"""The README's badges must state things that are true of this repository.

Badges rot silently: nothing breaks when one goes stale, and a reader has no way
to tell. The FastMCP badge advertised 3.2 for two minor releases while
pyproject.toml required >=3.4.7, and nobody noticed because a badge has no test.

So each version badge is checked against the file that actually decides it, and
the coverage badge against the threshold CI enforces. A badge that cannot be
tied back to something in the repository does not belong in this file -- and,
arguably, not in the README either.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _badge_value(label: str) -> str:
    """The value segment of a static shields.io badge, URL-decoded enough."""
    match = re.search(rf"!\[[^\]]*\]\(https://img\.shields\.io/badge/{label}-([^-]+)-", README)
    assert match, f"no static badge found for {label!r}"
    return match.group(1).replace("%2B", "+").replace("%25", "%").replace("%20", " ")


def test_fastmcp_badge_matches_the_declared_dependency() -> None:
    """The badge said 3.2 while the floor was 3.4.7."""
    declared = [d for d in PYPROJECT["project"]["dependencies"] if d.startswith("fastmcp")]
    assert declared, "fastmcp is no longer a declared dependency"
    floor = re.search(r"(\d+)\.(\d+)", declared[0])
    assert floor, f"cannot read a version floor from {declared[0]!r}"

    badge = _badge_value("FastMCP").rstrip("+")
    assert badge == f"{floor.group(1)}.{floor.group(2)}", (
        f"README advertises FastMCP {badge} but pyproject requires {declared[0]}"
    )


def test_python_badge_matches_requires_python() -> None:
    required = PYPROJECT["project"]["requires-python"]
    badge = _badge_value("python").rstrip("+")
    assert badge in required, f"README advertises python {badge}, pyproject says {required}"


def test_sagemath_badge_matches_the_container_base_image() -> None:
    """The runtime the project is actually built and tested against."""
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    image = re.search(r"^FROM\s+sagemath/sagemath:(\S+)", dockerfile, re.M)
    assert image, "the Dockerfile no longer starts from a pinned sagemath image"
    assert _badge_value("SageMath") == image.group(1), (
        f"README advertises SageMath {_badge_value('SageMath')} but the image is "
        f"{image.group(1)}"
    )


def test_coverage_badge_is_backed_by_a_ci_gate() -> None:
    """A coverage number nobody enforces is a number that drifts."""
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    gate = re.search(r"--cov-fail-under=(\d+)", ci)
    assert gate, "the CI unit job does not enforce a coverage floor"

    badge = _badge_value("coverage").rstrip("%")
    assert badge == gate.group(1), (
        f"README claims {badge}% coverage but CI only enforces {gate.group(1)}%"
    )


@pytest.mark.parametrize(
    "label,path",
    [
        ("Dependabot", ".github/dependabot.yml"),
        ("Signed", ".github/workflows/release.yml"),
    ],
)
def test_badges_that_point_at_a_file_point_at_one_that_exists(label: str, path: str) -> None:
    assert (ROOT / path).exists(), f"the {label} badge links to {path}, which is missing"


def test_the_signed_badge_means_the_release_actually_signs() -> None:
    release = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "cosign sign" in release, "the badge claims signed images but nothing signs them"


def test_the_registry_badge_matches_a_real_listing() -> None:
    """Check the registry, not the workflow.

    This badge was removed once for claiming a listing that did not exist: the
    test then asserted only that release.yml mentions an mcp-registry job, which
    a job that had never run satisfied perfectly. The v0.5.0 release published
    for real, so the badge is back -- verified against the registry itself, and
    skipped rather than failed when the network is unavailable.
    """
    import json
    import urllib.error
    import urllib.request

    if "MCP%20Registry" not in README:
        pytest.skip("no registry badge to verify")

    name = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))["name"]
    url = "https://registry.modelcontextprotocol.io/v0/servers?search=sagemath"
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            servers = json.loads(response.read())["servers"]
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        pytest.skip(f"registry unreachable: {exc}")

    listed = {entry["server"]["name"] for entry in servers}
    assert name in listed, (
        f"the README claims an MCP registry listing, but {name} is not in the "
        f"registry (found {sorted(listed)})"
    )
