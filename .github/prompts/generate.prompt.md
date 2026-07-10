---
description: Generate synthetic DICOM instances into the PACS
mode: agent
tools: ["pixel-atlas/get_template_info", "pixel-atlas/resolve_seed", "pixel-atlas/generate_dataset", "pixel-atlas/validate_dataset", "pixel-atlas/store_to_pacs"]
---

# /generate modality=<CT> count=<n> [orientation=] [body_part=] [tag=value ...] [prior_of=<study_uid> days_before=<n>]

Follow this exact sequence (solution-design.md §2, §4):

1. Call `get_template_info` for the requested modality to learn its
   `protected_tags` — the only tags that CAN'T be overridden (tags this
   generator computes itself per-instance, plus UIDs it always regenerates).
   Reject any `tag=value` override that's in `protected_tags`, or that isn't
   a valid tag for the template's IOD (`get_iod_requirements`) — ask the user
   to correct it. Anything else is a valid override.
2. Call `resolve_seed(modality, body_part, orientation)`.
   - If `source_type=pacs` and there's more than one candidate, present up
     to 5 (StudyInstanceUID, description, date) and ask the user to pick
     one, or to use the template fallback instead.
   - If `source_type=template`, tell the user plainly that no similar data
     was found in the PACS and ask for explicit confirmation before using
     the bundled template seed. Do not proceed without that confirmation.
   - If `source_type=none`, report the closest alternatives from
     `closest_alternatives` and stop — no generation happens.
3. If `count` > 50, confirm with the user before proceeding (large-batch
   confirmation, independent of the template-fallback confirmation above).
4. If `prior_of=<study_uid>` was given, `days_before` is required (a positive
   integer number of days before the reference study's StudyDate). Pass both
   through to `generate_dataset` as `prior_of_study_uid`/`days_before` — this
   reuses that study's PatientID/PatientName/StudyDate (offset earlier) instead
   of drawing a new synthetic patient, so the result reads as a genuine prior
   for comparison. It still gets its own independent StudyInstanceUID (never an
   in-place edit of the reference study).
5. Call `generate_dataset(template_id, seed_source, count, overrides, prior_of_study_uid?, days_before?)`
   using the `seed_source` resolved (and confirmed) in step 2.
6. Call `validate_dataset(output_path)`. If `passed` is false, stop and
   report the errors — do not call `store_to_pacs`. Always relay the
   `iod_conformance` summary in the report alongside the pass/fail result
   (files_with_errors and example_errors, if any).
7. **Before storing anything to the PACS**, show the user a summary of what's
   about to happen — study_uid, instance count, seed source, the validation
   result, any overrides applied — and ask them to confirm the store. This
   is a separate confirmation from the template-fallback one (step 2) and
   the >50-count one (step 3); it applies to every `/generate` call
   regardless of count or seed source, because storing is the one step that
   actually reaches the shared PACS. Only call
   `store_to_pacs(output_path, confirm_store=True)` after that confirmation
   — the tool rejects the call without `confirm_store=True`, so don't skip
   passing it even if you're confident the user already agreed.
8. Report a compact summary: job_id, study_uid, instance count, seed source
   used, validation result, and stored/failed counts. If this was a prior,
   also state the shared PatientID and the computed StudyDate. Never dump raw
   per-instance tag data into the chat.
