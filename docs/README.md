# `docs/`

Design and setup documentation for Pixel Atlas. Start with the root
[README.md](../README.md) for the reading order — this folder holds the
detailed docs it links to:

| File | Covers |
|---|---|
| `use-cases.md` | Actors, commands, and detailed use cases (the **what**) |
| `solution-design.md` | Workflow, template system, validation, token economy (the **how**) |
| `architecture.md` | Components, MCP server tool contract, deployment, diagrams |
| `execution-plan-phases1-3.md` | The actual build schedule/scope being implemented right now, with a running done/not-done checklist — check this first to see current progress |
| `implementation-status.md` | Phase-by-phase build log, local dev environment setup, Copilot Chat testing steps, troubleshooting table, and what's not yet implemented |
| `orthanc-setup.md` | Running the reference Orthanc PACS via Docker |
| `docker-wsl-setup.md` | Docker Desktop + WSL2 setup on Windows |
| `vscode-git-claude-setup.md` | VS Code, Git, and Claude/Copilot setup |

Design docs (`use-cases.md`/`solution-design.md`/`architecture.md`) describe
the full v1 scope; `execution-plan-phases1-3.md` tracks what's actually been built
so far, which is a deliberately cut-down slice of that scope.
