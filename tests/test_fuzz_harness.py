"""The fuzz target must run, and must be able to fail.

A fuzz harness is the easiest thing in a repository to let rot: nothing
imports it, CI may skip it on a path filter, and a target that crashes on
startup reports the same "no crashes found" as one that is working. Worse, a
target whose generator produces only unparseable input prints a clean result
forever -- which an earlier version of `fuzz/fuzz_validate.py` did, because
the byte that selects the denied name was being prepended to the source.

So: the harness is exercised here, on every unit run, and the oracles are
checked against inputs that must trip them.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "fuzz" / "fuzz_validate.py"


def _harness():
    spec = importlib.util.spec_from_file_location("fuzz_validate", TARGET)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["fuzz_validate"] = module
    spec.loader.exec_module(module)
    return module


def test_the_fuzz_target_exists_and_imports() -> None:
    assert TARGET.is_file(), "the fuzz target named by .clusterfuzzlite/build.sh is missing"
    assert _harness().DENIED, "the target fuzzes against an empty denied-name set"


def test_the_denied_set_comes_from_the_live_policy() -> None:
    """Hard-coding it would let a rule stop denying a name without the fuzzer
    noticing -- the target would keep passing on a weaker policy."""
    from sagemath_mcp.security import SECURITY_POLICY

    assert set(_harness().DENIED) == set(SECURITY_POLICY.forbidden_call_names)


def test_a_clean_input_is_accepted() -> None:
    """The counter-property. A harness that flagged everything would satisfy
    every check below while telling you nothing."""
    harness = _harness()
    harness.check(b"\x00" + b"1 + 1")


def test_the_read_oracle_fires_on_a_known_hole() -> None:
    """Simulate a policy that stopped refusing a name, and confirm the target
    reports it rather than passing."""
    harness = _harness()
    name = harness.DENIED[0]

    def always_valid(_code: str) -> None:
        return None

    harness.validate_code = always_valid
    with pytest.raises(AssertionError, match="accepted in a read position"):
        harness.check(b"\x00" + f"{name}(1)".encode())


def test_the_crash_oracle_fires_on_an_unexpected_exception() -> None:
    """A rule that raises `AttributeError` is a rule that is not being
    applied, and a caller catching only `SecurityViolation` would see it
    propagate. That must be a finding, not a pass."""
    harness = _harness()

    def boom(_code: str) -> None:
        raise AttributeError("no such attribute")

    harness.validate_code = boom
    with pytest.raises(AssertionError, match="not SecurityViolation"):
        harness.check(b"\x00" + b"1 + 1")


def test_the_campaign_refuses_to_report_clean_over_nothing() -> None:
    """The bug this file exists for. If the generator stops producing
    parseable programs, the campaign must fail rather than print a clean
    result over an empty run."""
    harness = _harness()
    harness.JUDGED = 0
    harness.check = lambda _data: None  # nothing is ever judged
    with pytest.raises(AssertionError, match="would mean nothing"):
        harness._local_campaign(5000)


def test_the_workflow_runs_the_target_on_the_python_we_ship() -> None:
    """The reason ClusterFuzzLite was removed the day it was added: its base
    image ships Python 3.11, this package requires >=3.12, and PEP 701 rewrote
    f-string parsing in 3.12. Fuzzing an AST policy on a different parser than
    the one we ship measures a configuration nobody runs -- and f-strings are
    exactly where this campaign's one false positive came from.

    So the workflow pins the version, and this fails if that pin drifts away
    from `requires-python`.
    """
    import tomllib

    workflow = (ROOT / ".github" / "workflows" / "fuzz.yml").read_text(encoding="utf-8")
    assert 'python-version: "3.12"' in workflow
    # Every target runs, and every file a target guards triggers the workflow.
    # A harness that exists but is not wired to the code it covers is the same
    # as no harness, and harder to notice.
    for target in sorted(ROOT.glob("fuzz/fuzz_*.py")):
        assert f"fuzz/{target.name}" in workflow, f"{target.name} is never run by CI"
    for guarded in ("security.py", "codegen.py", "_sage_worker.py"):
        assert guarded in workflow, f"a change to {guarded} would not trigger the fuzzers"

    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["requires-python"] == ">=3.12", (
        "the floor moved; the fuzz workflow still pins 3.12"
    )


def test_a_finding_replays_from_its_seed() -> None:
    """A fuzzer whose findings cannot be reproduced is a rumour generator."""
    harness = _harness()
    harness.JUDGED = 0
    harness._local_campaign(200, seed=7)
    first = harness.JUDGED
    harness.JUDGED = 0
    harness._local_campaign(200, seed=7)
    assert harness.JUDGED == first


def test_the_campaign_actually_parses_most_of_what_it_generates() -> None:
    """Judged-versus-generated is the honest measure of a generator. A ratio
    near zero means the campaign is fuzzing the parser, not the policy."""
    harness = _harness()
    harness.JUDGED = 0
    harness._local_campaign(2000, seed=1)
    assert harness.JUDGED > 2000 * 0.5, (
        f"only {harness.JUDGED}/2000 generated programs parsed; the campaign is "
        "measuring syntax errors rather than the policy"
    )
