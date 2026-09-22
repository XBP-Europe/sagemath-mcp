"""What the monitoring metrics may disclose, and to whom.

`_METRICS` is a process-global singleton. The aggregate counters in it are
totals and say nothing about any one client, but the free-text fields hold a
*single* client's most recent failure -- its message, its rejected code, its
untruncated stdout. The monitoring resource is unscoped and, on the shipped
HTTP deployment, readable by any client, so publishing those fields hands one
caller another caller's inputs. That happened, and is item 58.

The fix for it removed three named fields. These tests are about the shape of
that fix rather than those three names: a denylist publishes anything added
later, which is the same enumeration items 79 and 92 had to abandon
elsewhere. See REVIEW_ACTIONS 95.
"""

from __future__ import annotations

# --- What may leave the process --------------------------------------------


def test_public_snapshot_withholds_a_field_nobody_listed() -> None:
    """The reason this is an allowlist.

    `public_snapshot` used to pop three named free-text fields and return
    everything else, so a field added to the metrics later would publish
    itself. Measured before the change: a planted `last_rejected_code` came
    straight through.

    It did not reach the wire — `MonitoringSnapshot` is a pydantic model and
    pydantic ignores unknown keys — but that is a default rather than a
    decision, and it is not the lock the docstring claimed. This asserts the
    claim the docstring makes (REVIEW_ACTIONS 95).
    """
    from unittest.mock import patch

    from sagemath_mcp import monitoring

    leaky = dict(monitoring.snapshot())
    leaky["last_rejected_code"] = "SECRET-FROM-ANOTHER-CLIENT"
    with patch.object(monitoring, "snapshot", return_value=leaky):
        public = monitoring.public_snapshot()

    assert "last_rejected_code" not in public
    assert "SECRET-FROM-ANOTHER-CLIENT" not in str(public)


def test_no_known_free_text_field_is_public() -> None:
    """`_CLIENT_TEXT_FIELDS` no longer drives the redaction, so it would be
    dead weight — except that it records *which* fields carry another
    client's message, rejected code and stdout, and why that matters
    (item 58). Keeping it load-bearing preserves that."""
    from sagemath_mcp.monitoring import _CLIENT_TEXT_FIELDS, _PUBLIC_FIELDS

    overlap = set(_CLIENT_TEXT_FIELDS) & set(_PUBLIC_FIELDS)
    assert not overlap, f"these carry per-client text and must not be public: {sorted(overlap)}"


def test_the_public_fields_are_exactly_the_model_fields() -> None:
    """`MonitoringSnapshot` is the wire contract. A field in the allowlist but
    not the model is silently dropped by pydantic — harmless but misleading.
    A field in the model but not the allowlist would raise at construction,
    which is a 500 on an observability endpoint."""
    from sagemath_mcp.models import MonitoringSnapshot
    from sagemath_mcp.monitoring import _PUBLIC_FIELDS

    assert set(_PUBLIC_FIELDS) == set(MonitoringSnapshot.model_fields)


def test_every_public_field_is_actually_produced() -> None:
    """An allowlist entry the metrics never emit is a field that silently
    vanishes from the resource. The comprehension skips missing keys, so
    without this the omission would be invisible."""
    from sagemath_mcp import monitoring

    produced = set(monitoring.snapshot())
    missing = sorted(set(monitoring._PUBLIC_FIELDS) - produced)
    assert not missing, f"listed as public but never measured: {missing}"


def test_the_counters_survive_concurrent_writers() -> None:
    """`_LOCK` is claimed to make these thread-safe, and the server does run
    evaluations concurrently. A lost update here would understate `attempts`
    against `successes + failures`, which is the number an operator uses to
    decide whether the server is healthy.

    Snapshots are taken from inside the race as well as after it: a reader
    that can observe a half-applied update is a different bug from one that
    loses a write, and only checking the total would miss it.
    """
    import random
    import threading

    from sagemath_mcp import monitoring

    monitoring.reset_metrics()
    try:
        failures: list[str] = []

        def worker(seed: int) -> None:
            rng = random.Random(seed)
            try:
                for _ in range(400):
                    roll = rng.random()
                    if roll < 0.5:
                        monitoring.record_success(rng.uniform(0, 100))
                    elif roll < 0.8:
                        monitoring.record_failure("boom", is_security=rng.random() < 0.5)
                    else:
                        seen = monitoring.public_snapshot()
                        assert seen["attempts"] >= seen["successes"] + seen["failures"], seen
                        assert seen["avg_elapsed_ms"] >= 0
            except Exception as exc:
                failures.append(f"{type(exc).__name__}: {exc}")

        threads = [threading.Thread(target=worker, args=(seed,)) for seed in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert not failures, failures
        final = monitoring.snapshot()
        assert final["attempts"] == final["successes"] + final["failures"], final
        assert final["security_failures"] <= final["failures"], final
    finally:
        monitoring.reset_metrics()
