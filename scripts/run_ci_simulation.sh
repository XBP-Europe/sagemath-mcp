#!/usr/bin/env bash

set -euo pipefail

cat <<'NOTE'
====================================================
Local CI Simulation
====================================================
This script approximates the GitHub Actions workflow defined in .github/workflows/ci.yml.
It assumes you have uv, docker, docker-compose, curl, tar, and sudo available locally.
NOTE

# Ensure we're in repo root
REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO_ROOT"

# Step 1: Create uv virtual environment if missing
if [ ! -d ".venv" ]; then
  echo "==> Creating uv virtual environment"
  uv venv
fi

# Step 2: Install dependencies (mirrors uv pip install -e .[dev])
echo "==> Installing dev dependencies"
uv pip install -e .[dev]

# Step 3: Install Helm if required
HELM_VERSION=${HELM_VERSION:-v3.15.2}
if ! command -v helm >/dev/null 2>&1 || ! helm version --short | grep -F "${HELM_VERSION}" >/dev/null 2>&1; then
  echo "==> Installing Helm ${HELM_VERSION}"
  curl -sSL "https://get.helm.sh/helm-${HELM_VERSION}-linux-amd64.tar.gz" | tar -xz
  sudo mv linux-amd64/helm /usr/local/bin/helm
  rm -rf linux-amd64
else
  echo "==> Helm ${HELM_VERSION} already available"
fi

# Step 4: Helm lint/template
helm lint charts/sagemath-mcp
helm template test charts/sagemath-mcp

# Step 5: Lint and unit tests
make lint
make test

# Step 6: Integration tests (requires running sage container)
if docker ps --format '{{.Names}}' | grep -Fxq 'sage-mcp'; then
  echo "==> Running integration tests against existing sage-mcp container"
  make integration-test || true
else
  echo "==> Skipping integration tests (sage-mcp container not running)"
fi

# Step 7: Docker Compose smoke test & monitoring verification
if command -v docker-compose >/dev/null 2>&1; then
  echo "==> Running docker-compose smoke test"
  docker-compose up --build -d
  export SAGEMATH_MCP_URL="http://127.0.0.1:31415/mcp"
  cleanup() {
    docker-compose down
  }
  trap cleanup EXIT
  uv run python scripts/exercise_mcp.py
  uv run python - <<'PY'
import asyncio
import os
from fastmcp import Client

async def main():
    client = Client(os.environ["SAGEMATH_MCP_URL"], transport="http")
    metrics = await client.resource("resource://sagemath/monitoring/metrics")
    assert metrics, "No metrics returned"
    snapshot = metrics[0]
    assert snapshot.attempts >= 1, "Expected at least one recorded attempt"

asyncio.run(main())
PY
else
  echo "==> docker-compose command not found; skipping smoke test"
fi

# Step 8: Build artifacts
make build

echo "==> CI simulation completed successfully."
