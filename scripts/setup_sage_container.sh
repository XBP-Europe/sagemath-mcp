#!/usr/bin/env bash
set -euo pipefail

IMAGE="${SAGEMATH_MCP_DOCKER_IMAGE:-sagemath/sagemath:latest}"
CONTAINER="${SAGEMATH_MCP_DOCKER_CONTAINER:-sage-mcp}"
MOUNT_DIR="${SAGEMATH_MCP_WORKDIR:-$(pwd)}"
WORKDIR="${SAGEMATH_MCP_CONTAINER_WORKDIR:-/workspace}"

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
  -v "$MOUNT_DIR":"$WORKDIR" \
  -w "$WORKDIR" \
  "$IMAGE" \
  tail -f /dev/null

echo "Container $CONTAINER is ready. Attach with: docker exec -it $CONTAINER bash"
