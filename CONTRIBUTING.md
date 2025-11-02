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
3. **Optional** – start the Sage container for integration tests:
   ```bash
   make sage-container
   ```

## Development Workflow

- Create a feature branch (`git checkout -b feature/my-change`).
- Run `uv run ruff check` and `uv run pytest` before submitting changes.
- For Sage-backed tests, run `make integration-test` (requires the Docker container).
- Follow the project’s [Agent Playbook](AGENTS.md) and [Testing Guide](TESTING.md) for tips on helper scripts and CI requirements.

## Coding Standards

- Python 3.11+ with Ruff enforcing PEP 8 and companion rules; line length ≤100.
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

- Follow the instructions in [DISTRIBUTION.md](DISTRIBUTION.md) for PyPI and container releases.
- Tag releases using `vX.Y.Z` to trigger the GitHub Actions workflows.

## Community Expectations

Participation in this project is governed by our [Code of Conduct](CODE_OF_CONDUCT.md). Please review it before engaging with the community.

## Questions?

Open a discussion or issue on GitHub, or reach out to the maintainers at sagemath-mcp-maintainers@proton.me. We’re happy to help!
