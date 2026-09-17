"""The published sdist must build a working wheel.

Nothing used to check this. CI built the wheel from the *repository*, where
`src/` exists, so every release shipped an sdist that could not be built from.
conda-forge found it, because conda-forge always builds from the sdist:

    FileNotFoundError: Forced include not found: $SRC_DIR/src/sagemath_mcp/py.typed

The cause was `packages = ["src/sagemath_mcp"]` on `[tool.hatch.build]`, which
applies to every target. On the sdist it rewrote `src/sagemath_mcp` to
`sagemath_mcp`, so the sdist no longer matched the `src/...` paths in
`pyproject.toml`. With the wheel's `force-include` it failed outright; without
it, hatchling found no package at `src/sagemath_mcp` and silently produced a
wheel containing **only `.dist-info`** -- no code at all, which is the worse of
the two failures because it installs.

So this test does the one thing that catches both: build the sdist, then build a
wheel *from the extracted sdist*, and look inside. Anyone who installs with
`pip install --no-binary :all:`, packages for a distribution, or reviews the
conda-forge recipe takes this path.
"""

from __future__ import annotations

import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Both are dev extras precisely so this runs rather than skips: a guard that
# skips in CI is not a guard. See the `dev` extra in pyproject.toml.
pytest.importorskip("build", reason="the `build` frontend is a dev extra")
pytest.importorskip("hatchling", reason="the build backend is a dev extra")


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """`python -m build` from the repository: sdist, then wheel from that sdist.

    `--no-isolation` keeps it offline and fast; the backend is already present.
    Without `--sdist`/`--wheel` the frontend does exactly the sequence this test
    is about -- it builds the sdist and then builds the wheel from it.
    """
    out = tmp_path_factory.mktemp("dist")
    result = subprocess.run(
        [sys.executable, "-m", "build", "--no-isolation", "--outdir", str(out), str(ROOT)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(
            "building the wheel from the sdist failed, which is how the package "
            f"reaches conda-forge and `pip install --no-binary :all:`:\n"
            f"{result.stdout[-3000:]}\n{result.stderr[-3000:]}"
        )
    sdists = list(out.glob("*.tar.gz"))
    wheels = list(out.glob("*.whl"))
    assert len(sdists) == 1 and len(wheels) == 1, (sdists, wheels)
    return sdists[0], wheels[0]


def test_the_sdist_keeps_the_source_layout(built: tuple[Path, Path]) -> None:
    """`src/` must stay `src/`, or the sdist stops matching `pyproject.toml`.

    This is the property that makes the sdist round-trip. A rewritten layout
    builds fine in the repository and fails only for whoever builds from the
    sdist, which is nobody in CI and everybody downstream.
    """
    sdist, _ = built
    with tarfile.open(sdist) as archive:
        names = archive.getnames()
    root = names[0].split("/")[0]
    assert f"{root}/src/sagemath_mcp/server.py" in names, (
        "the sdist no longer keeps the package under src/; pyproject.toml's "
        "src/... paths will not resolve when building from it"
    )
    assert f"{root}/src/sagemath_mcp/py.typed" in names


def test_the_wheel_built_from_the_sdist_contains_the_package(
    built: tuple[Path, Path],
) -> None:
    """The failure that installs cleanly and does nothing.

    An empty wheel is valid, installable, and imports as ModuleNotFoundError at
    run time. Counting the modules is what distinguishes it from a real build.
    """
    _, wheel = built
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
    modules = [n for n in names if n.startswith("sagemath_mcp/") and n.endswith(".py")]
    assert len(modules) >= 20, f"the wheel has only {len(modules)} modules: {modules}"
    for required in ("sagemath_mcp/server.py", "sagemath_mcp/security.py"):
        assert required in names, f"{required} is missing from the wheel"


def test_the_typing_marker_survives_the_round_trip(built: tuple[Path, Path]) -> None:
    """`py.typed` is what tells a type checker the package is typed at all, and
    it is the file whose force-include broke the sdist build in the first
    place."""
    _, wheel = built
    with zipfile.ZipFile(wheel) as archive:
        assert "sagemath_mcp/py.typed" in archive.namelist()


def test_the_console_script_is_declared(built: tuple[Path, Path]) -> None:
    """A wheel with no entry point installs and leaves `sagemath-mcp` missing
    from PATH, which is the same class of silent failure."""
    _, wheel = built
    with zipfile.ZipFile(wheel) as archive:
        entry_points = next(
            (n for n in archive.namelist() if n.endswith("/entry_points.txt")), None
        )
        assert entry_points, "the wheel declares no entry points"
        content = archive.read(entry_points).decode()
    assert "sagemath-mcp = sagemath_mcp.server:main" in content
