import asyncio
import json
import shutil
import time

import pytest
import pytest_asyncio

from sagemath_mcp import runtime, server
from sagemath_mcp.config import SageSettings
from sagemath_mcp.monitoring import reset_metrics
from sagemath_mcp.session import SageEvaluationError, SageSession, SageSessionManager

from .conftest import FakeContext

requires_sage = pytest.mark.skipif(
    shutil.which("sage") is None, reason="Sage executable not available"
)


@pytest.fixture(autouse=True)
def unset_pure_python(monkeypatch):
    monkeypatch.delenv("SAGEMATH_MCP_PURE_PYTHON", raising=False)


@pytest_asyncio.fixture
async def real_sage_manager(monkeypatch):
    """A manager backed by the actual Sage worker.

    The shared `sage_manager` fixture forces the pure-Python shim, which is
    right for routing tests and useless for anything asserting Sage semantics:
    tests written against it would have been checking the shim's behaviour while
    claiming to check Sage's.
    """
    manager = SageSessionManager(SageSettings(force_python_worker=False, eval_timeout=90.0))
    monkeypatch.setattr(runtime, "SESSION_MANAGER", manager)
    try:
        yield manager
    finally:
        await manager.shutdown()


@requires_sage
@pytest.mark.asyncio
async def test_real_sage_session_evaluates_expression():
    settings = SageSettings(force_python_worker=False)
    session = SageSession("integration-session", settings)
    try:
        result = await session.evaluate("factorial(5)", want_latex=False, capture_stdout=False)
        assert result.result == "120"
    finally:
        await session.shutdown()


@requires_sage
@pytest.mark.asyncio
async def test_security_violation_keeps_session_alive():
    settings = SageSettings(force_python_worker=False)
    session = SageSession("integration-security", settings)
    try:
        with pytest.raises(SageEvaluationError) as excinfo:
            await session.evaluate(
                "import os\nos.system('echo blocked')",
                want_latex=False,
                capture_stdout=False,
            )
        assert excinfo.value.error_type == "SecurityViolation"

        # Session should still respond to subsequent evaluations.
        follow_up = await session.evaluate("2 + 2", want_latex=False, capture_stdout=False)
        assert follow_up.result == "4"
    finally:
        await session.shutdown()


@requires_sage
@pytest.mark.asyncio
async def test_server_monitoring_resource_with_real_sage(monkeypatch):
    settings = SageSettings(force_python_worker=False)
    manager = SageSessionManager(settings)
    monkeypatch.setattr(runtime, "SESSION_MANAGER", manager)
    reset_metrics()
    ctx = FakeContext("integration-monitoring")

    try:
        success = await server.evaluate_sage("factorial(6)", ctx=ctx)
        assert success.result == "720"

        # The refusal has to be one the policy still makes: a bare `import os`
        # binds a name nothing reads, and an import that would change nothing is
        # dropped rather than refused now.
        with pytest.raises(server.ToolError):
            await server.evaluate_sage("import os\nos.getuid()", ctx=ctx)

        raw = await server.monitoring_resource("metrics", None)
        assert raw
        snapshot = json.loads(raw)
        assert snapshot["successes"] >= 1
        assert snapshot["failures"] >= 1
        assert snapshot["security_failures"] >= 1
    finally:
        await manager.shutdown()


