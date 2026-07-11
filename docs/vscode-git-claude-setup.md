# VS Code, Git, and Claude setup

This guide helps you set up a local development environment on Windows for working with this repository.

## 1. Install Visual Studio Code

1. Download and install Visual Studio Code from https://code.visualstudio.com/.
2. Launch VS Code.
3. Install the following recommended extensions:
   - Python
   - Docker
   - GitLens
   - Remote - WSL
   - Claude (if available in your environment) or the Claude Code extension

### Verify
- Open the Command Palette with Ctrl+Shift+P.
- Run "Extensions: Show Installed Extensions".
- Confirm the extensions appear in the list.
- In a terminal, run:

```powershell
code --version
```

You should see a version number.

## 2. Install Git for Windows

1. Download Git from https://git-scm.com/download/win.
2. Run the installer with the default settings.

### Verify
Run:

```powershell
git --version
```

You should see the Git version.

## 3. Set up a Linux environment

1. Open PowerShell as Administrator.
2. Run:

```powershell
wsl --install -d Ubuntu
```
3. Restart your machine if prompted.
4. After reboot, open Ubuntu and create a user account.

### Verify
Run:

```powershell
wsl --status
```

You should see that the Linux environment is installed and ready to use.

## 4. Install Claude support

This project is driven via **Claude Code** (the CLI / VS Code extension), not
just the browser chat — it's what actually calls the Pixel Atlas MCP tools.

1. Install the Claude Code extension from the VS Code Extensions view (or the
   standalone CLI) and sign in.
2. `.mcp.json` at the repo root registers the `pixel-atlas` MCP server for
   Claude Code automatically — no extra config needed once it's running (see
   [SETUP.md](SETUP.md)).
3. The browser chat at https://claude.ai/ is still useful for ad hoc
   questions, but it cannot call this project's MCP tools — use Claude Code
   for anything that generates/modifies/validates DICOM data.

### Verify
- In VS Code, open the Command Palette and confirm Claude Code commands appear.
- Run `claude` (or open the extension) in the repo root and confirm it can see
  the `pixel-atlas` MCP server (e.g. ask it to run `/status`).

## 5. Clone the repository

1. Open a terminal in the folder where you want the project to live.
2. Run:

```powershell
git clone <your-repo-url>
cd Pixel-Atlas
```

### Verify
Run:

```powershell
dir
```

You should see the repository folder and its files.
