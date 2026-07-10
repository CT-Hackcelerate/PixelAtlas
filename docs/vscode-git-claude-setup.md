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

Use the browser-based Claude experience rather than a local CLI install:

1. Open your browser and go to https://claude.ai/.
2. Sign in with CT account.
3. If you want to use it from VS Code, install the Claude extension from the Extensions view and sign in there as well.

### Verify
- Open https://claude.ai/ and confirm that you can sign in successfully.
- In VS Code, open the Command Palette and confirm that Claude-related commands appear after the extension is installed.

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
