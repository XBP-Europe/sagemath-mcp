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
- [x] Build and publish a Docker image via CI (ghcr.io) alongside PyPI release.
- [x] Add CLI reference (arguments/help output) to docs and README.
- [x] Add integration test ensuring monitoring metrics capture timeout/cancellation cases from a real Sage run.
- [x] Update Helm `values.yaml` defaults once the GHCR image is published.
- [x] Extend release workflow to push Helm chart artifacts and run `helm lint`/`helm template` for validation during release publish.
- [x] Add CI smoke tests that bring up `docker compose` services (pure-Python mode) and exercise `scripts/exercise_mcp.py`.
- [x] Add Dependabot (or Renovate) configuration for Python, GitHub Actions, and Docker dependencies.

## Current priority queue

- [x] **Release blocker:** disable stateful tool/resource response caching and add two-client isolation tests ([review item 10](REVIEW_ACTIONS.md)).
- [x] **Release blocker:** close the AST-validator bypasses, correct the public sandbox claims, and harden the real container boundary ([review items 1-3](REVIEW_ACTIONS.md)). Took three rounds: direct spellings, then aliases of forbidden functions, then aliases of forbidden modules.
- [x] Fix named-workspace cancellation and validate worker response ids ([review item 11](REVIEW_ACTIONS.md)). Includes `reset()`, which was still reading the next line unconditionally.
- [x] Reject every numeric integer above `2^53`; require decimal strings for exact large values ([review item 12](REVIEW_ACTIONS.md)).
- [x] Implement actual incremental stdout events or rename the buffered streaming facade ([review item 13](REVIEW_ACTIONS.md)) — implemented, not renamed.
- [x] Persist idle-culled sessions and make journal filenames collision-free ([review items 14-15](REVIEW_ACTIONS.md)), with a fallback so the rename does not orphan journals written by earlier versions.
- [x] Add named-workspace selection to every specialized worker-backed tool ([review item 16](REVIEW_ACTIONS.md)).
- [x] Synchronize both `server.json` versions in `scripts/bump_version.py` and add a consistency test ([review item 17](REVIEW_ACTIONS.md)).
- [x] Split `server.py` into `app`/`runtime`/`codegen` and a `tools/` package ([review item 4](REVIEW_ACTIONS.md)); coverage work on the extracted helpers is deliberately separate.
- [ ] Raise coverage on the helpers now that they are isolated in `codegen.py` (distribution mean/variance, matrix and integer rejection paths, expression fallbacks).
- [x] Run the CLI suites on a schedule rather than by memory (`.github/workflows/cli-nightly.yml`); add the three API-key secrets to switch each leg on.
- [ ] Confirm the MCP registry listing goes live on the next tagged release; the job has never executed.
- [ ] Account-side Smithery and Glama submissions ([review item 7](REVIEW_ACTIONS.md)) — needs repository-owner access.
