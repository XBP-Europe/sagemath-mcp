"""Drive Claude, Gemini and Codex through tool-forcing math questions.

Each case is checked twice over:

1. The CLI's answer must contain the value SageMath computes.
2. The proxy's wire log must show the expected tool actually being called, and
   returning without error.

The second check is the point. Grepping the answer alone cannot tell a working
MCP integration apart from a model that answered from memory, which is why the
questions here are also chosen to be impractical to answer without a computer
algebra system.

    python -m tests.cli_integration.run_extended --cli all
    python -m tests.cli_integration.run_extended --cli codex --case ext-nt-next-prime
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .extended_cases import EXTENDED_CASES, ToolForcingCase
from .runner import run_claude, run_codex, run_gemini

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROXY = PROJECT_ROOT / "tests" / "cli_integration" / "mcp_proxy.py"
SERVER_NAME = "sagemath-clitest"

# The real server, reached through the dev container so Sage is genuine.
REAL_SERVER = ["docker", "exec", "-i", "sage-mcp", "sage", "-python", "-m", "sagemath_mcp.server"]


@dataclass
class CaseResult:
    cli: str
    case_id: str
    status: str  # PASS | WRONG_ANSWER | DODGED | NO_TOOL_CALL | TOOL_ERROR | TIMEOUT | ERROR
    detail: str
    tools_called: list[str]
    elapsed: float


def proxy_command(log_path: Path) -> list[str]:
    return [sys.executable, str(PROXY), "--log", str(log_path), "--", *REAL_SERVER]


# --------------------------------------------------------------------------
# Per-CLI registration. Each CLI has its own syntax; none of them is hard.
# --------------------------------------------------------------------------
def register(cli: str, log_path: Path) -> None:
    cmd = proxy_command(log_path)
    unregister(cli)
    if cli == "claude":
        args = ["claude", "mcp", "add", SERVER_NAME, "--", *cmd]
    elif cli == "gemini":
        args = ["gemini", "mcp", "add", SERVER_NAME, *cmd]
    elif cli == "codex":
        args = ["codex", "mcp", "add", SERVER_NAME, "--", *cmd]
    else:
        raise ValueError(cli)
    subprocess.run(args, cwd=str(PROJECT_ROOT), capture_output=True, text=True, check=True)


def unregister(cli: str) -> None:
    args = {
        "claude": ["claude", "mcp", "remove", SERVER_NAME],
        "gemini": ["gemini", "mcp", "remove", SERVER_NAME],
        "codex": ["codex", "mcp", "remove", SERVER_NAME],
    }[cli]
    subprocess.run(args, cwd=str(PROJECT_ROOT), capture_output=True, text=True)


# A model inventing an argument is model behaviour, not a server fault: the
# server rejects it with a schema validation error and the model retries. Gemini
# does exactly this (`wait_for_previous` on evaluate_sage) and then answers
# correctly, which used to fail the case. A genuine server error -- a security
# violation, a dead worker, a timeout -- must still fail it.
_CLIENT_FAULT_MARKERS = (
    "unexpected keyword argument",
    "validation error",
    "field required",
    "input should be",
)


# The other kind of error that is not a server fault: the mathematics the model
# asked for did not work. Sage says so, the model tries something else, and the
# answer is right -- which is a *correct* integration, and the shape every real
# session has. Watching Claude work the Bose-Einstein integral: it asked for the
# symbolic form first, got back an unevaluated `limit(...)` that `N()` cannot
# reduce, and switched to `numerical_integral` -- exactly what a person does.
#
# These stay narrow on purpose, and none of them can be produced by this
# server's own policy: a refusal, a dead worker or a timeout is still fatal
# below, whatever the model did afterwards.
_MATHEMATICS_FAULT_MARKERS = (
    "cannot evaluate symbolic expression numerically",
    "unable to simplify to float approximation",
    "appears to have no zero on the interval",
    "brent's method failed",
    "integral is divergent",
    # Qualified, because Sage always qualifies it -- `rational division by
    # zero`, `symbolic division by zero`, `power::eval(): division by zero`.
    # The bare phrase quoted no subsystem, so it matched anything containing it,
    # and it was the one entry here that could have covered a server defect.
    "rational division by zero",
    "symbolic division by zero",
    "eval(): division by zero",
    # Maxima asking for an assumption, which is a question rather than a failure.
    "positive, negative or zero",
)


def _is_client_fault(preview: str) -> bool:
    lowered = preview.lower()
    return any(marker in lowered for marker in _CLIENT_FAULT_MARKERS)


def _is_mathematics_fault(preview: str) -> bool:
    lowered = preview.lower()
    return any(marker in lowered for marker in _MATHEMATICS_FAULT_MARKERS)


def read_wire_log(
    log_path: Path,
) -> tuple[list[str], dict[int, str], list[str], list[str]]:
    """Return (tools called, ids the SERVER failed, tools that SUCCEEDED).

    Calls the model malformed are excluded from the failures: they say nothing
    about the server. So are calls whose *mathematics* Sage rejected -- a
    divergent integral, a bracket with no sign change -- because exploring and
    retrying is what a session looks like, not a defect. What remains in the
    second value is this server's own failures: a refusal, a dead worker, a
    timeout, an internal error.

    Excluding them is not enough on its own -- the tool still appeared in the
    call list, so a case could pass on a malformed call that failed plus a
    plausible-looking answer, with no successful tool call anywhere. The third
    value is what the assertions actually need. The fourth carries the errors
    that *were* tolerated, so a run that took four attempts to get there does not
    read exactly like a clean one.
    """
    tools: list[str] = []
    succeeded: list[str] = []
    tolerated: list[str] = []
    # id -> what the server said. Kept, not counted: "the server returned
    # isError" names no cause, and every diagnosis then needs the run repeated
    # with the log held on to.
    errored: dict[int, str] = {}
    call_ids: dict[int, str] = {}
    if not log_path.exists():
        return tools, errored, succeeded, tolerated
    for line in log_path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("kind") == "tool_call":
            name = record.get("tool")
            if name:
                tools.append(name)
                if record.get("id") is not None:
                    call_ids[record["id"]] = name
        elif record.get("kind") == "response":
            name = call_ids.get(record.get("id"))
            if name is None:
                continue
            if not record.get("is_error"):
                succeeded.append(name)
            else:
                preview = " ".join(
                    str(record.get(field) or "") for field in ("preview", "error")
                )
                if _is_mathematics_fault(preview):
                    # Not a server fault, and not nothing either: a PASS that
                    # took four attempts should not read like a clean one.
                    tolerated.append(preview.strip()[:80])
                elif not _is_client_fault(preview):
                    errored[record["id"]] = preview
    return tools, errored, succeeded, tolerated


def normalise(text: str) -> str:
    """Strip separators so 1,844,349,560 matches 1844349560."""
    return text.replace(",", "").replace(" ", "").replace("_", "").lower()


def evaluate(case: ToolForcingCase, output: str, log_path: Path, elapsed: float,
             cli: str) -> CaseResult:
    tools, errored, succeeded, tolerated = read_wire_log(log_path)
    relevant = [t for t in tools if t in case.accepted_tools]
    # An accepted tool that was CALLED proves nothing; one that answered does.
    relevant_ok = [t for t in succeeded if t in case.accepted_tools]

    if not tools:
        return CaseResult(cli, case.id, "NO_TOOL_CALL",
                          "the CLI answered without calling any MCP tool", tools, elapsed)
    if not relevant:
        return CaseResult(cli, case.id, "NO_TOOL_CALL",
                          f"called {sorted(set(tools))}, none of {case.accepted_tools}",
                          tools, elapsed)
    if errored:
        first = next(iter(errored.values())).replace("\\n", " ")[:240]
        return CaseResult(cli, case.id, "TOOL_ERROR",
                          f"the server returned isError: {first}", tools, elapsed)
    if not relevant_ok:
        return CaseResult(
            cli, case.id, "NO_TOOL_CALL",
            f"every call to {sorted(set(relevant))} failed; no tool actually answered",
            tools, elapsed)

    flat = normalise(output)
    for answer in case.expected_answers:
        if normalise(answer) in flat:
            detail = f"matched {answer!r}"
            if tolerated:
                detail += f" ({len(tolerated)} tolerated: {tolerated[0]!r})"
            return CaseResult(cli, case.id, "PASS", detail, tools, elapsed)

    tail = output.strip()[-160:].replace("\n", " ")
    # Same failure, different diagnosis: a model that refused is not a model that
    # computed the wrong number, and the two want different fixes -- one is a
    # prompt or a permission, the other is the server.
    lowered = output.lower()
    if any(marker.lower() in lowered for marker in case.forbidden):
        return CaseResult(cli, case.id, "DODGED",
                          f"answer declined rather than computed; tail: {tail!r}",
                          tools, elapsed)
    return CaseResult(cli, case.id, "WRONG_ANSWER",
                      f"expected one of {case.expected_answers}; tail: {tail!r}",
                      tools, elapsed)


def _invoke(cli: str, prompt: str, timeout: int) -> tuple[str, float]:
    """Call one CLI with the flags it needs to actually use MCP tools."""
    if cli == "claude":
        return run_claude(prompt, timeout, allowed_tools=f"mcp__{SERVER_NAME}")
    if cli == "gemini":
        return run_gemini(prompt, timeout, auto_approve=True)
    return run_codex(prompt, timeout)


def run_case(cli: str, case: ToolForcingCase, log_path: Path) -> CaseResult:
    log_path.write_text("", encoding="utf-8")  # isolate this case's traffic
    try:
        output, elapsed = _invoke(cli, case.prompt, case.timeout_seconds)
    except subprocess.TimeoutExpired:
        return CaseResult(
            cli, case.id, "TIMEOUT",
            f"no answer within {case.timeout_seconds}s", [], float(case.timeout_seconds),
        )
    except Exception as exc:  # report and continue with the next case
        return CaseResult(cli, case.id, "ERROR", f"{type(exc).__name__}: {exc}", [], 0.0)
    return evaluate(case, output, log_path, elapsed, cli)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli", default="all",
                        choices=["claude", "gemini", "codex", "all"])
    parser.add_argument("--case", action="append", help="case id (repeatable)")
    parser.add_argument("--domain", help="comma-separated domains")
    args = parser.parse_args(argv)

    cases = list(EXTENDED_CASES)
    if args.case:
        wanted = set(args.case)
        cases = [c for c in cases if c.id in wanted]
    if args.domain:
        domains = {d.strip() for d in args.domain.split(",")}
        cases = [c for c in cases if c.domain in domains]
    if not cases:
        print("no cases selected", file=sys.stderr)
        return 2

    clis = ["claude", "gemini", "codex"] if args.cli == "all" else [args.cli]
    results: list[CaseResult] = []

    with tempfile.TemporaryDirectory(prefix="sagemath-clitest-") as tmp:
        log_path = Path(tmp) / "wire.jsonl"
        for cli in clis:
            print(f"\n=== {cli} ===", flush=True)
            try:
                register(cli, log_path)
            except subprocess.CalledProcessError as exc:
                print(f"  could not register with {cli}: {exc.stderr.strip()[:120]}")
                continue
            try:
                for case in cases:
                    result = run_case(cli, case, log_path)
                    results.append(result)
                    mark = "PASS" if result.status == "PASS" else result.status
                    print(f"  [{mark:>13}] {case.id:<24} {result.elapsed:6.1f}s  "
                          f"tools={sorted(set(result.tools_called)) or '-'}", flush=True)
                    if result.status != "PASS":
                        print(f"                  {result.detail}", flush=True)
            finally:
                unregister(cli)

    print("\n=== summary ===")
    ran_nothing = []
    for cli in clis:
        subset = [r for r in results if r.cli == cli]
        passed = sum(1 for r in subset if r.status == "PASS")
        print(f"  {cli:<8} {passed}/{len(subset)} passed")
        if not subset:
            ran_nothing.append(cli)

    if ran_nothing:
        # A CLI that was asked for but ran nothing means registration failed --
        # its `mcp add` syntax changed, or the server would not start. That used
        # to print "0/0 passed" and exit 0, so the check went green precisely
        # when the CLI could not reach the server at all. (Absent credentials do
        # not reach this: those legs are skipped before the runner starts.)
        print(f"\n  ERROR: ran no cases for {', '.join(ran_nothing)} "
              "-- registration failed, so nothing was actually tested")
        return 1

    failures = [r for r in results if r.status != "PASS"]
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
