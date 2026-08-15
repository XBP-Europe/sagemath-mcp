# Installation Guide

This document collects platform-specific notes for installing and running the
SageMath MCP server.

> **SageMath itself is required, not optional.** Installing this package gives
> you the MCP server; it does not give you Sage. Without a Sage runtime the
> server starts and advertises all 37 tools, and then every evaluation fails
> with `Unable to locate Sage executable 'sage'`. The supported way to supply
> one is the Docker container below — the project is built and tested against
> **SageMath 10.9**, and the set of names callers may use is generated from that
> version.
>
> If `sage` is on your `PATH` already, the server uses it and no container is
> needed. Point `SAGEMATH_MCP_SAGE_BINARY` at it if it is installed somewhere
> unusual.

## Cross-platform (pip/uv)

```bash
pip install sagemath-mcp
sagemath-mcp --transport streamable-http --host 127.0.0.1 --port 8314
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv tool install sagemath-mcp
uvx sagemath-mcp --transport http --host 127.0.0.1 --port 8314
```

### Docker Compose (all platforms)

> Compose ships two ways: `docker compose` (the v2 plugin, current) and
> `docker-compose` (the v1 binary, end of life since 2023). The commands below
> use the v2 spelling; substitute `docker-compose` if that is what you have.
> Repository tooling detects whichever is installed.

```bash
git clone https://github.com/XBP-Europe/sagemath-mcp.git
cd sagemath-mcp
docker compose up --build
```

The container exposes `http://127.0.0.1:8314/mcp` and runs as the non-root `sage` user (UID/GID 1001),
with a read-only root filesystem.

The bundled compose file mounts the repository read-only, so it needs no ownership
change. Do **not** `chown -R` the checkout to make it writable: the server runs from
the package installed in the image, not from the mount, and a writable checkout is
something an escaped process can edit. If you deliberately develop against the mount,
drop the `:ro` on that one volume rather than changing ownership of the tree.

### Kubernetes (Helm)

```bash
helm install sagemath charts/sagemath-mcp \
  --set image.repository=<your-ghcr-namespace>/sagemath-mcp \
  --set image.tag=v0.5.0
```

Pin the tag to a released version rather than `latest`. `latest` gives you no
way to say which build is running when something breaks, no clean rollback, and
no guarantee that a restarted pod matches its neighbours.

The chart enforces non-root execution and drops Linux capabilities. Edit `values.yaml` to customise
ingress, resource limits, or environment variables.

## Windows 11

1. Install Python 3.12+ from [python.org](https://python.org/) (check "Add to PATH").
2. Optionally install `uv`:
   ```powershell
   powershell -ExecutionPolicy RemoteSigned -Command "Invoke-WebRequest https://astral.sh/uv/install.ps1 -UseBasicParsing | Invoke-Expression"
   ```
3. Install the package:
   ```powershell
   pip install sagemath-mcp
   ```
4. Launch the server:
   ```powershell
   sagemath-mcp
   ```
   (Use `python -m sagemath_mcp.server` if the command is not on `PATH`.)
5. Sage runtime (**required** — the server cannot evaluate anything without it):
   - Install [Docker Desktop](https://www.docker.com/products/docker-desktop/).
   - Run `pwsh -File scripts/setup_sage_container.ps1` to launch the container, or use Git Bash/WSL with `make sage-container`.
6. For source development, clone the repository and run `uv pip install -e .[dev]`.

## macOS (Intel & Apple Silicon)

1. Install Python 3.12 via [python.org](https://python.org) or Homebrew:
   ```bash
   brew install python@3.12
   ```
2. Install `uv` (optional but recommended):
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```
3. Install the package:
   ```bash
   pip3 install sagemath-mcp
   ```
4. Launch the server:
   ```bash
   sagemath-mcp
   ```
5. Sage runtime via Docker Desktop (**required** — without it every evaluation fails):
   ```bash
   make sage-container  # or ./scripts/setup_sage_container.sh
   ```
6. For development, clone the repo and run `uv pip install -e .[dev]`.

## Linux

Follow the cross-platform pip instructions. For development, clone the repo and run:

```bash
uv pip install -e .[dev]
make test
```

## Troubleshooting

- If `sagemath-mcp` is not recognized on Windows, ensure the Python Scripts directory is on `PATH`
  or run `python -m sagemath_mcp.server`.
- To manage the Docker container manually:
  ```bash
  docker logs -f sage-mcp
  docker exec -it sage-mcp bash
  docker rm -f sage-mcp
  ```
- Only a dedicated persistence or scratch volume should ever be writable, and only that
  path needs to belong to UID/GID 1001 (`chown 1001:1001 <that-path>`). The checkout
  itself is mounted read-only by design; do not widen it to fix a permission error.
- **"Unable to locate Sage executable"** means exactly that: the package is
  installed but there is no Sage for it to drive. Start the container, or set
  `SAGEMATH_MCP_SAGE_BINARY` to your own installation.
- **Security policy errors** ("Import statements are disabled", "is not a name
  this server offers") are the sandbox working as intended. Caller code is
  checked against an allowlist, so the fix is a Sage primitive or the matching
  specialised tool rather than a way around the rule — `USAGE.md` lists what is
  refused and what to use instead.
