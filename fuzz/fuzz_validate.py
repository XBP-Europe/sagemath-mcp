"""Continuous fuzzing of the AST security policy.

`validate_code` is the first lock on model-written code, and the one that has
been picked most often: items 37, 46, 49, 50, 52, 56, 61-63, 79 and 90 are all
the same shape -- a spelling nobody enumerated. Hand-written cases catch what
someone thought of, and `tests/test_security_property.py` generalises those
into invariants, but both are bounded by the shapes a person chose to write.

This is the unbounded version, run by `.github/workflows/fuzz.yml` on the
Python the package requires. ClusterFuzzLite was wired up first and removed
the same day: its base image ships Python 3.11, and PEP 701 rewrote f-string
parsing in 3.12, so a coverage-guided run there would face a different parser
for exactly the construct that produced this campaign's one false positive.

It asserts two things:

1. **The policy never crashes.** For any input, `validate_code` either returns
   or raises `SecurityViolation`. Any other exception is a bug: callers that
   catch only `SecurityViolation` would see it propagate, and a rule that
   raises `AttributeError` on some shape is a rule that is not being applied.

2. **A denied name is never accepted in a read position.** The fuzzer splices
   a name the policy denies into the generated program; if the parsed tree
   reads that name and validation passes, the policy has a hole.

The second check is verified against the **parsed tree**, never the source
text. The first campaign to skip that reported `f'{{name}}'` as a bypass --
those are literal braces, and no name is in the program at all.

Run it locally:

    uv run python fuzz/fuzz_validate.py                      # a short campaign
    uv run python fuzz/fuzz_validate.py --iterations 2000000 # the weekly one
    uv run python fuzz/fuzz_validate.py corpus/              # replay a corpus
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sagemath_mcp.security import (
    SECURITY_POLICY,
    SecurityViolation,
    validate_code,
)

#: Names the policy is supposed to refuse in a read position. Taken from the
#: live policy rather than hard-coded, so a rule that stops denying one of
#: these is a finding here rather than a silent relaxation.
DENIED: tuple[str, ...] = tuple(
    sorted(SECURITY_POLICY.forbidden_call_names)
)


def _reads(tree: ast.Module, name: str) -> bool:
    """Does the parsed program LOAD `name`? The source text is not evidence."""
    return any(
        isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, ast.Load)
        for node in ast.walk(tree)
    )


#: Programs actually validated, as opposed to rejected by the parser first.
#: Reported at the end of a campaign, because "clean" over zero programs is
#: the same output as "clean" over fifty thousand, and only one of them means
#: anything. A run of this harness whose first byte joined the source text
#: made almost everything a SyntaxError while still printing "clean".
JUDGED = 0


def check(data: bytes) -> None:
    """One fuzz iteration. Raises AssertionError on a finding.

    The first byte selects which denied name to splice in; the rest is the
    program. Keeping the selector out of the source is what stops a mutation
    from silently turning every input into a SyntaxError.
    """
    global JUDGED
    if not data:
        return
    name = DENIED[data[0] % len(DENIED)]
    try:
        source = data[1:].decode("utf-8")
    except UnicodeDecodeError:
        return
    source = source.replace("@@", name)

    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        return
    JUDGED += 1

    try:
        validate_code(source)
    except SecurityViolation:
        return
    except RecursionError:
        # Depth is bounded by a policy rule of its own; the parser gives up
        # first on some shapes, and neither is a security finding.
        return
    except Exception as exc:
        raise AssertionError(
            f"validate_code raised {type(exc).__name__}, not SecurityViolation, "
            f"on {source!r}: {exc}"
        ) from exc

    if _reads(tree, name):
        raise AssertionError(f"denied name {name!r} was accepted in a read position: {source!r}")


#: Statement shapes with a `@@` hole. The hole is filled with an expression
#: built from `_WRAPS`, so the campaign explores nesting rather than this list.
_TEMPLATES = (
    "@@", "x = @@", "(@@)", "@@()", "@@.attr", "f'{@@}'", "del @@",
    "if False:\n    del @@\n@@(1)", "lambda: @@", "@@ += 1", "global @@",
    "def f(a=@@): pass", "class C(@@): pass", "with @@ as c: pass",
    "print(@@)", "@@\ndef f(): pass", "for i in [@@]: pass", "while @@: break",
    "match @@:\n    case _: pass", "try:\n    pass\nexcept @@: pass",
    "assert @@", "[e for e in [@@]][0]", "{'k': @@}['k']", "return @@",
)

#: Expression wrappers, applied to a random depth around the hole.
_WRAPS = (
    "({})", "[{}][0]", "({},)[0]", "{{'k': {}}}['k']", "{{{}}}", "not {}",
    "(lambda a={}: a)()", "(lambda: {})()", "[e for e in [{}]][0]", "-{}",
    "({} if True else None)", "(None if False else {})", "[*[{}]][0]",
    "{}()", "{}.attr", "{}[0]", "{} + 1", "f'{{{}}}'", "{} if {} else {}",
    "{{**{{'a': {}}}}}['a']", "sorted([{}], key=lambda v: v)",
    "[x for x in [1] if {}][0]", "(lambda *a: a)(*[{}])",
)


def _local_campaign(iterations: int = 5000, seed: int = 0) -> int:
    """The campaign. Deterministic for a given seed, so a finding replays.

    Runs without any fuzzing engine, which is the point: a fuzz target nobody
    can run is a fuzz target that rots, and this one is exercised by the unit
    suite as well as by CI.
    """
    import random

    rng = random.Random(seed)
    for index in range(iterations):
        expression = "@@"
        for _ in range(rng.randint(0, 3)):
            wrap = rng.choice(_WRAPS)
            try:
                expression = wrap.format(*([expression] * wrap.count("{}")))
            except (IndexError, KeyError):
                pass
        source = rng.choice(_TEMPLATES).replace("@@", expression)
        check(bytes([index % 256]) + source.encode("utf-8"))
    if JUDGED < min(iterations, len(_TEMPLATES)):
        raise AssertionError(
            f"the campaign only judged {JUDGED} programs; the generator is "
            "producing inputs the parser rejects, so 'clean' would mean nothing"
        )
    print(
        f"campaign clean: {JUDGED} of {iterations} generated programs validated, "
        f"over {len(_TEMPLATES)} templates x {len(_WRAPS)} wrappers x "
        f"{len(DENIED)} denied names (seed {seed})"
    )
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Fuzz the AST security policy.")
    parser.add_argument("corpus", nargs="?", help="replay every file in a directory")
    parser.add_argument("--iterations", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=0, help="a finding replays with its seed")
    args = parser.parse_args(argv)

    if args.corpus:
        for path in sorted(Path(args.corpus).rglob("*")):
            if path.is_file():
                check(path.read_bytes())
        print(f"corpus replay clean: {JUDGED} programs validated")
        return 0
    return _local_campaign(args.iterations, args.seed)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
