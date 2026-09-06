# The DEVELOPMENT/TEST container: writable checkout, no read-only hardening.
# Use the Dockerfile image or docker-compose.yml to run the server. The image
# tag is pinned to the Sage release the project targets, matching the bash
# script -- a moving `latest` silently changed which Sage the tests ran against.
param(
    [string]$Image = $env:SAGEMATH_MCP_DOCKER_IMAGE,
    [string]$ContainerName = $env:SAGEMATH_MCP_DOCKER_CONTAINER,
    [string]$MountDir = $env:SAGEMATH_MCP_WORKDIR,
    [string]$Workdir = $env:SAGEMATH_MCP_CONTAINER_WORKDIR,
    [string]$PidsLimit = $env:SAGEMATH_MCP_DOCKER_PIDS_LIMIT,
    [string]$Memory = $env:SAGEMATH_MCP_DOCKER_MEMORY
)

if (-not $Image) { $Image = "sagemath/sagemath:10.9" }
if (-not $ContainerName) { $ContainerName = "sage-mcp" }
if (-not $MountDir) { $MountDir = (Get-Location).Path }
if (-not $Workdir) { $Workdir = "/workspace" }
if (-not $PidsLimit) { $PidsLimit = "2048" }
if (-not $Memory) { $Memory = "8g" }

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error "Docker CLI not found. Install Docker Desktop first."
    exit 1
}

if (-not (docker image inspect $Image 2>$null)) {
    Write-Host "Pulling Sage image $Image ..."
    docker pull $Image
}

$existing = docker ps -a --format '{{.Names}}' | Where-Object { $_ -eq $ContainerName }
if ($existing) {
    $running = docker ps --format '{{.Names}}' | Where-Object { $_ -eq $ContainerName }
    if ($running) {
        Write-Host "Container $ContainerName already running."
        exit 0
    }
    Write-Host "Starting existing container $ContainerName ..."
    docker start $ContainerName | Out-Null
    exit 0
}

Write-Host "Launching Sage container $ContainerName ..."
docker run `
  --name $ContainerName `
  -d `
  --pids-limit $PidsLimit `
  --memory $Memory `
  --security-opt no-new-privileges `
  -v "$MountDir":"$Workdir" `
  -w "$Workdir" `
  $Image `
  tail -f /dev/null | Out-Null

Write-Host "Container $ContainerName is ready (development/test fixture; not a hardened runtime)."
Write-Host "Attach with: docker exec -it $ContainerName bash"
