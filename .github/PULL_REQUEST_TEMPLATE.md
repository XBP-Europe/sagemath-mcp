## Summary

- [ ] Title is descriptive and uses the imperative mood.
- [ ] Linked issues or Pull Requests (if applicable).

## Changes

- Describe the main changes in this PR.
- Highlight any breaking changes or notable follow-ups.

## Testing

- [ ] `uv run pytest` (coverage is gated at 100%, statements and branches)
- [ ] `uv run ruff check` — the bare command, as CI runs it
- [ ] `make integration-test` (if Sage container available)
- [ ] Ran against **real SageMath**, not only the pure-Python worker, if behaviour changed
- [ ] Other (specify): <!-- e.g. make cli-extended, compose smoke test -->

## Checklist

- [ ] Documentation updated (README, USAGE, etc.) where needed.
- [ ] Added/updated tests covering changes.
- [ ] If a tool changed: snapshot regenerated (`python -m tests.test_tool_inventory --write`) and the diff reviewed.
- [ ] If a security rule changed: the regression test was confirmed to **fail first**, and `tests/test_math_coverage.py` still passes — every security test asserts something is *blocked*, so they cannot tell "secure" from "refuses everything".
- [ ] If the worker namespace or the Sage version changed: `make allowlist` run and **every added name reviewed** — each one is a name every caller can then use.
- [ ] If dependencies changed: `uv lock` run and the lockfile committed.
- [ ] Verified non-root container behavior if deployment assets changed.
- [ ] Confirmed CODEOWNERS and reviewers.
