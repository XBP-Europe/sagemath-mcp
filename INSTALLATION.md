# Installation Guide

This document collects platform-specific notes for installing and running the
SageMath MCP server.

> **SageMath itself is required, not optional.** A plain `pip install
> sagemath-mcp` gives you the MCP server, not Sage. Without a Sage runtime the
> server starts and advertises all 40 tools, and then every evaluation fails
> with `Unable to locate Sage executable 'sage'`. Pick one of these:
>
> - **The `[passagemath]` extra** (macOS and Linux), the recommended route:
>   `pip install "sagemath-mcp[passagemath]"` installs a pip-built Sage runtime
>   (~1 GB) next to the server, pinned to a release this project's CI has
>   verified. Native Windows is not supported (see below). A pip install runs
>   with your own privileges; the container below adds OS-level isolation.
> - **The container image** (all platforms), for isolation: Sage is baked in. See
>   [Docker Compose](#docker-compose-all-platforms) below, or the `docker run`
>   line in the README. The image runs **SageMath 10.10**, the version the set
>   of names callers may use is generated from.
> - **conda-forge** (macOS and Linux):
>   `conda install -c conda-forge "sagemath-mcp>=0.9.4" sage`.
> - **A Sage you already have.** If `sage` is on your `PATH`, or installed in the
>   same environment as the server (a conda env or venv, even when not
>   activated), the server uses it. Point `SAGEMATH_MCP_SAGE_BINARY` at it if it
>   is installed somewhere unusual.
>
> A server running on the host cannot use a Sage that lives inside a container,
> so `make sage-container` (a development and test fixture) is not a runtime.

## Cross-platform (pip/uv)

```bash
pip install "sagemath-mcp[passagemath]"   # or plain sagemath-mcp next to your own Sage
sagemath-mcp --transport streamable-http --host 127.0.0.1 --port 8314
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uvx --from "sagemath-mcp[passagemath]" sagemath-mcp --transport http --host 127.0.0.1 --port 8314
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
  --set image.tag=v0.9.6
```

The chart pulls `ghcr.io/xbp-europe/sagemath-mcp`; set `image.repository` only
for your own build. Pin the tag to a released version rather than `latest`.
`latest` gives you no way to say which build is running when something breaks,
no clean rollback, and no guarantee that a restarted pod matches its neighbours.

The chart enforces non-root execution and drops Linux capabilities. Edit `values.yaml` to customise
ingress, resource limits, or environment variables.

## Windows 11

SageMath has no native Windows build, and passagemath's native Windows support
is partial (no PARI, Singular or Maxima), so run the server where Sage does:

- **The container image** (recommended): install
  [Docker Desktop](https://www.docker.com/products/docker-desktop/), then run
  the image as in the README (`docker run … -p 127.0.0.1:8314:8314
  ghcr.io/xbp-europe/sagemath-mcp:0.9.6`), or `docker compose up` in a checkout.
  The server is then at `http://127.0.0.1:8314/mcp`.
- **WSL**: inside a WSL distribution, follow the Linux instructions
  (`pip install "sagemath-mcp[passagemath]"`).

For source development, install Python 3.12+ from
[python.org](https://python.org/) (check "Add to PATH") and, optionally, `uv`:

```powershell
powershell -ExecutionPolicy RemoteSigned -Command "Invoke-WebRequest https://astral.sh/uv/install.ps1 -UseBasicParsing | Invoke-Expression"
```

then clone the repository and run `uv pip install -e .[dev]`.
`pwsh -File scripts/setup_sage_container.ps1` starts the development container
the integration tests run in.

## macOS (Intel & Apple Silicon)

1. Install Python 3.12 via [python.org](https://python.org) or Homebrew:
   ```bash
   brew install python@3.12
   ```
2. Install `uv` (optional but recommended):
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```
3. Install the package with its Sage runtime:
   ```bash
   pip3 install "sagemath-mcp[passagemath]"
   ```
   (or conda-forge: `conda install -c conda-forge "sagemath-mcp>=0.9.4" sage`)
4. Launch the server:
   ```bash
   sagemath-mcp
   ```
5. For development, clone the repo and run `uv pip install -e .[dev]`.
   `make sage-container` starts the development container the integration
   tests run in; it is not a runtime for the server.

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
  installed but there is no Sage for it to drive. Install the `[passagemath]`
  extra, run the container image instead, or set `SAGEMATH_MCP_SAGE_BINARY` to
  your own installation.
- **Security policy errors** ("Import statements are disabled", "is not a name
  this server offers") are the sandbox working as intended. Caller code is
  checked against an allowlist, so the fix is a Sage primitive or the matching
  specialised tool rather than a way around the rule — `USAGE.md` lists what is
  refused and what to use instead.
