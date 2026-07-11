Pixel Atlas generates/modifies synthetic DICOM test data via the local
`pixel-atlas` MCP server, storing results in a local Orthanc PACS.

How generation works: **prefer the one-shot `generate_study` tool** — it builds a
conformant study by itself (server-side defaults + auto-fill). You do NOT author
DICOM tags, do NOT call `get_iod_requirements`, and NEVER read files from disk for
generation. Flow: `generate_study(...)` → confirm → `store_to_pacs`.

Core rules:
- **Never loop.** If a tool returns an `error`, report it and stop — do not retry
  the same call hoping for a different result. Respond precisely and concisely.
- One `generate_study` call = one study. Multi-frame/cine: `enhanced=true`,
  `count` = frames, `cine_rate` for US. Tag requests → `overrides`.
- Advanced only (edit an existing study, PR/KO, or a case `generate_study` can't
  build): use `extract_spec`/`validate_spec`/`materialize_dataset`.
- Supported scan types: standard image IODs (single- and multi-frame) plus PR and
  KO. For anything else (SR, RT, SEG, encapsulated docs, …) say it's unsupported —
  never substitute.
- Never generate real PHI. This is a test tool on test data.
- Confirm before creating/overwriting >50 instances or any in-place PACS overwrite.
- Always confirm before `store_to_pacs` (needs `confirm_store=True`); show the
  validation result first.
- Report compact summaries (UIDs, counts, pass/fail, approx_tokens) — never dump
  raw per-instance tags.

See docs/ai-driven-comprehensive-plan.md and docs/solution-design.md.