@requires_sage
@pytest.mark.asyncio
async def test_monitoring_metrics_on_timeout(monkeypatch):
    """Validate monitoring metrics capture timeout from a real Sage session."""
    settings = SageSettings(force_python_worker=False, eval_timeout=1.0)
    manager = SageSessionManager(settings)
    monkeypatch.setattr(runtime, "SESSION_MANAGER", manager)
    reset_metrics()
    ctx = FakeContext("integration-timeout")

    try:
        # Run a computation that exceeds the 1s timeout
        # NOT "import time; time.sleep(10)": callers cannot import any more, so
        # that raises SecurityViolation -- which is also a ToolError, so this
        # test would have kept passing while no longer testing a timeout at all.
        # A long pure-Sage computation is the honest way to exceed the deadline.
        with pytest.raises(server.ToolError, match="timed out"):
            await server.evaluate_sage(
                "total = 0\nfor i in range(10**9):\n    total += i\ntotal", ctx=ctx
            )

        raw = await server.monitoring_resource("metrics", None)
        assert raw
        snapshot = json.loads(raw)
        assert snapshot["failures"] >= 1
        # The resource no longer carries the free-text error (item 58); it is
        # kept only on the internal record for server-side logs.
        assert "last_error" not in snapshot
        from sagemath_mcp import monitoring as _monitoring

        assert _monitoring.snapshot()["last_error"] is not None
    finally:
        await manager.shutdown()


@requires_sage
@pytest.mark.asyncio
async def test_monitoring_metrics_on_cancellation(monkeypatch):
    """Validate monitoring metrics capture cancellation from a real Sage session."""

    settings = SageSettings(force_python_worker=False)
    manager = SageSessionManager(settings)
    monkeypatch.setattr(runtime, "SESSION_MANAGER", manager)
    reset_metrics()
    ctx = FakeContext("integration-cancel")

    try:
        # First do a successful eval to establish the session
        result = await server.evaluate_sage("1 + 1", ctx=ctx)
        assert result.result == "2"

        # Cancel the session and verify monitoring
        await server.cancel_sage_session(ctx=ctx)

        raw = await server.monitoring_resource("metrics", None)
        assert raw
        snapshot = json.loads(raw)
        assert snapshot["successes"] >= 1
    finally:
        await manager.shutdown()


@requires_sage
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("equation", "function", "variable", "expected"),
    [
        # The documented form from the tool's own docstring. This is the exact
        # call reported in issue #12.
        ("diff(y(x), x) + y(x) = cos(x)", "y", "x", ("_C", "cos(x)", "sin(x)")),
        # The bare form, which worked before the fix and must keep working:
        # the fix must not simply trade one broken spelling for another.
        ("diff(y, x) + y = cos(x)", "y", "x", ("_C", "cos(x)", "sin(x)")),
        # Second order, both spellings.
        ("diff(y(x), x, 2) + y(x) = 0", "y", "x", ("_K1", "_K2")),
        ("diff(y, x, 2) + y = 0", "y", "x", ("_K1", "_K2")),
        # "==" takes the non-split branch through the generated code.
        ("diff(y(x), x) == y(x)", "y", "x", ("_C", "e^x")),
        # The applied/bare handling must not assume the names y and x.
        ("diff(f(t), t) = f(t)", "f", "t", ("_C", "e^t")),
        ("diff(y(x), x) = x*y(x)", "y", "x", ("_C", "e^")),
    ],
)
async def test_solve_ode_equation_forms(monkeypatch, equation, function, variable, expected):
    """Regression test for #12: solve_ode rejected the documented "y(x)" form.

    The generated Sage code bound the dependent name to the *applied*
    expression y(x), so "y(x)" in the user's equation became "(y(x))(x)" and
    Sage raised "Substitution using function-call syntax and unnamed arguments
    has been removed". Every spelling below must now solve.
    """

    settings = SageSettings(force_python_worker=False)
    manager = SageSessionManager(settings)
    monkeypatch.setattr(runtime, "SESSION_MANAGER", manager)
    ctx = FakeContext("integration-ode-forms")

    try:
        result = await server.solve_ode(
            equation, function=function, variable=variable, ctx=ctx
        )
        solution = str(result["solution"])

        # The exact failure reported in #12 must not resurface.
        assert "Substitution using function-call syntax" not in solution
        for fragment in expected:
            assert fragment in solution, f"{fragment!r} missing from {solution!r}"
    finally:
        await manager.shutdown()


