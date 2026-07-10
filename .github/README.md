# `.github/`

Copilot-side artifacts for the Pixel Atlas agent (Path A / VS Code, see
[architecture.md §4](../docs/architecture.md#4-copilot-side-artifacts)).

| Path | Purpose |
|---|---|
| `copilot-instructions.md` | Repo-wide context included on every Copilot Chat request: what Pixel Atlas is, the PACS-first/template-fallback rule, no-PHI rule, confirmation thresholds. Kept short deliberately — see [solution-design.md §14](../docs/solution-design.md#14-token--cost-economy) (token economy). |
| `chatmodes/pixel-atlas.chatmode.md` | The `Pixel Atlas` chat mode — scopes the available tools to `pixel-atlas/*` only (plus minimal file-read tools) and pins the model to GPT-4o. Select this chat mode in Copilot Chat before running any `/generate`, `/modify`, etc. |
| `prompts/*.prompt.md` | One file per slash command (`/status`, `/list-templates`, ...). Each declares the specific MCP tools it needs (least-privilege per command) and the instructions for using them. Only add a prompt file once the underlying MCP tool actually exists in `mcp-server/server.py` — see [mcp-server/README.md](../mcp-server/README.md). |

## Current prompt files

| Command | Status | Backing tool(s) |
|---|---|---|
| `/status` | ✅ implemented | `health_check`, `get_job_status` |
| `/list-templates` | ✅ implemented | `list_templates` |
| `/generate` | ✅ implemented | `get_template_info`, `resolve_seed`, `generate_dataset`, `validate_dataset`, `store_to_pacs` |
| `/modify` | ✅ implemented | `list_pacs_studies`, `get_template_info`, `modify_dataset`, `validate_dataset`, `store_to_pacs` |
| `/validate` | ✅ implemented | `validate_dataset` (standalone, `path=` or `study=`) |
| `/check-feature` | ✅ implemented | `check_pacs_feature` |
| *(none — no dedicated slash command)* | ✅ implemented | `get_iod_requirements` — read-only IOD knowledge-base lookup (mandatory/conditional/optional modules + tags for a template or SOP Class UID). Reachable via natural language under the chatmode's `pixel-atlas/*` scope; documented directly in `pixel-atlas.chatmode.md` rather than as its own command, since it's consulted internally (by `/generate` and `/modify` tag planning) more often than invoked standalone. |

See [docs/execution-plan-3day.md](../docs/execution-plan-3day.md) for the
build schedule these map to. Every prompt file scopes `tools:` down to just
what that command needs — this isn't just tidiness, it's what keeps the
model from wandering into unrelated tools (e.g. calling `get_job_status`
speculatively) when a request is a bit open-ended. `check_pacs_feature`
originally had no dedicated prompt file and relied on chatmode-level
guidance only; that gap is what caused exactly this kind of wandering in
practice (a real report: asking about Modality LUT presence sent the model
into a `get_job_status(job_id="dummy")` retry loop instead), which is why
`/check-feature` was added.
