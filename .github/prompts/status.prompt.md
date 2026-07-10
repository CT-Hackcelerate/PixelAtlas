---
description: Check Pixel Atlas environment or job status
mode: agent
tools: ["pixel-atlas/health_check", "pixel-atlas/get_job_status"]
---

# /status [job=<job_id>]

If `job` is given, call `get_job_status` with that job_id and report its
state, progress, and message.

If no `job` is given, call `health_check` and report a short status table:
MCP server, template count, Orthanc reachability, and which DCMTK binaries
are found on PATH (expected to be missing until the DCMTK wrapper lands).
