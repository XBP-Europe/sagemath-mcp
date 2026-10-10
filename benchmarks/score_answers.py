"""Score an unscored outcome-benchmark result in Sage, without a judge model.

The workflow's `score: 'none'` mode returns each arm's answers with
`correct: null`. This applies the judge prompt's own rules mechanically --
the same equivalence checks, run once, reproducibly, at no model cost:

- numeric: exact equality, parsing decimals as rationals (`6.80` is 34/5)
- symbolic: `(model - gold).simplify_full() == 0`
- set: equal as sets of exact values
- a refused, empty or unparseable answer is not correct

Unparseable answers are marked `unparsed` in the note so a person can look at
them; nothing is guessed. Run inside the Sage container, writing to stdout:

    docker exec sage-mcp sage -python /workspace/benchmarks/score_answers.py \\
        /workspace/benchmarks/cases.json /workspace/<unscored.json> > result.json
"""

from __future__ import annotations

import json
import re
import sys

from sage.all import QQ, SR
from sage.version import version as SAGE_VERSION

_SUPERSCRIPT = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")
_UNICODE = [
    (re.compile(r"√\s*\("), "sqrt("),
    (re.compile(r"√\s*([0-9A-Za-z.]+)"), r"sqrt(\1)"),
    (re.compile(r"([⁰¹²³⁴⁵⁶⁷⁸⁹]+)"), lambda m: "^" + m.group(1).translate(_SUPERSCRIPT)),
]
_IMPLICIT = [
    (re.compile(r"\)\s*\("), ")*("),
    (re.compile(r"(\d)\s*([A-Za-z(])"), r"\1*\2"),
    (re.compile(r"\)\s*([A-Za-z0-9])"), r")*\1"),
]


def _expr(text: str):
    text = text.strip().replace("$", "").replace("π", "pi")
    text = text.replace("\u00d7", "*").replace("\u2212", "-")  # multiplication, minus signs
    for pattern, repl in _UNICODE:
        text = pattern.sub(repl, text)
    for pattern, repl in _IMPLICIT:
        text = pattern.sub(repl, text)
    return SR(text)


def _number(text: str):
    text = text.strip().replace("$", "").replace(",", "").replace(" ", "")
    try:
        return SR(QQ(text))
    except (TypeError, ValueError):
        return _expr(text)


def _elements(text: str, want: int) -> list:
    text = text.strip()
    if text[:1] + text[-1:] in ("{}", "[]", "()"):
        text = text[1:-1]
    parts = [p for p in re.split(r",|\band\b", text) if p.strip()]
    # "Find both prime factors" answered as "p * q": a product of the elements.
    if len(parts) == 1 and want > 1 and "*" in parts[0]:
        parts = parts[0].split("*")
    return [_expr(part) for part in parts]


def _same(a, b) -> bool:
    return bool((a - b).simplify_full() == 0)


def check(kind: str, model: str, gold: str) -> tuple[bool, str]:
    try:
        if kind == "numeric":
            return bool(_number(model) == _number(gold)), "exact equality"
        if kind == "symbolic":
            return _same(_expr(model), _expr(gold)), "simplify_full(model - gold) == 0"
        if kind == "set":
            want = _elements(gold, 0)
            got = _elements(model, len(want))
            unmatched = list(want)
            for item in got:
                match = next((w for w in unmatched if _same(item, w)), None)
                if match is None:
                    return False, "set element not in gold"
                unmatched.remove(match)
            return not unmatched, "equal as sets"
    except Exception as exc:  # any parse failure is a person's call, not a guess
        return False, f"unparsed: {type(exc).__name__}"
    return False, f"unknown check type {kind!r}"


def _tally(rows: list[dict]) -> dict:
    return {
        "total": len(rows),
        "correct": sum(r["correct"] for r in rows),
        "refused": sum(r["refused"] for r in rows),
        "wrongConfident": sum(r["wrong_confident"] for r in rows),
        "toolCalls": sum(r["tool_calls"] or 0 for r in rows),
    }


def main(cases_path: str, result_path: str) -> None:
    cases = {c["id"]: c for c in json.load(open(cases_path))["cases"]}
    data = json.load(open(result_path))
    for row in data["perProblem"]:
        case = cases[row["id"]]
        answer = (row.get("answer") or "").strip()
        if row["refused"] or not answer:
            row["correct"], row["note"] = False, "no answer"
        else:
            row["correct"], row["note"] = check(case["check"], answer, case["gold_sage"])
        row["wrong_confident"] = row["confident"] and not row["correct"] and not row["refused"]

    rows = data["perProblem"]
    data["summary"] = {
        "overall": {a: _tally([r for r in rows if r["arm"] == a]) for a in data["arms"]},
        "byTier": {
            t: {
                a: _tally([r for r in rows if r["arm"] == a and r["tier"] == t])
                for a in data["arms"]
            }
            for t in data["tiers"]
        },
    }
    data["judgeModel"] = "none (deterministic Sage check, benchmarks/score_answers.py)"
    data["sageVersion"] = SAGE_VERSION
    json.dump(data, sys.stdout, indent=1)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
