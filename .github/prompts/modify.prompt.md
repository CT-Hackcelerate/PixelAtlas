---
description: Modify tags on an existing PACS study
mode: agent
tools: ["pixel-atlas/list_pacs_studies", "pixel-atlas/get_iod_requirements", "pixel-atlas/describe_attributes", "pixel-atlas/modify_dataset", "pixel-atlas/validate_dataset", "pixel-atlas/store_to_pacs"]
---

# /modify study=<StudyInstanceUID> [tag=value ...] [regenerate_uids=true|false]

1. Resolve the source study. If `study=` wasn't given or isn't a UID, use
   `list_pacs_studies` to help the user find it (a direct, user-named lookup).
2. Validate overrides against the study's *actual* IOD with
   `get_iod_requirements(sop_class_uid=…)` / `describe_attributes`. Pixel-module
   and UID tags can't be overridden; `modify_dataset` also rejects them.
3. **Always ask** whether the result should be a new derived study
   (`regenerate_uids=true`, non-destructive) or an in-place overwrite
   (`regenerate_uids=false`, destructive) if the request didn't say. For the
   overwrite, confirm again, then call with `regenerate_uids=false` **and**
   `confirm_destructive=true`. Relay the `note` about the PACS's overwrite policy.
4. `modify_dataset(study_uid, overrides, regenerate_uids, confirm_destructive?)`.
   If the result has an `error`, report it and stop.
5. `validate_dataset(path=output_path)`. If not passed, stop and report; don't store.
6. Confirm (show original_study_uid, resulting study_uid, count, overrides,
   validation), then `store_to_pacs(output_path, confirm_store=True)`.
7. Report a compact summary: job_id, original_study_uid, study_uid, count,
   validation result, stored/failed counts, and the overwrite caveat if destructive.
