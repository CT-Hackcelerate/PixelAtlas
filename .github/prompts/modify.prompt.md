---
description: Modify tags on an existing PACS study
mode: agent
tools: ["pixel-atlas/get_template_info", "pixel-atlas/list_pacs_studies", "pixel-atlas/modify_dataset", "pixel-atlas/validate_dataset", "pixel-atlas/store_to_pacs"]
---

# /modify study=<StudyInstanceUID> [tag=value ...] [regenerate_uids=true|false]

Follow this exact sequence (solution-design.md §9):

1. Resolve the source study. If `study=` wasn't given, or doesn't look like a
   UID, use `list_pacs_studies` to help the user find it — this is a direct,
   user-named lookup (they already know which study they want to modify), not
   the similarity search behind `/generate`.
2. Validate overrides: if the study's modality has a matching template, use
   `get_template_info`'s `protected_tags` to reject any override that's
   protected, and use `get_iod_requirements(sop_class_uid=...)` to reject any
   tag that isn't valid for the study's actual IOD — same rule as
   `/generate`.
3. **Always explicitly ask** whether this modification should create a new,
   independent derived study (`regenerate_uids=true`, non-destructive — the
   original is untouched) or overwrite the original study in place
   (`regenerate_uids=false`, destructive). Do not silently default to either
   one just because the user didn't say — this choice materially changes
   what happens to their data, so ask every time `regenerate_uids` wasn't
   stated outright in the request.
   - If the user chooses (or explicitly asked for) the in-place overwrite:
     confirm again, restating plainly that the original study will be
     targeted for overwrite and this cannot be undone from this tool. Only
     after that second confirmation, call `modify_dataset` with
     `regenerate_uids=false` **and** `confirm_destructive=true` — both are
     required; the tool call is rejected otherwise, so don't skip
     `confirm_destructive` even if you're confident the user already agreed.
   - Note: whether the PACS actually overwrites the existing copy depends on
     its own configuration (e.g. Orthanc's `OverwriteInstances` setting) —
     `modify_dataset`'s result includes a `note` field about this when
     `regenerate_uids=false`; always relay it, don't imply the overwrite is
     guaranteed to have taken visible effect.
4. Call `modify_dataset(study_uid, overrides, regenerate_uids, confirm_destructive?)`.
   If the result has an `error` key, report it and stop.
5. Call `validate_dataset(path=output_path)`. If `passed` is false, stop and
   report the errors — do not call `store_to_pacs`.
6. **Before storing anything to the PACS**, show the user a summary of
   what's about to happen — `original_study_uid`, the resulting `study_uid`
   (new or same, depending on `regenerate_uids`), instance count, overrides
   applied, the validation result — and ask them to confirm the store. This
   is a separate confirmation from step 3's same-study-vs-new-study question;
   it applies every time, because storing is the one step that actually
   reaches the shared PACS. Only call
   `store_to_pacs(output_path, confirm_store=True)` after that confirmation.
7. Report a compact summary: `job_id`, `original_study_uid`, `study_uid` (new
   or same, depending on `regenerate_uids`), instance count, validation
   result, stored/failed counts, and — if `regenerate_uids=false` — the
   overwrite-verification caveat from step 3. Never dump raw per-instance tag
   data into the chat.