@requires_sage
@pytest.mark.asyncio
async def test_solve_ode_applied_and_bare_agree(monkeypatch):
    """#12: the two spellings describe one ODE, so they must solve identically."""

    settings = SageSettings(force_python_worker=False)
    manager = SageSessionManager(settings)
    monkeypatch.setattr(runtime, "SESSION_MANAGER", manager)
    ctx = FakeContext("integration-ode-agree")

    try:
        applied = await server.solve_ode(
            "diff(y(x), x) + y(x) = cos(x)", function="y", variable="x", ctx=ctx
        )
        bare = await server.solve_ode(
            "diff(y, x) + y = cos(x)", function="y", variable="x", ctx=ctx
        )
        assert str(applied["solution"]) == str(bare["solution"])
    finally:
        await manager.shutdown()


@requires_sage
@pytest.mark.asyncio
async def test_large_result_exceeds_asyncio_default_stream_limit():
    """A result larger than asyncio's 64 KiB default must survive the round trip.

    One JSON response is read with a single readline(), so the whole payload
    has to fit in the subprocess stream buffer. With asyncio's default limit
    this raised LimitOverrunError, which is what broke plot3d_expression: its
    base64 PNG is around 100 KiB.
    """

    settings = SageSettings(force_python_worker=False)
    session = SageSession("integration-large-result", settings)
    try:
        # Comfortably past the 64 KiB default.
        result = await session.evaluate(
            "'x' * 200000", want_latex=False, capture_stdout=False
        )
        assert result.result is not None
        assert len(result.result) >= 200000
    finally:
        await session.shutdown()


@requires_sage
@pytest.mark.asyncio
async def test_interrupt_preserves_state_with_real_sage(monkeypatch):
    """Interrupt against a real Sage worker, not the pure-Python shim.

    Sage installs its own signal handling during startup, so the pure-Python
    worker passing this is not evidence that Sage does.
    """
    settings = SageSettings(force_python_worker=False, eval_timeout=120.0)
    manager = SageSessionManager(settings)
    monkeypatch.setattr(runtime, "SESSION_MANAGER", manager)
    ctx = FakeContext("integration-interrupt")

    try:
        await server.evaluate_sage("treasure = factorial(20)", ctx=ctx)

        async def long_running():
            with pytest.raises(server.ToolError):
                await server.evaluate_sage("sum(k for k in range(10**9))", ctx=ctx)

        task = asyncio.create_task(long_running())
        await asyncio.sleep(1.5)
        result = await server.interrupt_sage_session(ctx=ctx)
        assert "state preserved" in result.message
        await task

        # The namespace must have survived the interrupt.
        kept = await server.evaluate_sage("treasure", ctx=ctx)
        assert kept.result == str(factorial_20())
    finally:
        await manager.shutdown()


def factorial_20() -> int:
    result = 1
    for value in range(2, 21):
        result *= value
    return result


@requires_sage
@pytest.mark.asyncio
async def test_named_sessions_isolated_with_real_sage(monkeypatch):
    settings = SageSettings(force_python_worker=False, eval_timeout=120.0)
    manager = SageSessionManager(settings)
    monkeypatch.setattr(runtime, "SESSION_MANAGER", manager)
    ctx = FakeContext("integration-named")

    try:
        await server.evaluate_sage("E = EllipticCurve([0,-1])", session="curves", ctx=ctx)
        await server.evaluate_sage("G = graphs.PetersenGraph()", session="graphs", ctx=ctx)

        rank = await server.evaluate_sage("E.rank()", session="curves", ctx=ctx)
        assert rank.result == "0"
        order = await server.evaluate_sage("G.order()", session="graphs", ctx=ctx)
        assert order.result == "10"

        # Each workspace sees only its own definitions.
        with pytest.raises(server.ToolError):
            await server.evaluate_sage("E.rank()", session="graphs", ctx=ctx)

        listed = await server.list_sage_sessions(ctx=ctx)
        assert {entry["name"] for entry in listed["sessions"]} == {"curves", "graphs"}
    finally:
        await manager.shutdown()


