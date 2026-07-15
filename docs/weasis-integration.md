# Connecting Weasis to Orthanc

Steps to view/query PixelAtlas-generated studies from Weasis against the
local Orthanc PACS, using classic DICOM networking (C-FIND/C-MOVE/C-STORE)
— no DICOMweb plugin required, works with the plain `jodogne/orthanc` image
used in [SETUP.md](SETUP.md).

## Prerequisites

- Orthanc running and reachable at `http://localhost:8042` (web) /
  `localhost:4242` (DICOM), per [SETUP.md](SETUP.md) Part 4.
- Weasis installed and running locally.

## 1. Enable Weasis's local DICOM listener

Weasis needs its own DICOM SCP server running so Orthanc can send it images
via C-MOVE/C-STORE. In Weasis:

1. **File → Preferences → DICOM Listener** (distinct from the DICOM Node
   list below — this is the toggle that actually binds a port).
2. Enable the local listener.
3. Set an AE Title (e.g. `WEASIS-AE`) and a port (e.g. `11112`).
4. Restart Weasis if the setting doesn't take effect immediately.

Verify it's actually listening:

```powershell
Test-NetConnection -ComputerName localhost -Port 11112
# TcpTestSucceeded should be True
```

## 2. Add DICOM nodes in Weasis

In Weasis's DICOM Node list, add two entries:

**Weasis itself** (so Weasis knows its own identity for C-MOVE destination):
| Field | Value |
|---|---|
| Description / AE title | `WEASIS-AE` |
| Hostname | `localhost` |
| Port | `11112` |
| Usage type | Both |

**Orthanc**:
| Field | Value |
|---|---|
| Description / AE title | `ORTHANC` |
| Hostname | `localhost` |
| Port | `4242` |
| Usage type | Both |

> Confirm Orthanc's actual AE title/port match by checking
> `http://localhost:8042/system` → `DicomAet` / `DicomPort` (default
> `ORTHANC` / `4242`). A common mistake is transposing digits (e.g. `4442`
> instead of `4242`).

## 3. Register Weasis as a known modality in Orthanc

Orthanc only C-MOVEs to destinations it knows about. Register Weasis via the
REST API (persists in Orthanc's database — no config file edit or restart
needed):

```powershell
curl -u orthanc:orthanc -X PUT http://localhost:8042/modalities/weasis `
  -H "Content-Type: application/json" `
  -d '{\"AET\": \"WEASIS-AE\", \"Host\": \"host.docker.internal\", \"Port\": 11112}'
```

Use `host.docker.internal` (not `localhost`) as the host — Orthanc runs
inside the Docker container and needs the special DNS name to reach back out
to the Windows host where Weasis is listening.

## 4. Test the connection

```powershell
curl -u orthanc:orthanc -X POST http://localhost:8042/modalities/weasis/echo
```

Empty body / HTTP 200 = success. If you get a connection error, re-check
step 1 — Weasis's listener isn't bound to the port Orthanc is trying to
reach.

## 5. Query/retrieve

In Weasis, use the query dialog against the `ORTHANC` node to C-FIND studies,
then retrieve (C-MOVE) into the local viewer.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `connection refused: getsockopt` on echo | Weasis's local DICOM listener isn't enabled/running — check step 1, verify with `Test-NetConnection`. |
| Echo works but C-MOVE retrieve fails | AE title/port mismatch between the Weasis node entry and what's registered in Orthanc (`GET /modalities/weasis`) — they must match exactly. |
| Nothing under `/plugins` in Orthanc | Expected on `jodogne/orthanc` — that image ships no plugins. Not required for this classic DICOM Q/R flow; only relevant if you later want DICOMweb (see SETUP.md discussion). |
