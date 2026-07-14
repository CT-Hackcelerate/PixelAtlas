Pixel Atlas generates/modifies synthetic DICOM test data via the local
`pixel-atlas` MCP server, storing results in a local Orthanc PACS.

How generation works: **check `find_recipe` first** — a cache hit returns a
previously-validated spec, skip straight to `validate_spec`. On a miss, you
author the DICOM Generation Spec yourself, grounded via
`get_iod_requirements`/`describe_attributes` (or `extract_spec` from a
matching PACS study via `resolve_seed`) — the server only grounds
(`validate_spec`) and builds (`materialize_dataset`); it never guesses tag
values for you. Flow: `find_recipe` → (author or reuse) → `validate_spec` →
`materialize_dataset` → confirm → `store_to_pacs`.

Core rules:
- **Never loop.** If a tool returns an `error`, report it and stop — do not retry
  the same call hoping for a different result. A `validate_spec` failure gets at
  most a couple of targeted repairs (fix exactly the reported tags) before you
  stop and ask. Respond precisely and concisely.
- Multi-frame/cine: `instanceCount` = frames; set Cine Module timing
  (`CineRate`/`FrameTime` or `FrameTimeVector`) yourself in `attributes`. Tag
  requests → `attributes` (uniform) or `perInstance` (varying).
- Editing an existing study: `modify_dataset(study_uid, overrides?, ...)` directly
  (self-contained, not part of the spec-authoring flow). PR/KO: author a spec with
  a `references` block naming existing target instances, then `validate_spec` →
  `materialize_dataset`.
- Supported scan types: standard image IODs (single- and multi-frame) plus PR and
  KO. For anything else (SR, RT, SEG, encapsulated docs, …) say it's unsupported —
  never substitute.
- Never generate real PHI. This is a test tool on test data.
- Confirm before creating/overwriting >50 instances or any in-place PACS overwrite.
- Always confirm before `store_to_pacs` (needs `confirm_store=True`); show the
  validation result first.
- Report compact summaries (UIDs, counts, pass/fail, approx_tokens) — never dump
  raw per-instance tags or the full spec JSON.

See docs/architecture.md and docs/solution-design.md.