@requires_sage
@pytest.mark.asyncio
async def test_streaming_emits_output_before_completion(monkeypatch):
    """A progress event must arrive while the computation is still running.

    The tool used to await the whole evaluation and only then split the
    accumulated stdout, so nothing reached the caller until the work had already
    finished. Printing a marker, computing for several seconds, then printing a
    second marker distinguishes the two: with real streaming the first event
    lands well before the result.
    """
    settings = SageSettings(force_python_worker=False, eval_timeout=120.0)
    manager = SageSessionManager(settings)
    monkeypatch.setattr(runtime, "SESSION_MANAGER", manager)
    ctx = FakeContext("integration-streaming")

    code = (
        "print('FIRST')\n"
        "total = 0\n"
        "for i in range(3 * 10**6):\n"
        "    total += i\n"
        "print('SECOND')\n"
        "total"
    )

    started = time.monotonic()
    first_event_at: list[float] = []

    original = ctx.report_progress

    async def timed(progress, total=None, message=None):
        if not first_event_at:
            first_event_at.append(time.monotonic() - started)
        await original(progress, total, message)

    ctx.report_progress = timed

    try:
        result = await server.evaluate_sage_streaming(code, ctx=ctx)
        finished = time.monotonic() - started

        messages = [event[2] for event in ctx.progress_events]
        assert "FIRST" in messages and "SECOND" in messages
        assert result.result is not None

        assert first_event_at, "no progress event was emitted at all"
        # The first line must not have waited for the whole computation.
        assert first_event_at[0] < finished * 0.9, (
            f"first event at {first_event_at[0]:.2f}s of a {finished:.2f}s run: "
            "output was buffered until completion"
        )
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
@requires_sage
async def test_is_convex_distinguishes_a_concave_polygon(sage_manager):
    """is_convex must test the polygon given, not its convex hull.

    Polyhedron(vertices=...) builds the hull and discards the ordering, and
    is_compact() is true for every bounded polytope -- so the answer was True
    for all input, concave included.
    """
    ctx = FakeContext("convexity")
    square = [[0, 0], [2, 0], [2, 2], [0, 2]]
    dart = [[0, 0], [4, 0], [2, 1], [4, 4], [0, 4]]      # (2,1) dents inward

    convex = await server.geometry_operation(
        operation="is_convex", points=square, ctx=ctx
    )
    concave = await server.geometry_operation(
        operation="is_convex", points=dart, ctx=ctx
    )
    assert convex["result"] is True
    assert concave["result"] is False, "a concave polygon was reported convex"



@pytest.mark.asyncio
@requires_sage
async def test_is_convex_rejects_a_self_intersecting_polygon(sage_manager):
    """A pentagram turns the same way at every vertex and is not convex.

    Convexity is only defined for a simple polygon, so consistent turn direction
    on its own answered a question the input did not pose.
    """
    ctx = FakeContext("convexity")
    pentagram = [[0, 3], [2, -3], [-3, 1], [3, 1], [-2, -3]]
    result = await server.geometry_operation(
        operation="is_convex", points=pentagram, ctx=ctx
    )
    assert result["result"] is False, "a self-intersecting polygon was reported convex"


@pytest.mark.asyncio
@requires_sage
async def test_matrix_determinant_stays_exact_past_the_safe_integer(sage_manager):
    """diag(2^53+1, 1) has determinant 2^53+1, which a double cannot hold."""
    ctx = FakeContext("exact-matrix")
    result = await server.matrix_operation(
        matrix=[["9007199254740993", "0"], ["0", "1"]],
        operation="determinant",
        ctx=ctx,
    )
    assert result["result"] == "9007199254740993"

    # Ordinary float matrices keep behaving exactly as before.
    floats = await server.matrix_operation(
        matrix=[[1.5, 0.0], [0.0, 2.0]], operation="determinant", ctx=ctx
    )
    assert floats["result"] == pytest.approx(3.0)
    assert isinstance(floats["result"], float)


