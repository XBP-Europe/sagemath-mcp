"""A session's code journal on disk: where it lives, writing it, replaying it."""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import re
from pathlib import Path

from .errors import SageProcessError

# The session logger, not this module's own: these lines were logged under
# `sagemath_mcp.session` before the 2026-09 split and still are.
LOGGER = logging.getLogger("sagemath_mcp.session")


# Subdirectory holding journals written by the current naming scheme.
_JOURNAL_NAMESPACE = "v2"


def _journal_entry(item) -> tuple[str, bool]:
    """Read one journal entry, in either the old or the current shape.

    Journals written before trust was recorded are plain strings. Those predate
    the specialized tools ever being replayable, so untrusted is both the safe
    reading and the accurate one.
    """
    if isinstance(item, dict):
        return item.get("code", ""), bool(item.get("trusted", False))
    return str(item), False


class JournalMixin:
    """Persisting a session's code journal, and replaying it.

    Mixed into `SageSession`, which provides `session_id`, `settings`,
    `_code_journal` and `evaluate`. Kept apart because persistence is its own
    subject -- file naming, legacy paths, crash-safe writes -- and none of it
    touches the worker process.
    """

    def _persist_path(self) -> Path | None:
        """Return the journal file path if persistence is enabled."""
        if not self.settings.persist_sessions or not self.settings.persist_dir:
            return None
        # Versioned namespace: digest-named files live in their own directory
        # so they cannot collide with a legacy flat file that happens to share a
        # name, and so a future scheme change is a new directory rather than
        # another round of ambiguity.
        d = Path(self.settings.persist_dir) / _JOURNAL_NAMESPACE
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{self._journal_stem()}.journal.json"

    def _legacy_persist_paths(self) -> list[Path]:
        """Journal paths written by earlier versions of this code.

        Two schemes preceded the digest: the raw session id, and a lossy
        sanitisation of it. Both are still on disk for anyone upgrading, and
        without this the rename silently orphans every persisted session --
        including plain default ones, whose filename was previously just the
        session id.
        """
        if not self.settings.persist_sessions or not self.settings.persist_dir:
            return []
        d = Path(self.settings.persist_dir)
        # The un-namespaced digest file, from the scheme between the two. The
        # digest covers the whole session id, so this one names its owner
        # unambiguously and is always safe to adopt.
        candidates = [d / f"{self._journal_stem()}.journal.json"]
        # The oldest scheme sanitised unsafe characters away, which is exactly
        # why it was replaced: "a/b" and "a?b" both wrote "a_b.journal.json".
        # Adopting such a file would be guessing whose state it is, so fall back
        # only when the sanitisation changed nothing and the name proves identity.
        sanitized = re.sub(r"[^A-Za-z0-9._-]", "_", self.session_id)
        if sanitized == self.session_id and self.session_id:
            candidates.append(d / f"{self.session_id}.journal.json")
        seen: set[Path] = set()
        return [p for p in candidates if not (p in seen or seen.add(p))]

    def _discard_persisted_journal(self) -> None:
        """Delete the on-disk journal, so a reset is not undone by a replay.

        `reset()` used to clear only the in-memory journal. `get()` restores
        from disk whenever the in-memory one is empty, and every worker-backed
        tool call goes through `get()` -- so the statements the caller had just
        discarded came back on the next call, including any flagged trusted,
        with no signal. Someone resetting to drop sensitive intermediates got
        them back immediately. The tool is annotated destructive and documented
        as clearing state; this makes that true when persistence is on.

        Legacy paths are removed too: `existing_journal_path` falls back to them
        on restore, so leaving one behind would reopen the same hole.
        """
        failed: list[str] = []
        for path in (self._persist_path(), *self._legacy_persist_paths()):
            if path is None:
                continue
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                # FAIL LOUD. Suppressing this left the journal in place while
                # `reset_sage_session` still reported success, and the next
                # call replayed it -- which is the exact failure the deletion
                # was added to fix. A caller who asked to discard state is
                # entitled to know it did not happen (REVIEW_ACTIONS 87).
                failed.append(f"{path}: {exc}")
        if failed:
            raise SageProcessError(
                "Session state was cleared in memory but the persisted journal "
                "could not be deleted, so it will be replayed on the next call: "
                + "; ".join(failed)
            )

    def existing_journal_path(self) -> Path | None:
        """The journal to restore from, preferring the current scheme."""
        current = self._persist_path()
        if current is not None and current.exists():
            return current
        for legacy in self._legacy_persist_paths():
            if legacy.exists():
                LOGGER.info(
                    "Restoring %s from a legacy journal path (%s)", self.session_id, legacy.name
                )
                return legacy
        return None

    def _journal_stem(self) -> str:
        """A filename that is unique per session id.

        Replacing every unsafe character with "_" was not injective: the
        workspaces "a/b" and "a?b" both became "a_b", so one could overwrite the
        other's journal and later restore the wrong code into its namespace.

        A readable prefix keeps the files identifiable while a digest of the
        full id guarantees distinct keys get distinct paths.
        """
        readable = re.sub(r"[^A-Za-z0-9._-]", "_", self.session_id)[:48]
        digest = hashlib.sha256(self.session_id.encode("utf-8")).hexdigest()[:12]
        return f"{readable}-{digest}"

    def save_journal(self) -> None:
        """Write the code journal to disk for later restoration.

        Order matters. The legacy file used to be deleted first, so a write that
        failed afterwards -- a full disk, a read-only mount -- destroyed the old
        journal and left a stray .tmp behind, having saved nothing. The new file
        is written and put in place first; only then is the superseded one
        retired, and a failed attempt cleans up after itself.
        """
        path = self._persist_path()
        if path is None:
            return

        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        try:
            tmp.write_text(
                json.dumps([{"code": code, "trusted": trusted}
                            for code, trusted in self._code_journal])
            )
            os.replace(tmp, path)
        except OSError:
            with contextlib.suppress(OSError):
                tmp.unlink()
            LOGGER.warning(
                "Could not save journal for %s; the previous one is untouched",
                self.session_id,
            )
            raise

        # Only now that the new journal exists: retire the pre-digest files so
        # the two naming schemes cannot diverge.
        for legacy in self._legacy_persist_paths():
            if legacy != path and legacy.exists():
                with contextlib.suppress(OSError):
                    legacy.unlink()
        LOGGER.debug("Saved journal for %s (%d entries)", self.session_id, len(self._code_journal))

    @classmethod
    def load_journal(cls, path: Path) -> list[str]:
        """Read a code journal from disk."""
        return json.loads(path.read_text())

    async def restore_from_journal(self, journal: list) -> int:
        """Replay saved code entries to rebuild session state.

        Each entry carries the trust mode it originally ran under. Blessing
        every entry instead would put caller code on the trusted path, which is
        the one thing the policy split exists to prevent; refusing every entry
        (the previous behaviour) broke restoration for any session that had used
        a specialized tool.

        Returns the number of entries successfully replayed.
        """
        replayed = 0
        for code, trusted in (_journal_entry(item) for item in journal):
            try:
                await self.evaluate(
                    code, want_latex=False, capture_stdout=False, trusted=trusted
                )
                replayed += 1
            except Exception:
                LOGGER.warning(
                    "Journal replay failed at entry %d for %s",
                    replayed, self.session_id,
                )
                break
        return replayed
