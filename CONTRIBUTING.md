# Contributing to SageMath MCP

Thank you for your interest in improving the SageMath MCP server! This guide explains how to get started, the coding standards we follow, and how to submit changes.

## Getting Started

1. **Fork & Clone**
   ```bash
   git clone https://github.com/<your-user>/sagemath-mcp.git
   cd sagemath-mcp
   ```
2. **Create a virtual environment and install dependencies**
   ```bash
   uv pip install -e .[dev]
   ```
   Configure Git hooks so lint runs before every push:
   ```bash
   git config core.hooksPath .githooks
   ```
3. **Optional** – start the Sage container for integration tests:
   ```bash
   make sage-container
   ```

## Development Workflow

- Create a feature branch (`git checkout -b feature/my-change`) from `main` (the default branch).
- Open pull requests against `main` and rebase onto the latest `origin/main` before submission.
- Run `uv run ruff check` and `uv run pytest` before submitting changes.
- For Sage-backed tests, run `make integration-test` (requires the Docker container).
- Follow the project’s [Agent Playbook](AGENTS.md) and [Testing Guide](TESTING.md) for tips on helper scripts and CI requirements.

## What CI enforces

These are the checks that fail a pull request. None of them are obvious from the
code, so they are listed here rather than discovered.

- **100% coverage, statements and branches.** `--cov-fail-under=100` runs in the
  unit job. A new branch needs a test that reaches it; if a branch is genuinely
  unreachable, delete it rather than exempt it — that is how most of them were
  resolved.
- **The tool inventory is snapshotted.** Adding, renaming or re-describing a tool
  changes the MCP contract and fails `tests/test_tool_inventory.py`. Regenerate
  deliberately: `python -m tests.test_tool_inventory --write`, and expect the diff
  to be reviewed. Descriptions count — they are what makes a model choose a
  specialised tool over `evaluate_sage`.
- **Every version must agree**, including `uv.lock`. `scripts/bump_version.py`
  updates them together; `uv lock --check` runs in CI.
- **Caller strings may not reach generated code ungated.** Generated snippets run
  under a policy that permits `sage_eval`, so a parameter interpolated without
  `_encode_literal`, `_validated_expression` or `_validated_identifier` is
  arbitrary execution. A structural test fails if one appears.
- **README claims are tested.** The security table, the badge versions and the
  coverage number are all checked against the code and the workflows.
- **Documented examples must be exercised.** Anything quoted in a `Field(...)`
  description has to appear in a test — that rule exists because a documented
  spelling once shipped broken.
- **The allowlist must match the installed Sage.** `allowlist.py` is generated,
  and an integration test plus a weekly job fail when it and the running Sage
  disagree in either direction: names Sage offers that callers cannot reach, or
  names listed that no longer exist.
- **Every tool must be documented.** A tool absent from `USAGE.md` and
  `README.md` fails `tests/test_tool_inventory.py`. The usage table drifted by
  four tools once, including the one the same page recommends in prose.
- **A dangerous-module entry must remove something.** Listing a module in
  `_DANGEROUS_SAGE_MODULES` that defines none of its own names protects nothing
  while looking like protection; an integration test rejects that.

## Writing a security fix

The project has had several sandbox bypasses. The discipline that catches them:

1. **Reproduce first**, against real SageMath rather than the pure-Python shim —
   Sage installs its own signal handling, namespace and preparser, and several
   findings existed only there.
2. **Write the regression test and watch it fail** on the unfixed code. A test
   that passes before the fix is testing nothing, and that has happened here.
3. **Fix, then re-run the whole integration suite.** Tightening the policy is the
   easiest way to break legitimate mathematics.
4. **Record it in `REVIEW_ACTIONS.md`** with the reproduction and the fix, so the
   next person can see the shape of what has already been tried.

Two things specific to this codebase:

**Caller code is deny-by-default.** A name works only if `allowlist.py` offers it
or the caller's own code bound it, so the usual fix for a newly-found dangerous
name is to stop offering it rather than to add a rule. Regenerate with `make
allowlist` after any change to what the worker namespace contains — including a
Sage version bump — and read the diff, because every added name is a name every
caller can now use.

**Check you have not broken the mathematics.** Every test in
`tests/test_security_bypass.py` asserts something is *blocked*, so a policy that
refused everything would pass all of them. `tests/test_math_coverage.py` is the
other direction: binding forms, truths Sage evaluates, equivalent spellings and
preparser behaviour. Run both.

## Coding Standards

- Python 3.12+ with Ruff enforcing PEP 8 and companion rules; line length ≤100.
- Mirror new modules with tests under `tests/`.
- A new tool goes in the matching `src/sagemath_mcp/tools/` module and must be
  listed in `tools/__init__.py`; a module missing from that list registers nothing.
- Resolve workers through `runtime.resolve_session(...)`, never a module-level
  import of `SESSION_MANAGER`, which binds the manager that existed at import time.
- Use `SageSettings` to expose environment-driven configuration; avoid hard-coded toggles.
- Keep inline comments concise and only for non-obvious logic.

## Commit & PR Guidelines

- Use imperative, descriptive commit messages (e.g., “Add structured monitoring metrics”).
- Reference related issues in the PR description and list the tests you ran.
- Keep PRs focused; large changes should be split across multiple commits/PRs.
- Ensure documentation updates accompany user-facing changes.

## Reporting Bugs & Requesting Features

- Open an issue with clear reproduction steps or desired behavior.
- Include logs, test output, or context about your Sage environment where applicable.

## Releasing

`main` is protected and requires all CI checks, so a release cannot be pushed to it
directly. The flow is:

1. Run the **Version bump** workflow (`workflow_dispatch`) with the segment to bump. It
   updates `pyproject.toml`, `src/sagemath_mcp/__init__.py` and
   `charts/sagemath-mcp/Chart.yaml`, then opens a pull request.
2. Merge that pull request once CI passes.
3. Push the tag to publish:

   ```bash
   git tag vX.Y.Z && git push origin vX.Y.Z
   ```

Pushing the tag triggers `release.yml`, which publishes to PyPI, pushes a Cosign-signed
image to GHCR, and creates the GitHub release. **A PyPI version number can never be
reused**, so treat the tag push as the point of no return; if something is wrong the only
remedy is another version.

Record user-visible changes in [CHANGELOG.md](CHANGELOG.md) **before** tagging. Choose the
segment by whether *output* changes: a tool returning a different value than the previous
release is a minor bump even when the new value is the correction of a bug.

The changelog entry is not optional bookkeeping. The release job reads the
`## [VERSION]` section and uses it as the release notes; with no entry it falls back to
generated notes and logs a warning, so the release still ships but says nothing useful.

See [DISTRIBUTION.md](DISTRIBUTION.md) for the packaging details.

## Community Expectations

Participation in this project is governed by our [Code of Conduct](CODE_OF_CONDUCT.md). Please review it before engaging with the community.

## Questions?

Open a discussion or issue on GitHub, or reach out to the maintainers at sagemath-mcp-maintainers@proton.me. We’re happy to help!