SAGE_SEMANTICS = [
    ("2^3", "8"),                                   # power, not XOR
    ("x", "x"),                                     # the REPL predefines x
    ("integrate(sin(x), x)", "-cos(x)"),
    ("K.<a> = NumberField(x^3 - 2); K.class_number()", "1"),   # preparser-only syntax
    ("type(2)", "<class 'sage.rings.integer.Integer'>"),       # Sage Integer, not int
]


@pytest.mark.parametrize("code,expected", SAGE_SEMANTICS, ids=[c for c, _ in SAGE_SEMANTICS])
@pytest.mark.asyncio
@requires_sage
async def test_evaluate_sage_runs_sage_not_python(code, expected, real_sage_manager):
    """The tool says SageMath; it used to execute plain Python.

    `2^3` returned 1 because `^` is XOR in Python, `K.<a> = ...` was a syntax
    error, and integer literals were machine ints. The specialised tools always
    preparsed via sage_eval, so the two halves of the server disagreed about
    which language they accepted.
    """
    result = await server.evaluate_sage(code=code, ctx=FakeContext("preparse"))
    assert result.result == expected


@pytest.mark.asyncio
@requires_sage
async def test_preparsing_does_not_open_a_way_past_the_policy(real_sage_manager):
    """Validation reads the preparsed source, so payloads cannot hide in syntax
    the validator could not previously parse."""
    from fastmcp.exceptions import ToolError

    for payload in (
        "R.<a> = QQ[]; __import__('os').getuid()",
        "f = open\nf('/etc/passwd').readline()",
        "m = os\nm.getuid()",
    ):
        with pytest.raises(ToolError):
            await server.evaluate_sage(code=payload, ctx=FakeContext("preparse-sec"))


@requires_sage
@pytest.mark.asyncio
async def test_sage_helpers_that_execute_code_are_unreachable():
    """The namespace scrub, against the real Sage namespace.

    `cython(get_remote_file(url))` was download, compile and execute in one
    expression, and `sh` runs a shell. None of it involved a name any rule
    mentioned, which is why the scrub works by provenance rather than by list.
    """
    from sagemath_mcp._sage_worker import _build_namespace

    namespace = _build_namespace()
    reachable = [
        name
        for name in (
            "cython", "cython_lambda", "fortran", "sh", "get_remote_file",
            "loads", "dumps", "save", "load", "attach", "sage_eval", "sageobj",
            "trace", "edit", "db", "db_save", "tmp_dir", "tmp_filename",
        )
        if name in namespace
    ]
    assert not reachable, f"dangerous Sage helpers still in the namespace: {reachable}"

    # And the mathematics is untouched.
    for needed in ("Integer", "ZZ", "QQ", "matrix", "plot", "EllipticCurve", "SR"):
        assert needed in namespace, f"{needed} was removed with the dangerous names"


@requires_sage
@pytest.mark.asyncio
async def test_external_interfaces_are_not_in_the_namespace():
    """Everything sage.interfaces.all exports spawns another program.

    gp and maxima both executed shell commands through their own `system`
    escapes. Stripping Sage's own export list covers the ones a hand-written
    list would miss, including anything a future release adds.
    """
    import sage.interfaces.all as interfaces

    from sagemath_mcp._sage_worker import _build_namespace

    namespace = _build_namespace()
    exported = {name for name in vars(interfaces) if not name.startswith("_")}
    still_reachable = sorted(exported & set(namespace))
    assert not still_reachable, f"external interfaces reachable: {still_reachable}"


@requires_sage
@pytest.mark.asyncio
async def test_mathematics_that_uses_singular_and_pari_still_works(real_sage_manager):
    """Removing the interface OBJECTS must not touch the libraries.

    Sage computes Gröbner bases through libsingular and factors through PARI
    in-process; only the subprocess interfaces were removed.
    """
    ctx = FakeContext("libraries")
    groebner = await server.polynomial_ring_operation(
        ring_vars=["a", "b"], polynomials=["a^2+b", "b^2-1"],
        operation="groebner_basis", ctx=ctx,
    )
    assert groebner["result"] == ["a^2 + b", "b^2 - 1"]

    factored = await server.number_theory_operation(
        operation="factor_integer", a="18446744073709551617", ctx=ctx
    )
    assert "274177" in str(factored["result"])


