"""Fuzz the worker's JSON protocol frames.

The worker subprocess holds the session's entire namespace. An uncaught
exception in its protocol loop does not drop one request -- it discards every
variable the caller has built up, and the parent sees a closed pipe with no
reason attached. So the loop's contract is that **any** line of input produces
a response frame and leaves the worker serving.

That was not true. `[]` is valid JSON, and `[].get("type")` is an
AttributeError that nothing caught, so a single malformed frame killed the
session. Five shapes did it (`[]`, a string, a number, `null`, `true`), plus
`{"type": "execute"}` with no `code`, through a `KeyError`.

Frames come from `session.py`, so none of this was reachable from a caller.
It was one bug in that file away from a dead session with no diagnosis, which
is the same argument the namespace scrub gets: the second lock is worth having
even when the first one holds.

This fuzzes `_read_frame`, the pure part of the loop, so it needs no
subprocess and runs in the unit suite.

    uv run python fuzz/fuzz_protocol.py --iterations 200000
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

JUDGED = 0

_KEYS = ("type", "id", "code", "want_latex", "capture_stdout", "trusted", "stream")
_TYPES = ("execute", "reset", "shutdown", "", None, 0, [], {}, "EXECUTE", "exec")
_VALUES = (
    None, 0, 1, -1, 1.5, "", "1+1", "x = 1", True, False, [], {}, [1, 2],
    {"a": 1}, "\x00", "\n", "é", "\\", '"', 10**20, "a" * 500,
)


def _frames(rng: random.Random) -> str:
    """One line of input, as the worker would read it from stdin."""
    shape = rng.randint(0, 5)
    if shape == 0:  # not JSON at all
        return rng.choice(("", "   ", "{", "}", "not json", "\x00", "[1,", "nan"))
    if shape == 1:  # valid JSON, not an object -- the crash class
        return json.dumps(rng.choice((None, True, False, 1, 1.5, "s", [], [1, 2])))
    if shape == 2:  # an object missing required keys
        return json.dumps({k: rng.choice(_VALUES) for k in rng.sample(_KEYS, rng.randint(0, 3))})
    frame: dict = {"type": rng.choice(_TYPES)}
    for key in _KEYS[1:]:
        if rng.random() < 0.6:
            frame[key] = rng.choice(_VALUES)
    return json.dumps(frame)


def check(line: str) -> None:
    """One iteration. The parser must answer, and must not raise."""
    global JUDGED
    from sagemath_mcp._sage_worker import _read_frame

    try:
        frame, error = _read_frame(line)
    except Exception as exc:
        raise AssertionError(
            f"the protocol parser raised {type(exc).__name__} on {line!r}: {exc}"
        ) from exc
    JUDGED += 1
    assert frame is None or error is None, (
        f"{line!r} produced both a frame and an error, so the loop would serve "
        "a frame it had already refused"
    )
    if error is not None:
        assert "ok" in error and error["ok"] is False, f"{line!r}: {error!r}"
        json.dumps(error)  # unserialisable means the parent gets nothing at all
    elif frame is not None:
        assert isinstance(frame, dict)
        # An execute frame reaching the loop must carry the key the loop
        # indexes, or the KeyError this file exists for comes straight back.
        if frame.get("type") == "execute":
            assert "code" in frame, f"{line!r} passed as an execute frame with no code"


def campaign(iterations: int = 5000, seed: int = 0) -> int:
    rng = random.Random(seed)
    for _ in range(iterations):
        check(_frames(rng))
    if JUDGED < iterations // 2:
        raise AssertionError(f"only {JUDGED}/{iterations} frames were dispatched")
    print(f"protocol campaign clean: {JUDGED} frames dispatched (seed {seed})")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Fuzz the worker protocol.")
    parser.add_argument("--iterations", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)
    return campaign(args.iterations, args.seed)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
