"""Continuous fuzzing of the AST security policy.

`validate_code` is the first lock on model-written code, and the one that has
been picked most often: items 37, 46, 49, 50, 52, 56, 61-63, 79 and 90 are all
the same shape -- a spelling nobody enumerated. Hand-written cases catch what
someone thought of, and `tests/test_security_property.py` generalises those
into invariants, but both are bounded by the shapes a person chose to write.

This is the unbounded version, run by ClusterFuzzLite in CI and suitable for
OSS-Fuzz. It asserts two things:

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

Run one input locally:

    uv run python fuzz/fuzz_validate.py            # a short built-in campaign
    uv run python fuzz/fuzz_validate.py corpus/    # replay a corpus directory
"""

from __future__ import annotations

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


def _atheris_main() -> None:
    import atheris

    with atheris.instrument_imports():
        pass

    def one(data: bytes) -> None:
        check(data)

    atheris.Setup(sys.argv, one)
    atheris.Fuzz()


def _local_campaign() -> int:
    """A short deterministic campaign, so the harness is exercised without
    atheris installed -- a fuzz target nobody can run is a fuzz target that
    rots."""
    import random

    rng = random.Random(0)
    templates = [
        "@@", "x = @@", "(@@)", "[@@][0]", "@@()", "@@.attr", "f'{@@}'",
        "del @@", "if False:\n    del @@\n@@(1)", "lambda: @@",
        "[e for e in [@@]][0]", "{'k': @@}['k']", "@@ += 1", "global @@",
        "def f(a=@@): pass", "class C(@@): pass", "with @@ as c: pass",
    ]
    for index in range(5000):
        source = rng.choice(templates)
        payload = bytes([index % 256]) + source.encode("utf-8")
        check(payload)
    if JUDGED < len(templates):
        raise AssertionError(
            f"the campaign only judged {JUDGED} programs; the generator is "
            "producing inputs the parser rejects, so 'clean' would mean nothing"
        )
    print(
        f"local campaign clean: {JUDGED} programs validated over "
        f"{len(templates)} templates x {len(DENIED)} denied names"
    )
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and Path(sys.argv[1]).is_dir():
        for path in sorted(Path(sys.argv[1]).rglob("*")):
            if path.is_file():
                check(path.read_bytes())
        print("corpus replay clean")
        raise SystemExit(0)
    try:
        import atheris  # noqa: F401
    except ImportError:
        raise SystemExit(_local_campaign()) from None
    _atheris_main()
