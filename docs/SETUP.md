# Pixel Atlas Setup Guide

Complete installation and configuration for Pixel Atlas (one-stop guide).

## Prerequisites

- Windows 11 with admin access
- ~20 GB disk space (for Docker + Orthanc data)

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

### 5.1 Install Python dependencies

```powershell
cd C:\dev\PixelAtlas\mcp-server
pip install -r requirements.txt
```

### 5.2 Verify MCP server starts

```powershell
python server.py
```

You should see:
```
MCP server started...
```

Press `Ctrl+C` to stop. It will start automatically when Claude connects.

---

## Part 6: Configure Claude Code

### 6.1 Open MCP Settings

In VS Code, open `.vscode/mcp.json` and verify:

```json
{
  "mcpServers": {
    "pixel-atlas": {
      "command": "python",
      "args": ["c:\\dev\\PixelAtlas\\mcp-server\\server.py"],
      "env": {
        "ORTHANC_URL": "http://localhost:8042",
        "ORTHANC_USER": "orthanc",
        "ORTHANC_PASSWORD": "orthanc"
      }
    }
  }
}
```

Update paths if your repo is in a different location.

### 6.2 Test MCP connection

Open Claude Code in VS Code and try:

```
/health_check
```

You should see:
- MCP server: ok
- Orthanc reachable: true

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
- Ensure Python 3.10+ is installed: `python --version`
- Check `requirements.txt` packages are installed: `pip list`
- Verify `.vscode/mcp.json` has correct paths (use absolute paths)

### Can't connect to Orthanc
- Verify Docker is running: `docker ps`
- Verify Orthanc container exists: `docker ps -a`
- Check firewall isn't blocking port 8042

### ImportError when starting MCP server
```powershell
# Reinstall dependencies
pip install --upgrade -r requirements.txt

# If using a venv, activate it first
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

---

## Quick Test

After all steps are complete:

1. Open VS Code
2. Open Claude Code
3. Try: `generate_study(modality="CT", count=3)`
4. Confirm and store to PACS
5. Visit http://localhost:8042 and verify the study appears

---

## Next Steps

- Read [QUICKSTART.md](QUICKSTART.md) for common workflows
- See [solution-design.md](solution-design.md) for how the system works
- Check [sample-prompts.md](sample-prompts.md) for example requests
