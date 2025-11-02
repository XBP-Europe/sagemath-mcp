# Distribution & Installation Guide

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
`ghcr.io/csteinl/sagemath-mcp`. To pull locally:

```bash
docker pull ghcr.io/csteinl/sagemath-mcp:latest
```

Images inherit the upstream `sagemath/sagemath` base and run as the non-root `sage`
user (UID/GID 1000). Ensure repository directories mounted into the container are
writable by that user (`chown -R 1000:1000 .` before `docker run`/`docker compose up`).

Helm deployments reference the same image via `charts/sagemath-mcp/values.yaml`. Adjust
`image.tag` in values or `--set image.tag=<version>` when installing a specific release.

## Verification After Install
```bash
uv pip install sagemath-mcp
uv run sagemath-mcp -- --help
```
If SageMath is available, execute a quick smoke test:
```bash
sage -python scripts/exercise_mcp.py
```

For container validation, start the service with `docker compose up --build` and run
`scripts/exercise_mcp.py` against `http://127.0.0.1:31415/mcp` to confirm end-to-end behavior.
