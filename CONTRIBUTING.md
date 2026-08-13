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

## Coding Standards

- Python 3.12+ with Ruff enforcing PEP 8 and companion rules; line length ≤100.
- Mirror new modules with tests under `tests/`.
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
