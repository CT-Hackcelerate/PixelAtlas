---
description: Check Pixel Atlas environment or job status
allowed-tools: mcp__pixel-atlas__health_check, mcp__pixel-atlas__get_job_status
argument-hint: "[job=<job_id>]"
---

# /status [job=<job_id>]

$ARGUMENTS

If `job` is given, call `get_job_status` with that job_id and report its
state, progress, and message.

If no `job` is given, call `health_check` and report a short status table:
MCP server, KB edition, Orthanc reachability, and which DCMTK binaries
(`storescu`/`dcmftest`, both optional) are found on PATH.
