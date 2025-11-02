# TODO

- [x] Add more integration tests that cover new functionality you introduced.
- [x] Update documentation to cover the new functionality.
- [x] Review best practices and usability rules (monitoring surfaced; security policy documented).
- [x] Raise server.py coverage (monitoring resource, helper tool edge cases, error paths).
- [x] Expand security policy tests for custom policies/logging.
- [x] Add rich MCP client quickstarts and prompt cookbook docs.
- [x] Capture enhanced monitoring diagnostics (recent error message/stack) and test them.
- [x] Automate release packaging (wheels for py311/py312/py313, GitHub Actions publish to PyPI).
- [x] Improve Windows/macOS onboarding (PowerShell helper, M1 notes).
- [x] Provide container image or documentation updates after automation wrap-up.
- [x] Add configuration parsing tests (invalid env values for floats/ints/bools).
- [x] Exercise `_evaluate_structured` error paths and helper tool fallbacks.
- [ ] Build and publish a Docker image via CI (ghcr.io) alongside PyPI release.
- [ ] Add CLI reference (arguments/help output) to docs and README.
- [ ] Add integration test ensuring monitoring metrics capture timeout/cancellation cases from a real Sage run.
- [ ] Update Helm `values.yaml` defaults once the GHCR image is published.
