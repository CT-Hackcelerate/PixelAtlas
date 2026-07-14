# `.github/` — contents

> Named `CONTENTS.md` rather than `README.md` on purpose: GitHub's repo
> landing page prefers a README found in `.github/` over one in the repo
> root, which would hide the real project README behind this folder-manifest
> page.

Copilot Chat integration: the chat mode, repo-wide instructions, and the
slash-command prompt files that scope the agent to one MCP tool set per
command (mirrors `.claude/commands/` for Claude Code).

| File | Purpose |
|---|---|
| `copilot-instructions.md` | Repo-wide instructions Copilot Chat always loads |
| `chatmodes/pixel-atlas.chatmode.md` | The `pixel-atlas` chat mode definition |
| `prompts/generate.prompt.md` | `/generate` — generate a study |
| `prompts/modify.prompt.md` | `/modify` — edit an existing PACS study |
| `prompts/validate.prompt.md` | `/validate` — validate generated/stored instances |
| `prompts/check-feature.prompt.md` | `/check-feature` — check a tag/value is present in PACS |
| `prompts/list-recipes.prompt.md` | `/list-recipes` — list cached recipes |
| `prompts/status.prompt.md` | `/status` — environment/job status |

See the [root README](../README.md) for the overall architecture and
[docs/README.md](../docs/README.md) for the full documentation index.