@requires_sage
@pytest.mark.asyncio
async def test_the_baked_in_denylist_still_matches_this_sage():
    """The list is baked in for speed; this is what keeps it true.

    Deriving it at every worker start cost enough on slow hardware to push the
    first evaluation past its timeout. So the names are a literal, and this
    re-derives them from the installed Sage: a version that adds, renames or
    moves a helper fails here rather than quietly leaving it reachable.
    """
    from sagemath_mcp._sage_worker import (
        _DANGEROUS_SAGE_NAME_LIST,
        _dangerous_sage_names,
    )

    derived = _dangerous_sage_names()
    missing = sorted(derived - _DANGEROUS_SAGE_NAME_LIST)
    assert not missing, (
        "this Sage defines dangerous helpers the baked-in list does not cover: "
        f"{missing}. Adding a module to _DANGEROUS_SAGE_MODULES does not strip "
        f"anything until the baked list is rebuilt: run `make denylist`."
    )


@requires_sage
def test_every_dangerous_module_actually_contributes_a_name():
    """A provenance entry that matches nothing is worse than no entry.

    `_dangerous_sage_names` takes only names *defined* in each listed module --
    "defined here, not merely imported here", because `sage.misc.persist` also
    has `Integer` in scope and removing that would break the mathematics. The
    consequence is that listing a module whose names are defined elsewhere
    silently protects nothing while looking like protection.

    That happened: `sage.libs.pari.all` was added after `pari('system("id")')`
    was found to run a shell, and it contributed zero names, because `pari`,
    `pari_gen` and `PariError` are all defined in `cypari2`. The removal that
    actually worked was the explicit one. This fails if anyone adds another
    entry that matches nothing.
    """
    import importlib

    from sagemath_mcp._sage_worker import _DANGEROUS_SAGE_MODULES

    barren = []
    for module_name in _DANGEROUS_SAGE_MODULES:
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue  # not installed in this Sage; not this test's business
        package = module_name.rsplit(".", 1)[0]
        defined = [
            name
            for name, value in vars(module).items()
            if not name.startswith("_")
            and isinstance(home := getattr(value, "__module__", None), str)
            and home.startswith(package)
        ]
        if not defined:
            barren.append(module_name)

    assert not barren, (
        f"these modules are listed as dangerous but define none of the names in "
        f"them, so listing them protects nothing: {barren}. Either name the module "
        f"the objects are really defined in, or remove the entry and use "
        f"_DANGEROUS_BARE_NAMES, which removes by name and demonstrably works."
    )


