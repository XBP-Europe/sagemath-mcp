#!/usr/bin/env bash
set -euo pipefail

# This is the DEVELOPMENT/TEST container: it mounts the checkout writably so
# `make sage-deps` can install the dev extras and the suite can run against a
# real Sage. It is not a runtime deployment -- use the Dockerfile image or
# docker-compose.yml (read-only root, dropped capabilities, loopback publish)
# to run the server. The image tag is pinned to the Sage release the project
# targets: a moving `latest` silently changed which Sage the tests ran against.
IMAGE="${SAGEMATH_MCP_DOCKER_IMAGE:-sagemath/sagemath:10.9}"
CONTAINER="${SAGEMATH_MCP_DOCKER_CONTAINER:-sage-mcp}"
MOUNT_DIR="${SAGEMATH_MCP_WORKDIR:-$(pwd)}"
WORKDIR="${SAGEMATH_MCP_CONTAINER_WORKDIR:-/workspace}"
# Bounded even as a dev fixture: a fork bomb or runaway computation in a test
# should not exhaust the host. Generous because the full suite (corpus sweep
# included) runs here; override via the environment if your machine needs it.
PIDS_LIMIT="${SAGEMATH_MCP_DOCKER_PIDS_LIMIT:-2048}"
MEMORY="${SAGEMATH_MCP_DOCKER_MEMORY:-8g}"

if ! command -v docker >/dev/null 2>&1; then
  echo "Error: docker is required to set up the Sage container." >&2
  exit 1
fi

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "Pulling Sage image $IMAGE ..."
  docker pull "$IMAGE"
fi

if docker ps -a --format '{{.Names}}' | grep -Fxq "$CONTAINER"; then
  if docker ps --format '{{.Names}}' | grep -Fxq "$CONTAINER"; then
    echo "Container $CONTAINER is already running."
    exit 0
  else
    echo "Starting existing container $CONTAINER ..."
    docker start "$CONTAINER"
    exit 0
  fi
fi

echo "Launching Sage container $CONTAINER ..."
docker run \
  --name "$CONTAINER" \
  -d \
  --pids-limit "$PIDS_LIMIT" \
  --memory "$MEMORY" \
  --security-opt no-new-privileges \
  -v "$MOUNT_DIR":"$WORKDIR" \
  -w "$WORKDIR" \
  "$IMAGE" \
  tail -f /dev/null

echo "Container $CONTAINER is ready (development/test fixture; not a hardened runtime)."
echo "Attach with: docker exec -it $CONTAINER bash"
