# Orthanc setup (without Docker Compose)

This guide runs Orthanc directly with Docker using a single container command. It does not require Docker Compose.

## 1. Prerequisites

Make sure Docker is installed and running. If not, follow the Docker with WSL guide first.

### Verify
Run:

```powershell
docker version
```

You should see Docker client and server information.

## 2. Create a local folder for Orthanc data

Create a folder where Orthanc can store files:

```powershell
mkdir C:\orthanc-data -Force
```

### Verify
Run:

```powershell
dir C:\orthanc-data
```

The folder should exist.

## 3. Run the Orthanc container

Run the following command:

```powershell
docker run -d `
  --name orthanc `
  -p 8042:8042 `
  -p 4242:4242 `
  -v C:/orthanc-data:/var/lib/orthanc/db `
  jodogne/orthanc
```

### Verify
Run:

```powershell
docker ps
```

You should see a container named `orthanc` in the list.

## 4. Open the Orthanc web interface

Open your browser and navigate to:

- http://localhost:8042/ OR http://localhost:8042/app/explorer.html

You should see the Orthanc web interface. Credentials: orthanc/orthanc

## 5. Optional: verify the DICOM port

Orthanc listens for DICOM traffic on port 4242. You can verify that the port is open from the host:

```powershell
Test-NetConnection -ComputerName localhost -Port 4242
```

### Verify
The output should indicate that the TCP port is open.

## 6. Stop or remove the container

To stop it:

```powershell
docker stop orthanc
```

To remove it:

```powershell
docker rm orthanc
```

### Verify
Run:

```powershell
docker ps -a --filter name=orthanc
```

You should see the container status after stopping or removal.
