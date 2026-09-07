#!/usr/bin/env python3
"""Mutation-test the AST security policy and write ``mutation-stats.md``.

Line coverage is nearly meaningless for a security policy: a rule can be fully
covered and still be wrong. A mutation score is the real claim -- it is the
share of deliberate weakenings of ``security.py`` (a flipped ``in``, a dropped
branch, a relaxed comparison) that the test suite *catches*. cosmic-ray applies
each mutation in place, runs the security tests, and records whether they failed
(the mutant was "killed") or passed (it "survived" -- a gap).

This is slow and its number measures test quality, not correctness, so it is
never CI-gated: it runs on demand (``make mutation``) and in a non-gating job.
The counterpart guardrail is that ``allowlist.py`` is *generated data*, not
logic, so it is out of scope here -- its correctness is guarded by the
Sage-agreement integration test instead.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time

CONFIG = "mutation/security.toml"
SESSION = "mutation/security.sqlite"
STATS = "mutation-stats.md"
_WORKER_BASE_PORT = 9800


def _run(*args: str) -> str:
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout


def _wait_for_port(port: int, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            sock.settimeout(0.5)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.1)
    raise RuntimeError(f"mutation worker on port {port} never became ready")


def _exec_parallel(workers: int) -> None:
    """Distribute the session across `workers` HTTP workers, each on its own copy.

    cosmic-ray's local distributor is serial -- one mutation, one full pytest
    run, ~2s, 696 times over. The http distributor pulls mutants from a queue in
    parallel, but each worker must mutate its *own* checkout. So each gets a
    plain copy of the whole tree (uncommitted files included -- no git clone),
    and the test command sets `PYTHONPATH=src` so the copy's mutated
    `security.py` shadows the editable install. A ~30-minute serial run becomes a
    few minutes.

    The copy is the *whole* tree, not just `src/` and `tests/`: the security
    suite reads root files by path (`README.md`, `Dockerfile`,
    `docker-compose.yml`, `.github/workflows/release.yml`, ...) anchored at its
    own repo root. Miss one and every genuine survivor trips that read's
    assertion instead -- reported as a false kill, which reads as a perfect
    score.
    """
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="cr-mutation-"))
    procs: list[subprocess.Popen] = []
    urls: list[str] = []
    ignore = shutil.ignore_patterns(
        ".git", ".venv", "venv", "__pycache__", "*.pyc", ".hypothesis",
        ".cosmic-ray", "*.sqlite", ".pytest_cache", ".ruff_cache", ".mypy_cache",
        "node_modules", ".tox", "dist", "build",
    )
    try:
        for i in range(workers):
            copy = tmp / f"w{i}"
            shutil.copytree(".", copy, ignore=ignore, symlinks=True)
            port = _WORKER_BASE_PORT + i
            procs.append(
                subprocess.Popen(
                    ["cosmic-ray", "http-worker", "--port", str(port)],
                    cwd=copy,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            )
            urls.append(f"http://127.0.0.1:{port}")
        for i in range(workers):
            _wait_for_port(_WORKER_BASE_PORT + i)
        # A throwaway config that points the http distributor at the workers.
        http_cfg = tmp / "http.toml"
        base = pathlib.Path(CONFIG).read_text(encoding="utf-8")
        base = base.replace('name = "local"', 'name = "http"')
        url_list = ", ".join(f'"{u}"' for u in urls)
        http_cfg.write_text(
            base + f'\n[cosmic-ray.distributor.http]\nworker-urls = [{url_list}]\n',
            encoding="utf-8",
        )
        subprocess.run(["cosmic-ray", "exec", str(http_cfg), SESSION], check=True)
    finally:
        for proc in procs:
            proc.terminate()
        for proc in procs:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)


def _parse(report: str) -> dict[str, int]:
    def grab(pattern: str) -> int:
        match = re.search(pattern, report)
        return int(match.group(1)) if match else 0

    return {
        "total": grab(r"total jobs:\s*(\d+)"),
        "complete": grab(r"complete:\s*(\d+)"),
        "surviving": grab(r"surviving mutants:\s*(\d+)"),
    }


def _survivor_operators(report: str) -> dict[str, int]:
    """Count surviving mutants by mutation operator.

    Lets the stats separate genuine test gaps from equivalent mutants -- most
    notably ``ReplaceBinaryOperator_BitOr``, which under ``from __future__ import
    annotations`` only ever hits the ``X | None`` in a type hint (a string that
    is never evaluated), so it cannot change behaviour and no test can kill it.
    """
    counts: dict[str, int] = {}
    current_op = None
    for line in report.splitlines():
        # Group BitOr replacements (the type-annotation `|`) as their own key,
        # everything else by the operator family.
        match = re.search(r"core/(ReplaceBinaryOperator_[A-Za-z]+|[A-Za-z]+)", line)
        if match:
            current_op = match.group(1)
        if "TestOutcome.SURVIVED" in line and current_op:
            counts[current_op] = counts.get(current_op, 0) + 1
    return counts


def _write_stats(counts: dict[str, int], survivors: dict[str, int], generated: str) -> None:
    complete = counts["complete"]
    surviving = counts["surviving"]
    killed = complete - surviving
    score = (100.0 * killed / complete) if complete else 0.0
    survival = (100.0 * surviving / complete) if complete else 0.0
    # BitOr survivors are the `X | None` in type hints -- equivalent mutants, not
    # gaps. Report the score with them excluded from both sides too.
    equivalent = survivors.get("ReplaceBinaryOperator_BitOr", 0)
    eff_complete = complete - equivalent
    eff_score = (100.0 * (killed) / eff_complete) if eff_complete else 0.0
    survivor_rows = "\n".join(
        f"| `{op}` | {n} |" for op, n in sorted(survivors.items(), key=lambda kv: -kv[1])
    )
    lines = [
        "# Mutation-testing statistics",
        "",
        "The mutation score of the AST security policy (`src/sagemath_mcp/security.py`).",
        "cosmic-ray applies each deliberate weakening and runs the security suite; a",
        "mutant is *killed* when a test fails, *survives* when they all pass. A high",
        "score means the tests exercise the policy's logic, not just its lines. Never",
        "CI-gated; run with `make mutation`.",
        "",
        f"- Generated: {generated}",
        "- Scope: `src/sagemath_mcp/security.py` (allowlist.py is generated data, guarded",
        "  by the Sage-agreement integration test instead)",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Mutants generated | {counts['total']} |",
        f"| Mutants run | {complete} |",
        f"| Killed | {killed} |",
        f"| Surviving | {surviving} |",
        f"| **Mutation score** | **{score:.2f}%** |",
        f"| Survival rate | {survival:.2f}% |",
        "",
        "## Surviving mutants, by operator",
        "",
        "Survivors are either genuine test gaps or *equivalent* mutants -- changes",
        "that cannot alter behaviour. The largest class here is",
        "`ReplaceBinaryOperator` on the `|` of an `X | None` type hint: under",
        "`from __future__ import annotations` that annotation is a string that is",
        "never evaluated, so no test can kill it.",
        "",
        "| Operator | Surviving |",
        "| --- | ---: |",
        survivor_rows,
        "",
        f"Excluding the {equivalent} equivalent type-annotation mutants, the",
        f"effective mutation score is **{eff_score:.2f}%** ({killed}/{eff_complete}).",
        "",
        "The remaining survivors are a mix: some are still near-equivalent (a",
        "`== \"s\"` turned to `is \"s\"` compares interned strings the same way; a",
        "`NumberReplacer` on a non-behavioural constant), and some are genuine",
        "test gaps -- boolean-logic and boundary-comparison flips on branches the",
        "suite reaches but does not pin from both sides. The genuine ones are the",
        "actionable output; closing them is tracked in TODO.",
        "",
        f"Inspect any survivor with `cr-report {SESSION} --show-output`.",
        "",
    ]
    pathlib.Path(STATS).write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Do not re-run; just regenerate mutation-stats.md from the existing session.",
    )
    parser.add_argument("--generated", default="", help="Timestamp to stamp into the stats file.")
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Parallel HTTP workers (each on its own copy). 1 = the serial local "
        "distributor. Default 8.",
    )
    args = parser.parse_args()

    if not args.report_only:
        pathlib.Path(SESSION).unlink(missing_ok=True)
        _run("cosmic-ray", "init", CONFIG, SESSION)
        if args.workers > 1:
            _exec_parallel(args.workers)
        else:
            subprocess.run(["cosmic-ray", "exec", CONFIG, SESSION], check=True)

    report = _run("cr-report", SESSION)
    counts = _parse(report)
    survivors = _survivor_operators(report)
    _write_stats(counts, survivors, args.generated or "on demand")
    killed = counts["complete"] - counts["surviving"]
    score = (100.0 * killed / counts["complete"]) if counts["complete"] else 0.0
    print(f"Mutation score: {score:.2f}% ({killed}/{counts['complete']} killed)")
    print(f"Wrote {STATS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
