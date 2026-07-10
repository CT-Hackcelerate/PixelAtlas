# Docker with WSL setup (without Docker Compose)

This guide installs Docker Desktop and enables it to work with WSL so you can run containers from a Linux environment.

## 1. Install WSL

If you have not already installed WSL, run the following in PowerShell as Administrator:

```powershell
wsl --install
```

Restart your machine if required.

### Verify
Run:

```powershell
wsl --status
```

You should see a default Ubuntu distribution.

## 2. Install Docker Desktop

1. Download Docker Desktop from https://www.docker.com/products/docker-desktop/.
2. Install it with the default settings.
3. During setup, enable WSL 2 integration.
4. Start Docker Desktop.

### Verify
Open a terminal and run:

```powershell
docker version
```

You should receive client and server version information.

## 3. Enable Docker integration with WSL

1. Open Docker Desktop.
2. Go to Settings > General.
3. Ensure "Use the WSL 2 based engine" is enabled.
4. Go to Settings > Resources > WSL Integration.
5. Enable the Ubuntu distribution you installed.

### Verify
From PowerShell or Ubuntu, run:

```powershell
docker info
```

You should see Docker system information instead of an error about the daemon not running.

## 4. Test Docker

Run:

```powershell
docker run --rm hello-world
```

### Verify
If the container starts successfully, Docker is working correctly.

## 5. Optional: use Docker from WSL

Open Ubuntu and confirm Docker works there too:

```bash
docker version
```

### Verify
If both PowerShell and WSL can run Docker commands, the integration is working.
