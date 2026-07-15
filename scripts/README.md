# `scripts/`

| File | Purpose |
|---|---|
| `setup.ps1` | Happy-path bootstrap: checks Docker, starts/creates the Orthanc container, sets up `.venv` + `mcp-server` dependencies, checks for DCMTK (soft dependency, informational only), and runs `health_check` to confirm everything works. Automates the native-venv setup described in [SETUP.md](../docs/SETUP.md) — the MCP server itself always runs as a local Python subprocess, never containerized; only Orthanc runs in Docker. |
| `reset_orthanc.ps1` | Deletes **all** studies from the local Orthanc PACS via its REST API — a full reset of the test PACS between runs. Irreversible; prompts for confirmation unless `-Yes` is passed. Reads the same `ORTHANC_URL`/`ORTHANC_USER`/`ORTHANC_PASSWORD` env vars as `mcp-server/config.py`. |
| `upload_seed_dataset.ps1` | Uploads every `*.dcm` file under [dicomdataset/](../dicomdataset/) into the local Orthanc PACS via its REST API, so a freshly set-up environment has some real studies to browse right away. Safe to re-run — Orthanc dedupes by SOPInstanceUID. Reads the same `ORTHANC_URL`/`ORTHANC_USER`/`ORTHANC_PASSWORD` env vars as `mcp-server/config.py`. |

Run from the repo root or from `scripts/` itself:

```powershell
.\scripts\setup.ps1

# seed the local PACS with the bundled sample DICOM files
.\scripts\upload_seed_dataset.ps1

# wipe every study from the local test PACS
.\scripts\reset_orthanc.ps1 OR
powershell -ExecutionPolicy Bypass -File .\scripts\reset_orthanc.ps1
```

Requires Docker Desktop and Python 3.11+ already installed — both need
interactive/admin consent and can't be silently scripted (see
[SETUP.md](../docs/SETUP.md)).

**Docker-only alternative to `reset_orthanc.ps1`:** since Orthanc's data here
is just the container + its bind-mounted volume, you can equivalently nuke
and recreate the container instead of going through the REST API:

```powershell
docker stop orthanc
docker rm orthanc
Remove-Item -Recurse -Force C:\orthanc-data
.\scripts\setup.ps1   # recreates the container + empty data folder
```

Same end result as `reset_orthanc.ps1` (empty PACS), just via the container
layer instead of per-study REST deletes — pick whichever you find easier to
run correctly.
