# Pixel Atlas Setup Guide

Complete installation and configuration for Pixel Atlas (one-stop guide).

## Prerequisites

- Windows 11 with admin access
- ~20 GB disk space (for Docker + Orthanc data)
- Python 3.11+ (`winget install Python.Python.3.11`)

---

## Fastest path: `scripts/setup.ps1`

Once Docker Desktop, Git, and VS Code are installed (Parts 1-2 below),
`scripts/setup.ps1` automates the rest of this guide (Orthanc container,
`.venv` + `mcp-server` dependencies, DCMTK check, `health_check`
verification):

```powershell
cd C:\dev\PixelAtlas
.\scripts\setup.ps1
```

See [scripts/README.md](../scripts/README.md) for what it covers. The manual
steps below are for troubleshooting or understanding what the script does.

---

## Part 1: Docker & WSL Setup

### 1.1 Install WSL (Windows Subsystem for Linux)

```powershell
# Run as Administrator
wsl --install
```

Restart your machine if prompted.

**Verify:**
```powershell
wsl --status
```

You should see Ubuntu as the default distribution.

### 1.2 Install Docker Desktop

1. Download from https://www.docker.com/products/docker-desktop/
2. Run the installer with default settings
3. **Important:** Enable "Use WSL 2 based engine" and WSL integration during setup
4. Start Docker Desktop from the Start menu

**Verify:**
```powershell
docker version
```

You should see client and server versions.

---

## Part 2: Git & VS Code

### 2.1 Install Git for Windows

Download from https://git-scm.com/download/win and install with default settings.

**Verify:**
```powershell
git --version
```

### 2.2 Install Visual Studio Code

Download from https://code.visualstudio.com/ and install.

**Recommended extensions** (install via Extensions tab Ctrl+Shift+X):
- Python (Microsoft)
- Docker (Microsoft)
- Remote - WSL (Microsoft)
- GitLens (GitKraken)

---

## Part 3: Pixel Atlas Repository

### 3.1 Clone the repository

```powershell
cd C:\dev
git clone https://github.com/your-org/PixelAtlas.git
cd PixelAtlas
```

### 3.2 Open in VS Code

```powershell
code .
```

---

## Part 4: Orthanc PACS (local test environment)

### 4.1 Create data folder

```powershell
mkdir C:\orthanc-data -Force
```

### 4.2 Start Orthanc container

```powershell
docker run -d `
  --name orthanc `
  -p 8042:8042 `
  -p 4242:4242 `
  -v C:\orthanc-data:/var/lib/orthanc/db `
  jodogne/orthanc
