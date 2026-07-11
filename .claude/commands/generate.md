---
description: Generate synthetic DICOM instances into the PACS
allowed-tools: mcp__pixel-atlas__resolve_seed, mcp__pixel-atlas__generate_study, mcp__pixel-atlas__validate_dataset, mcp__pixel-atlas__store_to_pacs
argument-hint: modality=<CT|MR|US|...> count=<n> [body_part=] [orientation=] [enhanced=true] [cine_rate=<n>] [tag=value ...]
---

# /generate modality=<CT|MR|US|...> count=<n> [body_part=] [orientation=] [enhanced=true] [cine_rate=<n>] [tag=value ...]

$ARGUMENTS

**Use the one-shot `generate_study` tool. This is a 2-call flow. Do NOT author a
spec by hand, do NOT call `get_iod_requirements`, do NOT read any files.**

1. Call `generate_study(modality, count, body_part?, orientation?, enhanced?,
   cine_rate?, overrides?)`. Put any `tag=value` requests in `overrides`.
   - Multi-frame (e.g. "multi-frame US", "cine", "enhanced CT"): pass
     `enhanced=true`; `count` is the number of frames; pass `cine_rate` for US.
   - It returns `{job_id, study_uid, count, frames, output_path, validation, approx_tokens}`,
     or a precise `error`. **If it returns an error, report it to the user and
     stop — do NOT retry the same call in a loop.** (Optionally call `resolve_seed`
     first only if the user wants to reuse existing PACS data.)
2. Show the user a compact summary (study_uid, count/frames, validation=passed,
   approx_tokens) and ask them to confirm the store.
3. On confirmation, call `store_to_pacs(output_path, confirm_store=True)` and
   report stored/failed counts.

Optionally run `validate_dataset(path=output_path)` before storing if you want to
re-show conformance, but `generate_study` already validated a probe instance.

Never dump raw per-instance tags. One `generate_study` call, one confirmation, one
store — nothing else.
