<#
.SYNOPSIS
    Delete ALL studies from the local Orthanc PACS - irreversible.

.DESCRIPTION
    Wipes every study (all patients/studies/series/instances) from the Orthanc
    instance this project talks to, via its REST API. Meant for resetting the
    local dev PACS between test runs - NOT for anything pointed at real data.

    Reads connection details from the same env vars as mcp-server/config.py
    (ORTHANC_URL, ORTHANC_USER, ORTHANC_PASSWORD), falling back to the same
    defaults, so it targets whatever Orthanc your MCP server is configured
    against without needing separate setup.

.PARAMETER Yes
    Skip the interactive confirmation prompt (e.g. for scripted use). Without
    it, the script lists what it found and asks you to type "yes" first.

.EXAMPLE
    .\scripts\reset_orthanc.ps1
    Lists study count, asks for confirmation, then deletes everything.

.EXAMPLE
    .\scripts\reset_orthanc.ps1 -Yes
    Deletes everything without prompting.
#>

param(
    [switch]$Yes
)

$ErrorActionPreference = "Stop"

$OrthancUrl = if ($env:ORTHANC_URL) { $env:ORTHANC_URL } else { "http://localhost:8042" }
$OrthancUser = if ($env:ORTHANC_USER) { $env:ORTHANC_USER } else { "orthanc" }
$OrthancPassword = if ($env:ORTHANC_PASSWORD) { $env:ORTHANC_PASSWORD } else { "orthanc" }

$pair = "$($OrthancUser):$($OrthancPassword)"
$basicAuth = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($pair))
$headers = @{ Authorization = "Basic $basicAuth" }

Write-Host "Target Orthanc: $OrthancUrl" -ForegroundColor Cyan

try {
    $studyIds = Invoke-RestMethod -Uri "$OrthancUrl/studies" -Headers $headers -Method Get
} catch {
    Write-Host "Could not reach Orthanc at $OrthancUrl - is it running? ($_)" -ForegroundColor Red
    exit 1
}

$count = $studyIds.Count
if ($count -eq 0) {
    Write-Host "No studies found - Orthanc is already empty." -ForegroundColor Green
    exit 0
}

Write-Host "Found $count stud$(if ($count -eq 1) {'y'} else {'ies'}) in Orthanc." -ForegroundColor Yellow
Write-Host "This will PERMANENTLY delete every study, series, and instance. This cannot be undone." -ForegroundColor Yellow

if (-not $Yes) {
    $confirmation = Read-Host "Type 'yes' to delete all $count studies"
    if ($confirmation -ne "yes") {
        Write-Host "Aborted - nothing was deleted." -ForegroundColor Cyan
        exit 0
    }
}

$deleted = 0
$failed = 0
foreach ($id in $studyIds) {
    try {
        Invoke-RestMethod -Uri "$OrthancUrl/studies/$id" -Headers $headers -Method Delete | Out-Null
        $deleted++
    } catch {
        Write-Host "  [!] Failed to delete study $id : $_" -ForegroundColor Red
        $failed++
    }
}

Write-Host "`nDeleted $deleted stud$(if ($deleted -eq 1) {'y'} else {'ies'})." -ForegroundColor Green
if ($failed -gt 0) {
    Write-Host "$failed failed to delete - see errors above." -ForegroundColor Red
    exit 1
}
