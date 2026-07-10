<#
.SYNOPSIS
    Happy-path bootstrap for Pixel Atlas's local dev environment.

.DESCRIPTION
    Scope note (Phase 3, execution-plan-phases1-3.md): the original plan described
    this as "Docker check + Orthanc up + image build", assuming a
    containerized MCP server. What was actually built through Phase 1-3 is a
    NATIVE Python (.venv) MCP server talking to a containerized Orthanc - no
    Dockerfile for the MCP server itself exists. This script automates that
    real setup, not the aspirational containerized one. See
    docs/architecture.md section 6 for the full prerequisite table; this
    script covers everything in it except Docker Desktop install and the
    Copilot Agent Mode/MCP org policy toggle, both of which need
    interactive/admin consent and can't be silently scripted.

    DCMTK is treated as a soft dependency here (informational check, not a
    hard failure) - see mcp-server/README.md and execution-plan-phases1-3.md
    section 5: only storescu/dcmftest are actually used by this codebase,
    and both have a working fallback (Orthanc REST upload,
    structural-checks-only) if missing.
#>

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg) { Write-Host "    [ok] $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "    [!]  $msg" -ForegroundColor Yellow }

Write-Step "Checking Docker"
try {
    docker version | Out-Null
    Write-Ok "Docker is installed and running"
} catch {
    Write-Warn "Docker isn't installed or isn't running - install Docker Desktop first (see docs/docker-wsl-setup.md), then re-run this script."
    exit 1
}

Write-Step "Checking/starting Orthanc"
$orthancRunning = docker ps --filter "name=orthanc" --filter "status=running" --format "{{.Names}}"
if ($orthancRunning -eq "orthanc") {
    Write-Ok "Orthanc container already running"
} else {
    $orthancExists = docker ps -a --filter "name=orthanc" --format "{{.Names}}"
    if ($orthancExists -eq "orthanc") {
        Write-Warn "Orthanc container exists but isn't running - starting it"
        docker start orthanc | Out-Null
    } else {
        Write-Warn "No Orthanc container found - creating one (see docs/orthanc-setup.md)"
        New-Item -ItemType Directory -Force -Path "C:\orthanc-data" | Out-Null
        docker run -d --name orthanc -p 4242:4242 -p 8042:8042 `
            -v "C:\orthanc-data:/var/lib/orthanc/db" `
            jodogne/orthanc | Out-Null
    }
    Start-Sleep -Seconds 3
    Write-Ok "Orthanc container is up"
}

Write-Step "Checking Python"
$pythonVersion = python --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Warn "Python not found on PATH - install Python 3.11+ first: winget install Python.Python.3.11"
    exit 1
}
Write-Ok "$pythonVersion"

Write-Step "Setting up the virtual environment"
$VenvPath = Join-Path $RepoRoot ".venv"
if (-not (Test-Path $VenvPath)) {
    python -m venv $VenvPath
    Write-Ok "Created .venv"
} else {
    Write-Ok ".venv already exists"
}
& "$VenvPath\Scripts\pip.exe" install -q -r (Join-Path $RepoRoot "mcp-server\requirements.txt")
Write-Ok "mcp-server dependencies installed"

Write-Step "Checking DCMTK (soft dependency - see script header)"
$dcmtkFound = $null -ne (Get-Command storescu -ErrorAction SilentlyContinue)
if ($dcmtkFound) {
    Write-Ok "storescu found on PATH"
} else {
    Write-Warn "storescu not found on PATH - store_to_pacs will fall back to Orthanc REST upload (still functional). Install DCMTK and add its bin folder to PATH if you want the storescu path specifically."
}

Write-Step "Verifying end-to-end"
Push-Location (Join-Path $RepoRoot "mcp-server")
try {
    $health = & "$VenvPath\Scripts\python.exe" -c "import server, json; print(json.dumps(server.health_check()))"
    Write-Ok "health_check: $health"
} finally {
    Pop-Location
}

Write-Host "`nSetup complete. Open this repo in VS Code, select the Pixel Atlas chat mode, and try /list-templates or /status." -ForegroundColor Cyan
