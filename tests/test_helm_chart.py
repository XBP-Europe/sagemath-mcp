"""The Helm chart must enforce what the documentation claims for it.

`SECURITY.md` describes one container boundary covering both the Compose
deployment and the chart. A 2026-09-19 security review found the chart
materially weaker than Compose on three counts, and the docs weaker still --
`README.md` credited the chart with a control Kubernetes does not offer in a
pod spec at all.

The gap is easy to reintroduce, because Docker supplies several of these
defaults implicitly and Kubernetes supplies none of them. So this renders the
chart with `helm template` and reads the result, rather than grepping the
template source: what matters is what lands in the cluster.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "charts" / "sagemath-mcp"

pytestmark = pytest.mark.skipif(
    shutil.which("helm") is None, reason="helm is not on PATH"
)


def _render(*set_values: str) -> list[dict]:
    """`helm template`, parsed. Renders the chart exactly as an operator would."""
    argv = ["helm", "template", "test-release", str(CHART)]
    for value in set_values:
        argv += ["--set", value]
    result = subprocess.run(argv, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        pytest.fail(f"helm template failed:\n{result.stdout[-2000:]}\n{result.stderr[-2000:]}")
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


@pytest.fixture(scope="module")
def deployment() -> dict:
    for doc in _render():
        if doc.get("kind") == "Deployment":
            return doc
    pytest.fail("the chart rendered no Deployment")


def test_the_pod_runs_under_the_default_seccomp_profile(deployment: dict) -> None:
    """Docker applies its default seccomp profile without being asked.
    Kubernetes does not: absent `seccompProfile`, the pod runs **Unconfined**,
    with the whole syscall table exposed to a process whose job is executing
    model-written code. For this workload it is the most load-bearing
    kernel-surface control there is, and it was the one the chart omitted.
    """
    pod = deployment["spec"]["template"]["spec"]
    profile = (pod.get("securityContext") or {}).get("seccompProfile")
    assert profile, "the pod sets no seccompProfile, so Kubernetes runs it Unconfined"
    assert profile.get("type") == "RuntimeDefault", profile


def test_no_kubernetes_api_token_is_mounted(deployment: dict) -> None:
    """`SECURITY.md` says plainly that the AST policy has been bypassed and
    repaired repeatedly, and tells operators not to mount sensitive paths into
    the worker. Without `automountServiceAccountToken: false` the pod gets the
    namespace's default ServiceAccount token projected into it, and
    `readOnlyRootFilesystem` does not stop anything *reading* it. Nothing in
    this server talks to the API server."""
    pod = deployment["spec"]["template"]["spec"]
    assert pod.get("automountServiceAccountToken") is False, (
        "the code-execution container is handed a Kubernetes API credential"
    )


def test_the_bearer_token_can_come_from_a_secret(deployment: dict) -> None:
    """The chart is the only shipped deployment that puts the server on a
    network, so it is the one that most needs the token -- and it had no
    first-class way to set it. The path an operator would find, `env`, renders
    a literal `value:`, putting the shared secret into the Deployment spec,
    `kubectl describe`, and the release Secret."""
    rendered = _render(
        "auth.existingSecret=sagemath-mcp-token",
        "auth.secretKey=token",
    )
    deployment_doc = next(d for d in rendered if d.get("kind") == "Deployment")
    container = deployment_doc["spec"]["template"]["spec"]["containers"][0]
    entries = {entry["name"]: entry for entry in container.get("env", [])}
    assert "SAGEMATH_MCP_HTTP_AUTH_TOKEN" in entries, (
        "setting auth.existingSecret did not wire the token into the container"
    )
    source = entries["SAGEMATH_MCP_HTTP_AUTH_TOKEN"]
    assert "value" not in source, "the token was rendered as a literal"
    ref = source["valueFrom"]["secretKeyRef"]
    assert ref == {"name": "sagemath-mcp-token", "key": "token"}, ref


def test_the_token_is_absent_unless_configured(deployment: dict) -> None:
    """No auth is the supported default for a local run; the chart must not
    invent an empty token that fails every request."""
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    names = {entry["name"] for entry in container.get("env", [])}
    assert "SAGEMATH_MCP_HTTP_AUTH_TOKEN" not in names


def test_the_readme_does_not_credit_the_chart_with_a_fork_ceiling() -> None:
    """Kubernetes has no per-pod PID limit in the pod spec -- it is a kubelet
    setting (`podPidsLimit`) an operator applies to the node. `SECURITY.md` gets
    this right ("Compose supplies PID/memory limits; Helm supplies CPU/memory
    limits"); the README claimed fork ceilings for a paragraph covering both.
    The honest fix is the sentence, not an invented chart field.
    """
    # Whitespace-collapsed: the claim wraps across a line, and searching for
    # the unwrapped phrase made an earlier version of this test pass vacuously.
    readme = " ".join((ROOT / "README.md").read_text(encoding="utf-8").split())
    window = readme[readme.find("## Security") :]
    assert "fork / memory ceilings" not in window, (
        "the README still credits both deployments with a fork ceiling; the "
        "chart cannot set one"
    )


def test_the_chart_keeps_what_it_already_had(deployment: dict) -> None:
    """A regression net for the controls that were already right, since this
    change edits the same blocks."""
    pod = deployment["spec"]["template"]["spec"]
    container = pod["containers"][0]
    assert pod["securityContext"]["runAsNonRoot"] is True
    assert pod["securityContext"]["runAsUser"] == 1001
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert container["securityContext"]["allowPrivilegeEscalation"] is False
    assert container["securityContext"]["capabilities"]["drop"] == ["ALL"]


def test_the_rendered_chart_is_valid_kubernetes_yaml() -> None:
    """`helm template` will happily emit something the API server rejects."""
    docs = _render()
    kinds = {doc["kind"] for doc in docs}
    assert {"Deployment", "Service"} <= kinds, kinds
    for doc in docs:
        assert doc.get("apiVersion"), json.dumps(doc)[:200]
