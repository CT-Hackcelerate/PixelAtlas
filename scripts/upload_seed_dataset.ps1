<#
.SYNOPSIS
    Upload the bundled sample DICOM files (dicomdataset/) into the local Orthanc PACS.

.DESCRIPTION
    Recursively finds every *.dcm file under dicomdataset/ (CR/CT/MRI/PX
    samples plus a few public multi-series datasets) and uploads each one to
    Orthanc via its REST API (POST /instances) - the same mechanism
    orthanc_client.upload_instance uses for store_to_pacs's Orthanc-REST
    fallback (solution-design.md SS11). Lets a freshly set-up environment
    have some real studies to browse/reference immediately, without needing
    to generate anything first.

    Reads connection details from the same env vars as mcp-server/config.py
    (ORTHANC_URL, ORTHANC_USER, ORTHANC_PASSWORD), falling back to the same
    defaults, so it targets whatever Orthanc your MCP server is configured
    against without needing separate setup.

    Safe to re-run: Orthanc dedupes by SOPInstanceUID, so re-uploading the
    same files just no-ops on the ones already stored.

.PARAMETER Path
    Folder to scan for *.dcm files. Defaults to dicomdataset/ at the repo root.

.EXAMPLE
    .\scripts\upload_seed_dataset.ps1
    Uploads every *.dcm file under dicomdataset/ to the local Orthanc.

.EXAMPLE
    .\scripts\upload_seed_dataset.ps1 -Path "C:\dev\PixelAtlas\dicomdataset\CT Chest"
    Uploads just one sample folder.
#>

param(
    [string]$Path = (Join-Path (Split-Path -Parent $PSScriptRoot) "dicomdataset")
)

$ErrorActionPreference = "Stop"

$OrthancUrl = if ($env:ORTHANC_URL) { $env:ORTHANC_URL } else { "http://localhost:8042" }
$OrthancUser = if ($env:ORTHANC_USER) { $env:ORTHANC_USER } else { "orthanc" }
$OrthancPassword = if ($env:ORTHANC_PASSWORD) { $env:ORTHANC_PASSWORD } else { "orthanc" }

$pair = "$($OrthancUser):$($OrthancPassword)"
$basicAuth = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($pair))
$headers = @{ Authorization = "Basic $basicAuth" }

if (-not (Test-Path $Path)) {
    Write-Host "Path not found: $Path" -ForegroundColor Red
    exit 1
}

Write-Host "Target Orthanc: $OrthancUrl" -ForegroundColor Cyan
Write-Host "Scanning: $Path" -ForegroundColor Cyan

try {
    Invoke-RestMethod -Uri "$OrthancUrl/system" -Headers $headers -Method Get | Out-Null
} catch {
    Write-Host "Could not reach Orthanc at $OrthancUrl - is it running? ($_)" -ForegroundColor Red
    exit 1
}

$files = Get-ChildItem -Path $Path -Filter "*.dcm" -Recurse -File
$total = $files.Count
if ($total -eq 0) {
    Write-Host "No .dcm files found under $Path" -ForegroundColor Yellow
    exit 0
}

Write-Host "Found $total .dcm file(s). Uploading..." -ForegroundColor Cyan

$uploaded = 0
$duplicates = 0
$failed = 0
$i = 0

foreach ($file in $files) {
    $i++
    if ($i % 50 -eq 0 -or $i -eq $total) {
        Write-Progress -Activity "Uploading to Orthanc" -Status "$i / $total" -PercentComplete (($i / $total) * 100)
    }
    try {
        $bytes = [System.IO.File]::ReadAllBytes($file.FullName)
        $result = Invoke-RestMethod -Uri "$OrthancUrl/instances" -Headers $headers -Method Post -Body $bytes -ContentType "application/dicom"
        if ($result.Status -eq "AlreadyStored") {
            $duplicates++
        } else {
            $uploaded++
        }
    } catch {
        Write-Host "  [!] Failed to upload $($file.FullName): $_" -ForegroundColor Red
        $failed++
    }
}

Write-Progress -Activity "Uploading to Orthanc" -Completed

Write-Host "`nUploaded $uploaded new instance(s); $duplicates already present; $failed failed." -ForegroundColor Green
if ($failed -gt 0) {
    Write-Host "$failed file(s) failed to upload - see errors above." -ForegroundColor Red
    exit 1
}
Write-Host "Visit $OrthancUrl to browse the seeded studies." -ForegroundColor Cyan
