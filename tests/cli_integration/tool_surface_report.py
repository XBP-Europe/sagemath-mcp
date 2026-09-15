"""Lay the tool-surface arms side by side and write tool-surface-stats.md.

Input: the JSON files `run_extended.py --json-out` writes, one per (arm, CLI
set). Output: a markdown report in the shape of benchmark-stats.md -- headline
per arm and CLI, a per-domain breakdown, and the per-case grid -- answering the
question the roadmap kept asserting and never measured: does the 40-tool
catalogue score better than evaluate_sage alone, and does either beat no
server at all?

    python -m tests.cli_integration.tool_surface_report results/tool_surface_*.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ARM_ORDER = ("none", "core", "full")
ARM_LABEL = {
    "none": "No server (reasoning only)",
    "core": "Core tools (evaluate_sage + session)",
    "full": "Full catalogue (40 tools)",
}
STATUS_MARK = {
    "PASS": "✓",
    "WRONG_ANSWER": "⚠",
    "DODGED": "∅",
    "NO_TOOL_CALL": "○",
    "TOOL_ERROR": "✗",
    "TIMEOUT": "⏱",
    "ERROR": "!",
    "QUOTA": "⛔",
}


def load(paths: list[Path]) -> list[dict]:
    results: list[dict] = []
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        for r in data["results"]:
            r.setdefault("arm", data.get("arm", "full"))
            results.append(r)
    return results


def _pct(n: int, d: int) -> str:
    return f"{n}/{d} ({100 * n // d}%)" if d else "n/a"


def _summary(rows: list[dict]) -> dict:
    n = len(rows)
    correct = sum(r["status"] == "PASS" for r in rows)
    wrong = sum(r["status"] == "WRONG_ANSWER" for r in rows)
    dodged = sum(r["status"] == "DODGED" for r in rows)
    no_tool = sum(r["status"] == "NO_TOOL_CALL" for r in rows)
    other = n - correct - wrong - dodged - no_tool
    calls = sum(len(r["tools_called"]) for r in rows)
    latencies = [r["elapsed"] for r in rows if r["status"] not in ("TIMEOUT", "ERROR")]
    median = statistics.median(latencies) if latencies else 0.0
    return {
        "n": n, "correct": correct, "wrong": wrong, "dodged": dodged, "no_tool": no_tool,
        "other": other, "calls": calls, "median_s": median,
    }


def render(results: list[dict]) -> str:
    arms = [a for a in ARM_ORDER if any(r["arm"] == a for r in results)]
    clis = sorted({r["cli"] for r in results})
    domains = sorted({r.get("domain", "") for r in results})
    cases = sorted({r["case_id"] for r in results})

    out: list[str] = []
    out.append("# Tool-surface measurement")
    out.append("")
    out.append(
        "Does the 40-tool catalogue earn its keep? The same tool-forcing cases\n"
        "(`tests/cli_integration/extended_cases.py`, answers impractical without a\n"
        "CAS) run through real CLI clients in three arms: no MCP server registered,\n"
        "the server narrowed on the wire to `evaluate_sage` plus the session and\n"
        "diagnostic tools (the proxy hides everything else from `tools/list` and\n"
        "refuses it on `tools/call`), and the full catalogue. Produced by\n"
        "`make tool-surface`; never CI-gated -- it measures the clients as much as\n"
        "the server."
    )
    out.append("")
    out.append(f"- Generated: {time.strftime('%Y-%m-%d')}")
    out.append(f"- Cases: {len(cases)} across domains: {', '.join(d for d in domains if d)}")
    out.append(f"- Clients: {', '.join(clis)}")
    out.append(
        "- Statuses: ✓ correct · ⚠ wrong-confident · ∅ declined · ○ answered without a\n"
        "  qualifying tool call · ✗ server error · ⏱ timeout · ⛔ cut off by the\n"
        "  provider (spend/usage limit), which is counted under *Other*, not against\n"
        "  the arm"
    )
    out.append(
        "- The no-server arm is enforced or observed per client: Claude Code runs with\n"
        "  `--tools \"\"` (no built-in tools at all); Gemini runs without `--yolo` and\n"
        "  its own statistics report every tool it attempted; Codex cannot be denied a\n"
        "  shell, so its `--json` event stream is scanned for `command_execution`. Any\n"
        "  such use shows up in the *Tool calls* column of that arm, which should read 0."
    )
    out.append("")
    out.append("## Headline")
    out.append("")
    out.append(
        "| Arm | Client | Correct | Wrong-confident | Declined | No tool call | Other | "
        "Tool calls | Median s |"
    )
    out.append("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")

    def headline_row(arm: str, label: str, rows: list[dict]) -> str:
        s = _summary(rows)
        return (
            f"| {ARM_LABEL[arm]} | {label} | **{_pct(s['correct'], s['n'])}** | {s['wrong']} | "
            f"{s['dodged']} | {s['no_tool']} | {s['other']} | {s['calls']} | "
            f"{s['median_s']:.0f} |"
        )

    for arm in arms:
        for cli in clis:
            rows = [r for r in results if r["arm"] == arm and r["cli"] == cli]
            if rows:
                out.append(headline_row(arm, cli, rows))
        out.append(headline_row(arm, "**all**", [r for r in results if r["arm"] == arm]))
    out.append("")

    cut_off = sorted({(r["arm"], r["cli"]) for r in results if r["status"] == "QUOTA"})
    if cut_off:
        out.append(
            "Arms with provider cut-offs (⛔): "
            + ", ".join(f"{arm}/{cli}" for arm, cli in cut_off)
            + ". They stay in the table above but are **excluded from every comparison "
            "below**, which only counts client-cases both arms actually measured."
        )
        out.append("")

    def compare(a: str, b: str) -> tuple[int, int, int, int] | None:
        """(correct in a, correct in b, n) over client-cases measured in both."""
        measured = {
            arm: {(r["cli"], r["case_id"]): r for r in results
                  if r["arm"] == arm and r["status"] != "QUOTA"}
            for arm in (a, b)
        }
        keys = set(measured[a]) & set(measured[b])
        if not keys:
            return None
        ca = sum(measured[a][k]["status"] == "PASS" for k in keys)
        cb = sum(measured[b][k]["status"] == "PASS" for k in keys)
        return ca, cb, len(keys), cb - ca

    if "core" in arms and "full" in arms and (cmp := compare("core", "full")):
        ca, cb, n, delta = cmp
        out.append(
            f"**Full catalogue minus core tools: {delta:+d} correct** over {n} client-cases "
            f"measured in both ({_pct(ca, n)} → {_pct(cb, n)})."
        )
    if "none" in arms:
        for other in ("core", "full"):
            if other in arms and (cmp := compare("none", other)):
                ca, cb, n, delta = cmp
                out.append(
                    f"**{ARM_LABEL[other]} minus no server: {delta:+d} correct** over {n} "
                    f"client-cases measured in both ({_pct(ca, n)} → {_pct(cb, n)}). In the "
                    f"server arms a correct answer only counts with a successful qualifying "
                    f"tool call, so this delta measures integration friction as much as "
                    f"mathematics."
                )
        none = _summary([r for r in results if r["arm"] == "none"])
        out.append(
            f"The no-server arm was wrong-confident **{none['wrong']}** times and declined "
            f"{none['dodged']} times in {none['n']} client-cases."
        )
    out.append("")

    out.append("## By domain (all clients)")
    out.append("")
    out.append("| Domain | " + " | ".join(ARM_LABEL[a] for a in arms) + " |")
    out.append("| --- |" + " ---: |" * len(arms))
    for domain in domains:
        cells = []
        for arm in arms:
            rows = [r for r in results if r["arm"] == arm and r.get("domain") == domain]
            s = _summary(rows)
            cells.append(_pct(s["correct"], s["n"]))
        out.append(f"| {domain or '(none)'} | " + " | ".join(cells) + " |")
    out.append("")

    out.append("## Per case")
    out.append("")
    out.append(
        "One cell per (arm, client). A ✓ in *core* next to a ✓ in *full* is a case the\n"
        "helpers did not decide; a ○/⚠ in *core* against a ✓ in *full* is the value\n"
        "a dedicated tool added."
    )
    out.append("")
    header = ["Case", "Domain"] + [f"{arm}/{cli}" for arm in arms for cli in clis]
    out.append("| " + " | ".join(header) + " |")
    out.append("| --- | --- |" + " :---: |" * (len(arms) * len(clis)))
    by_key: dict[tuple[str, str, str], dict] = {}
    domain_of: dict[str, str] = defaultdict(str)
    for r in results:
        by_key[(r["arm"], r["cli"], r["case_id"])] = r
        domain_of[r["case_id"]] = r.get("domain", "")
    for case in cases:
        cells = []
        for arm in arms:
            for cli in clis:
                r = by_key.get((arm, cli, case))
                cells.append(STATUS_MARK.get(r["status"], "?") if r else "")
        out.append(f"| `{case}` | {domain_of[case]} | " + " | ".join(cells) + " |")
    out.append("")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "tool-surface-stats.md")
    args = parser.parse_args(argv)
    results = load(args.inputs)
    if not results:
        print("no results in the given files", file=sys.stderr)
        return 2
    args.out.write_text(render(results), encoding="utf-8")
    print(f"wrote {args.out} ({len(results)} results)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
