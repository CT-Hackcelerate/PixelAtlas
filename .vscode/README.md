# `.vscode/`

Workspace-level VS Code configuration.

| File | Purpose |
|---|---|
| `mcp.json` | Registers the `pixel-atlas` MCP server with VS Code's Copilot Agent Mode. Points at the repo-root `.venv` Python interpreter running `mcp-server/server.py`, and sets the env vars the server reads via `mcp-server/config.py` (template/staging/log paths, Orthanc URL + credentials). Edit `env` here if your Orthanc instance uses different host/port/credentials than the [default setup](../docs/orthanc-setup.md). |

Reload the VS Code window after editing `mcp.json` for changes to take effect
(VS Code spawns the MCP server process on load). See
[architecture.md §4](../docs/architecture.md#4-copilot-side-artifacts) for how
this fits into the overall Copilot-side artifact layout.
