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

## Verification After Install
```bash
uv pip install sagemath-mcp
uv run sagemath-mcp -- --help
```
If SageMath is available, execute a quick smoke test:
```bash
sage -python scripts/exercise_mcp.py
```
