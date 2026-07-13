---
description: Generate synthetic DICOM instances into the PACS
mode: agent
tools: ["pixel-atlas/find_recipe", "pixel-atlas/resolve_seed", "pixel-atlas/get_iod_requirements", "pixel-atlas/describe_attributes", "pixel-atlas/extract_spec", "pixel-atlas/validate_spec", "pixel-atlas/materialize_dataset", "pixel-atlas/validate_dataset", "pixel-atlas/store_to_pacs"]
---

# /generate modality=<CT|MR|US|...> count=<n> [body_part=] [orientation=] [enhanced=true] [tag=value ...]

**Check the recipe cache before authoring anything by hand.**

1. `find_recipe(modality, body_part?, orientation?, enhanced?, contrast?,
   localizer?)`.
   - **Hit**: take `spec` from the result. Apply any `tag=value` requests
     directly into its `attributes`/`perInstance`. Go to step 3.
   - **Miss**: step 2.
2. Author the spec. `resolve_seed(modality, body_part?, orientation?,
   enhanced?)`:
   - `source_type: "pacs"` → `extract_spec(study_uid=<candidate>)`.
   - `source_type: "iod"` → `get_iod_requirements(modality, enhanced?)`
     (compact — never pass `full=true` here), `describe_attributes` for any
     tag you're unsure of, then write the Generation Spec yourself: `request`
     (modality, instanceCount, seedSource), `attributes` (flat
     `{Keyword: value}` map), `perInstance` rules, `pixel` directive,
     `identity`. Multi-frame (e.g. "multi-frame US", "cine", "enhanced CT"):
     set `enhanced=true` on `resolve_seed`/`get_iod_requirements`,
     `instanceCount` = number of frames, and for classic cine set
     `CineRate`/`FrameTime` (or `FrameTimeVector`) in `attributes` yourself.
   - Put any `tag=value` requests from the user into `attributes`
     (uniform) or `perInstance` (varying per instance).
3. `validate_spec(spec)`. **On error, fix exactly the reported tags and
   retry at most a couple of times — never loop on the same failure.** On
   success you get `spec_id`.
4. `materialize_dataset(spec_id, instance_count=count)`. Returns
   `{job_id, study_uid, count, frames?, output_path, validation, approx_tokens}`
   or a precise `error` (report and stop, don't retry blindly).
5. Show the user a compact summary (study_uid, count/frames,
   validation=passed, approx_tokens) and ask them to confirm the store.
6. On confirmation, call `store_to_pacs(output_path, confirm_store=True)` and
   report stored/failed counts.

`materialize_dataset` already validates a probe instance — only run a
standalone `validate_dataset(path=output_path)` if you want to re-show full
conformance before storing.

Never dump raw per-instance tags or the full spec JSON to the user — report
compact summaries only.