```

**Verify:**
```powershell
docker ps
```

You should see the orthanc container running.

### 4.3 Access Orthanc Web UI

Open http://localhost:8042 in your browser.

- **Username:** orthanc
- **Password:** orthanc

---

## Part 5: MCP Server Setup

### 5.1 Create the venv and install dependencies

```powershell
cd C:\dev\PixelAtlas
python -m venv .venv
.\.venv\Scripts\pip.exe install -r mcp-server\requirements.txt
```

(`scripts/setup.ps1` does this step for you and is idempotent if `.venv`
already exists.)

### 5.2 Verify the MCP server starts

```powershell
cd C:\dev\PixelAtlas\mcp-server
..\.venv\Scripts\python.exe -c "import server, json; print(json.dumps(server.health_check()))"
```

You should see a JSON result with `"orthanc_reachable": true`. This runs the
server's `health_check` directly, without going through VS Code — useful for
isolating whether a problem is in the Python environment/Orthanc connection
vs. the MCP client wiring in Part 6.

---

## Part 6: Configure Claude Code / Copilot Agent Mode

### 6.1 Open MCP Settings

In VS Code, open `.vscode/mcp.json` and verify it matches (paths are
workspace-relative via `${workspaceFolder}`, so this normally needs no
edits unless your Orthanc instance uses different host/port/credentials):

```json
{
  "servers": {
    "pixel-atlas": {
      "command": "${workspaceFolder}/.venv/Scripts/python.exe",
      "args": ["${workspaceFolder}/mcp-server/server.py"],
      "env": {
        "PIXEL_ATLAS_RECIPES": "${workspaceFolder}/recipes",
        "PIXEL_ATLAS_STAGING": "${workspaceFolder}/staging",
        "PIXEL_ATLAS_LOG_DIR": "${workspaceFolder}/.pixel-atlas/logs",
        "ORTHANC_URL": "http://localhost:8042",
        "ORTHANC_USER": "orthanc",
        "ORTHANC_PASSWORD": "orthanc"
      }
    }
  }
}
```

There is also a repo-root `.mcp.json` (same server, relative paths, no
`PIXEL_ATLAS_*` overrides) used by Claude Code outside of VS Code's own MCP
integration — keep both in sync if you change the Orthanc connection details.

### 6.2 Test MCP connection

Open Claude Code (or Copilot Agent Mode) in VS Code and try:

```
health_check()
```

You should see:
- MCP server: ok
- Orthanc reachable: true

---

## Restarting the MCP server

VS Code spawns `mcp-server/server.py` as a subprocess when the window loads
and keeps it running for the life of that window — it does **not** hot-reload
when you edit server-side Python (`mcp-server/*.py`). Restart after any
change there, or if the server seems stuck/unresponsive:

**Preferred — reload the VS Code window:**
1. Command Palette (`Ctrl+Shift+P`) → **Developer: Reload Window** (or, if
   available in your Copilot/Claude Code version, **MCP: List Servers** →
   select `pixel-atlas` → **Restart**).
2. VS Code respawns the server process on reload; the next tool call will use
   the updated code.

**Fallback — kill the process directly** (if a reload doesn't pick up the
change, or the window is unresponsive):
```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -like '*mcp-server*server.py*' } |
  Select-Object ProcessId, CommandLine
```
Confirm which PID(s) belong to the session you mean to restart (multiple
windows/workspaces each spawn their own copy — killing all of them will
restart every open session's server, not just yours), then:
```powershell
Stop-Process -Id <pid> -Force
```
The host reconnects and relaunches the server automatically on the next MCP
tool call. There's no "restart" RPC to call from inside a chat session —
this process-level restart (or a window reload) is the only way.

---

## Troubleshooting

### Orthanc won't start
```powershell
# Check if port 8042/4242 is already in use
netstat -ano | findstr :8042

# If port is in use, stop the existing container
docker stop orthanc
docker rm orthanc
# Then re-run the start command above
```

### MCP server won't connect
- Ensure Python 3.11+ is installed: `python --version`
- Check `mcp-server/requirements.txt` packages are installed in `.venv`:
  `.\.venv\Scripts\pip.exe list`
- Verify `.vscode/mcp.json` / `.mcp.json` point at `.venv\Scripts\python.exe`
  (not a bare `python`, which may resolve to a different interpreter)
- If you edited server code or `mcp.json` and nothing changed, restart the
  server — see [Restarting the MCP server](#restarting-the-mcp-server) above

### Can't connect to Orthanc
- Verify Docker is running: `docker ps`
- Verify Orthanc container exists: `docker ps -a`
- Check firewall isn't blocking port 8042

### ImportError when starting MCP server
```powershell
# Reinstall dependencies into the project .venv (create it first if missing)
python -m venv .venv
.\.venv\Scripts\pip.exe install --upgrade -r mcp-server\requirements.txt
```
Then restart the MCP server (see above) so it picks up the reinstalled
packages.

---

## Quick Test

After all steps are complete:

1. Open VS Code
2. Open Claude Code
3. Try: "Generate 3 CT instances"
4. Confirm and store to PACS
5. Visit http://localhost:8042 and verify the study appears

---

## Next Steps

- Read [QUICKSTART.md](QUICKSTART.md) for common workflows
- See [solution-design.md](solution-design.md) for how the system works
- Check [sample-prompts.md](sample-prompts.md) for example requests
- See [scripts/README.md](../scripts/README.md) for what `setup.ps1` automates
