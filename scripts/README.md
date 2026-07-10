# `scripts/`

| File | Purpose |
|---|---|
| `setup.ps1` | Happy-path bootstrap: checks Docker, starts/creates the Orthanc container, sets up `.venv` + `mcp-server` dependencies, checks for DCMTK (soft dependency, informational only), and runs `health_check` to confirm everything works. See the script's own header comment for scope notes — it automates the *actual* native-venv setup this project uses, not the containerized-MCP-server path architecture.md describes as an option. |
| `generate_iod_spec.py` | One-time template-authoring tool: dumps a DICOM IOD's module/tag requirements from `dicom-validator`'s standard-derived data into a committed `templates/<MODALITY>/<template_id>/iod_spec.yaml`. Run manually when adding a new IOD template or refreshing against a new DICOM standard edition — never invoked by the MCP server. Usage: `python scripts/generate_iod_spec.py <sop_class_uid> <output_path>`. |
| `generate_seed.py` | Regenerates a template's pixel-only fallback seed (`seed/IM0001.dcm`) from its `manifest.yaml` (`sop_class_uid`, `modality`, optional `seed_params`) — one shared script for every modality. Usage: `python scripts/generate_seed.py <template_id>`. |

Run from the repo root or from `scripts/` itself:

```powershell
.\scripts\setup.ps1
```

Requires Docker Desktop and Python 3.11+ already installed — both need
interactive/admin consent and can't be silently scripted (see
[architecture.md §6](../docs/architecture.md#6-prerequisites--setup)).
