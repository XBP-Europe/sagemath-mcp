# Distribution & Installation Guide

## Versioning

Use the **Bump Version** workflow (GitHub Actions → *Bump Version*) before starting a release. The workflow:

- increments the selected segment (patch by default) via `scripts/bump_version.py`,
- updates all four places a version appears — `pyproject.toml`,
  `src/sagemath_mcp/__init__.py`, `charts/sagemath-mcp/Chart.yaml` and
  `server.json` (which carries it twice) — because a test fails when they
  disagree,
- pushes a branch and **opens a pull request**; `main` is protected by required
  status checks, so nothing is committed to it directly, and
- stops there. **You push the tag yourself once that pull request merges:**

  ```bash
  git tag vX.Y.Z && git push origin vX.Y.Z
  ```

  Pushing the tag is what triggers the release pipeline, and it is the point of
  no return: a PyPI version number can never be reused. Record the changes in
  `CHANGELOG.md` under `## [X.Y.Z]` **before** tagging — the release job reads
  that section for its notes and falls back to generated ones with a warning if
  it is missing.

The full release procedure, including how to choose the segment, is in
[CONTRIBUTING.md](CONTRIBUTING.md#releasing).

## Building Artifacts
1. Install development extras:
   ```bash
   uv pip install -e .[dev]
   ```
2. Produce source and wheel distributions (docs included):
   ```bash
   uv run python scripts/build_release.py
   ```
   Artifacts land in the `dist/` directory (e.g., `sagemath_mcp-<version>.tar.gz`, `sagemath_mcp-<version>-py3-none-any.whl`).

## Verifying Contents
```bash
uv run python -m build --wheel --sdist --outdir dist
uv run python -m twine check dist/*
```
`twine check` confirms metadata and long description rendering.

## Local Installation
Install from a built wheel:
```bash
uv pip install dist/sagemath_mcp-<version>-py3-none-any.whl
```
Or directly from source:
```bash
uv pip install dist/sagemath_mcp-<version>.tar.gz
```

## Publishing (PyPI Example)
```bash
uv run python -m twine upload dist/*
```
Provide PyPI credentials via environment variables or keyring as usual.

### Container Artifacts (GHCR)

The release workflow automatically builds and pushes Docker images to GHCR at
`ghcr.io/xbp-europe/sagemath-mcp`. To pull locally:

```bash
docker pull ghcr.io/xbp-europe/sagemath-mcp:v0.5.0   # or :latest to track releases
```

Prefer a version tag in anything you deploy. `latest` gives no way to say which
build is running when something breaks, and no clean rollback.

Images inherit the upstream `sagemath/sagemath` base and run as the non-root `sage`
user (UID/GID 1001), with a read-only root filesystem and writable scratch supplied
as tmpfs. Mounted repository directories are read-only and need no ownership change;
grant UID/GID 1001 write access only to a dedicated persistence volume, if you use one.

This number comes from the base image and is not ours to choose: `sage` was UID 1000
through SageMath 10.5 and is 1001 from 10.9. Check it after any base image bump with
`docker run --rm sagemath/sagemath:<tag> id sage`, and update the Helm chart's
`runAsUser`/`runAsGroup` to match. `/home/sage` is mode 0750, so a mismatched UID
cannot even reach the `sage` executable and the container exits immediately.

Helm deployments reference the same image via `charts/sagemath-mcp/values.yaml`. Adjust
`image.tag` in values or `--set image.tag=<version>` when installing a specific release.

### Verifying container signatures

All published images are signed with [Sigstore Cosign](https://docs.sigstore.dev/). Verify
the signature using GitHub’s OIDC transparency log:

```bash
cosign verify ghcr.io/xbp-europe/sagemath-mcp:latest \
  --certificate-identity="https://github.com/XBP-Europe/sagemath-mcp/.github/workflows/release.yml@refs/tags/vX.Y.Z" \
  --certificate-oidc-issuer="https://token.actions.githubusercontent.com"
```

Replace `vX.Y.Z` with the tagged release when verifying specific builds. Successful
verification proves the image was built by the repository’s GitHub Actions workflow.

## Verification After Install
```bash
uv pip install sagemath-mcp
uv run sagemath-mcp --help
```
`--help` works without SageMath; nothing else does, since every evaluation needs
a Sage runtime. With one available, run a quick smoke test:
```bash
sage -python scripts/exercise_mcp.py
```

For container validation, start the service with `docker compose up --build` (`docker-compose` on Compose v1) and run
`scripts/exercise_mcp.py` against `http://127.0.0.1:8314/mcp` to confirm end-to-end behavior.
