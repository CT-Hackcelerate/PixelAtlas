# `.vscode/`

Workspace-level VS Code configuration.

| File | Purpose |
|---|---|
| `mcp.json` | Registers the `pixel-atlas` MCP server with VS Code's Copilot Agent Mode. Points at the repo-root `.venv` Python interpreter running `mcp-server/server.py`, and sets the env vars the server reads via `mcp-server/config.py` (recipes/staging/log paths, Orthanc URL + credentials). Edit `env` here if your Orthanc instance uses different host/port/credentials than the [default setup](../docs/SETUP.md#part-4-orthanc-pacs-local-test-environment). |

Reload the VS Code window after editing `mcp.json` for changes to take effect
(VS Code spawns the MCP server process on load — see
[SETUP.md#restarting-the-mcp-server](../docs/SETUP.md#restarting-the-mcp-server)).
See [architecture.md §4](../docs/architecture.md#4-component-map) for how this
server fits into the overall component layout.