@requires_sage
@pytest.mark.asyncio
async def test_the_caller_allowlist_matches_this_sage():
    """The allowlist is baked in; this is what keeps it honest.

    Two directions, and they mean different things:

    * **Additions** — names this SageMath offers that the list does not. Callers
      cannot reach them, so a Sage upgrade quietly loses functionality. Each one
      needs a look before it is added: this is the review step the whole
      deny-by-default design exists to create.
    * **Removals** — names the list allows that no longer exist. Harmless to
      security (reading one is a NameError either way) but the list has gone
      stale, and stale is how a list stops being read.

    Regenerate with the snippet in the failure message, then review the diff.
    """
    import math

    from sagemath_mcp._sage_worker import (
        _CALLER_SHIMS,
        _build_namespace,
        _restricted_builtins,
    )
    from sagemath_mcp.allowlist import ALLOWED_CALLER_NAMES

    namespace = _build_namespace()
    live_including_dunders = set(namespace) | set(_restricted_builtins())

    # The caller shims are deliberately live and deliberately off the allowlist,
    # because they replace a scrubbed Sage global with a safe stand-in rather
    # than an allowlisted object (item 64):
    #   `attrcall`     -- the worker's *guarded* wrapper (item 59). The validator
    #                     permits exactly one spelling, the screened literal call;
    #                     every other read is refused by the forbidden-name rule,
    #                     which consults neither the allowlist nor the bindings.
    #   `set_verbose`  -- a no-op, offered outright (harmless) via
    #                     `_OFFERED_SHIM_NAMES`, not through the generated list.
    # Their protection does not depend on the gap below being empty, so they are
    # excluded rather than allowlisted.
    guarded = frozenset(_CALLER_SHIMS)

    # What is live but not allowlisted must be dunders and nothing else. A
    # caller binding is trusted without consulting the allowlist, so anything
    # sitting in this gap is reachable by binding the name in a branch that
    # never runs. Dunders are safe there only because reading one is blocked
    # outright and `_bound_names` refuses to record them; a non-dunder arriving
    # here in a future Sage would have neither protection.
    gap = sorted(n for n in live_including_dunders - ALLOWED_CALLER_NAMES - guarded
                 if not n.startswith("__"))
    assert not gap, (
        f"these names are live in the worker namespace but not on the allowlist, "
        f"and are not dunders: {gap}. Either allowlist them or scrub them from "
        f"the namespace -- leaving them here makes them reachable by binding the "
        f"name in an unexecuted branch."
    )

    live = {name for name in namespace if not name.startswith("_")}
    live |= {name for name in _restricted_builtins() if not name.startswith("_")}
    # The generator also covers the pure-Python worker's `from math import *`, so
    # the comparison has to include those or every one of them reads as drift.
    live |= {name for name in vars(math) if not name.startswith("_")}

    additions = sorted(live - ALLOWED_CALLER_NAMES - guarded)
    removals = sorted(ALLOWED_CALLER_NAMES - live)

    assert not additions, (
        f"this SageMath offers {len(additions)} names the allowlist does not cover, "
        f"so callers cannot use them: {additions[:20]}"
        "\n\nReview each one -- a new helper that compiles, spawns or writes belongs "
        "in _DANGEROUS_SAGE_MODULES instead -- then regenerate through a temp "
        "file (the generator imports allowlist.py, so redirecting straight over "
        "it truncates its own input):\n"
        "  docker exec sage-mcp bash -lc 'cd /workspace && sage -python "
        "scripts/generate_allowlist.py > /tmp/allowlist_new.py'\n"
        "  docker exec sage-mcp cat /tmp/allowlist_new.py "
        "> src/sagemath_mcp/allowlist.py"
    )
    assert not removals, (
        f"the allowlist names {len(removals)} things this SageMath no longer has, "
        f"so it has drifted: {removals[:20]}"
    )


@requires_sage
def test_the_star_exports_match_this_sage():
    """The vetted star-import lists are baked in; this keeps them honest.

    Every module in `star_exports.py` is re-screened against the installed Sage
    with the same function the generator used. A version that adds a name
    reaching a shell, compiler, pickle or file to a listed module turns its
    screen result to None -- clean-modules-only -- and this test fails, naming
    the module, rather than the new name becoming reachable through the star.

    Regenerate with the snippet in scripts/generate_star_exports.py and review
    the diff.
    """
    from sagemath_mcp._sage_worker import _star_export_screen
    from sagemath_mcp.star_exports import STAR_EXPORTS

    drift = {}
    for module_name, baked in STAR_EXPORTS.items():
        screened = _star_export_screen(module_name)
        if screened != baked:
            drift[module_name] = (
                "no longer screens clean" if screened is None
                else {
                    "added": sorted(screened - baked),
                    "removed": sorted(baked - screened),
                }
            )
    assert not drift, (
        f"the baked star-export lists disagree with this SageMath: {drift}. "
        "Regenerate with scripts/generate_star_exports.py and review the diff."
    )
