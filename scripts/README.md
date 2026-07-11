# `scripts/`

| File | Purpose |
|---|---|
| `setup.ps1` | Happy-path bootstrap: checks Docker, starts/creates the Orthanc container, sets up `.venv` + `mcp-server` dependencies, checks for DCMTK (soft dependency, informational only), and runs `health_check` to confirm everything works. See the script's own header comment for scope notes — it automates the *actual* native-venv setup this project uses, not the containerized-MCP-server path architecture.md describes as an option. |

Run from the repo root or from `scripts/` itself:

```powershell
.\scripts\setup.ps1
```

Requires Docker Desktop and Python 3.11+ already installed — both need
interactive/admin consent and can't be silently scripted (see
[architecture.md §6](../docs/architecture.md#6-prerequisites--setup)).
