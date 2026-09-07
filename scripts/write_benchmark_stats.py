#!/usr/bin/env python3
"""Render ``benchmark-stats.md`` from an outcome-benchmark result JSON.

The benchmark itself is the Workflow in ``benchmarks/outcome_benchmark.workflow.js``:
it runs the fixed case set (``benchmarks/cases.json``) through the model twice --
reasoning alone vs. with SageMath compute -- and scores every answer for
equivalence in Sage. That Workflow returns a JSON object (``perProblem`` +
``summary``); this script turns it into the published table, the way the doctest
corpus sweep writes ``doctest-corpus-stats.md``.

Usage:
    python scripts/write_benchmark_stats.py <result.json> [--generated "<when>"]

Kept separate from the Workflow so the numbers can be re-rendered without
re-running the model, and so the render is plain, reviewable Python.
"""

from __future__ import annotations

import argparse
import json
import pathlib

STATS = "benchmark-stats.md"
ARM_LABEL = {"no_tools": "Reasoning only", "sage": "With Sage compute"}


def _acc(t: dict) -> str:
    return f"{t['correct']}/{t['total']}" + (
        f" ({100.0 * t['correct'] / t['total']:.0f}%)" if t["total"] else ""
    )


def render(data: dict, generated: str) -> str:
    summary = data["summary"]
    tiers = data["tiers"]
    arms = data["arms"]
    per = data["perProblem"]

    overall = summary["overall"]
    nt, sg = overall["no_tools"], overall["sage"]
    delta = sg["correct"] - nt["correct"]

    lines = [
        "# Outcome benchmark",
        "",
        "Does the model get more mathematics right when it can run Sage, versus",
        "reasoning alone? Two arms over the fixed case set in `benchmarks/cases.json`,",
        "every answer scored for *mathematical equivalence* in the SageMath 10.9",
        "container (not string-matched). Produced by",
        "`benchmarks/outcome_benchmark.workflow.js`.",
        "",
        f"- Generated: {generated}",
        f"- Cases: {nt['total']} across tiers: {', '.join(tiers)}",
        f"- Subject model (under test): `{data.get('subjectModel', 'unknown')}`"
        f"; scoring judge: `{data.get('judgeModel', 'unknown')}`",
        "- This is as much a measurement of the subject model as of the server; a",
        "  stronger model closes the gap on its own. Never CI-gated.",
        "",
        "## Headline",
        "",
        "| Arm | Correct | Wrong-confident | Refused | Sage calls |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for arm in arms:
        t = overall[arm]
        lines.append(
            f"| {ARM_LABEL.get(arm, arm)} | {_acc(t)} | {t['wrongConfident']} "
            f"| {t['refused']} | {t['toolCalls']} |"
        )
    lines += [
        "",
        f"**Delta: +{delta}** answers correct with Sage compute "
        f"({_acc(nt)} → {_acc(sg)}).",
        "",
        "## By tier",
        "",
        "| Tier | Reasoning only | With Sage | Delta |",
        "| --- | ---: | ---: | ---: |",
    ]
    for tier in tiers:
        bt = summary["byTier"][tier]
        d = bt["sage"]["correct"] - bt["no_tools"]["correct"]
        sign = f"+{d}" if d > 0 else str(d)
        lines.append(f"| {tier} | {_acc(bt['no_tools'])} | {_acc(bt['sage'])} | {sign} |")

    lines += [
        "",
        "## Per problem",
        "",
        "A ✗ in *Reasoning only* that is ✓ *With Sage* is the value the server adds;",
        "a wrong-confident cell (⚠) is the failure mode `verify_claim` exists for.",
        "",
        "| ID | Tier | Reasoning only | With Sage |",
        "| --- | --- | :---: | :---: |",
    ]
    by_id: dict[str, dict[str, dict]] = {}
    for r in per:
        by_id.setdefault(r["id"], {})[r["arm"]] = r
    for pid in sorted(by_id):
        row = by_id[pid]
        tier = next(iter(row.values()))["tier"]
        cells = []
        for arm in arms:
            r = row.get(arm, {})
            if r.get("refused"):
                cells.append("— (refused)")
            elif r.get("correct"):
                cells.append("✓")
            elif r.get("wrong_confident"):
                cells.append("⚠ wrong")
            else:
                cells.append("✗")
        lines.append(f"| {pid} | {tier} | {cells[0]} | {cells[1]} |")

    lines += [
        "",
        "## Method and honest limits",
        "",
        "- The two arms are the **same model**; one is told to reason unaided, the",
        "  other to compute and verify with Sage. The delta is the lift from having",
        "  the CAS in the loop.",
        "- The compute arm runs Sage **directly** (`docker exec ... sage -c`), so it",
        "  bypasses this server -- its tool selection, input validation, handles and",
        "  verifier. So the result supports *Sage computation helps this model on these",
        "  cases*, not yet *this server's design improves outcomes*. Measuring through",
        "  the MCP interface with enforced tool permissions is the intended next step.",
        "- *Reasoning only* is **prompt-enforced**: the agent is told not to execute",
        "  anything and self-reports zero tool calls. It is not hard tool-gated. The",
        "  rigorous three-arm version (no-tools / `evaluate_sage`-only / full",
        "  catalogue, with real gating) is a planned `tests/cli_integration` harness --",
        "  a follow-up under the CLI nightlies, not something that runs today.",
        "- Answers are scored by an **independent** Sage-backed step, so a plausible",
        "  wrong answer is caught, not accepted on its wording.",
        "- Small, fixed, seeded case set: this is a directional signal a run can",
        "  reproduce, not a leaderboard number. Grow `benchmarks/cases.json` to",
        "  tighten it.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("result", help="Path to the Workflow result JSON.")
    ap.add_argument("--generated", default="on demand", help="Timestamp for the stats file.")
    args = ap.parse_args()
    data = json.loads(pathlib.Path(args.result).read_text(encoding="utf-8"))
    pathlib.Path(STATS).write_text(render(data, args.generated), encoding="utf-8")
    print(f"Wrote {STATS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
