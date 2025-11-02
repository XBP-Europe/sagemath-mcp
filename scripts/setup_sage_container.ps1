param(
    [string]$Image = $env:SAGEMATH_MCP_DOCKER_IMAGE,
    [string]$ContainerName = $env:SAGEMATH_MCP_DOCKER_CONTAINER,
    [string]$MountDir = $env:SAGEMATH_MCP_WORKDIR,
    [string]$Workdir = $env:SAGEMATH_MCP_CONTAINER_WORKDIR
)

if (-not $Image) { $Image = "sagemath/sagemath:latest" }
if (-not $ContainerName) { $ContainerName = "sage-mcp" }
if (-not $MountDir) { $MountDir = (Get-Location).Path }
if (-not $Workdir) { $Workdir = "/workspace" }

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
  -v "$MountDir":"$Workdir" `
  -w "$Workdir" `
  $Image `
  tail -f /dev/null | Out-Null

Write-Host "Container $ContainerName is ready. Attach with: docker exec -it $ContainerName bash"
