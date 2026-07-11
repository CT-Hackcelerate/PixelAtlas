# Sample prompts

Plain-language prompts to type into your AI coding agent (Claude Code or
Copilot Chat, Pixel Atlas chat mode) for manual testing — not slash commands;
the agent should map them to the right tool calls itself. See
[CLAUDE.md](../CLAUDE.md) for the exact tool contract and golden rules.

## 1. Generate

Expected: `generate_study` → (confirmation) → `store_to_pacs(confirm_store=True)`.

```
Generate 3 axial CT chest instances
```
Expect: one call to `generate_study(modality="CT", count=3, ...)`, a compact
summary (UIDs, count, validation), a confirmation before `store_to_pacs`.

```
Generate 200 axial CT chest scans for load testing
```
Expect: an explicit confirmation before generating (count > 50), then the
usual store confirmation — two distinct confirmations.

```
Generate 5 CT chest instances with PatientSex=F and PatientAge=062Y
```
Expect: passed through as `overrides={"PatientSex": "F", "PatientAge": "062Y"}`.

```
Generate 2 CT instances and set the SOPInstanceUID to 12345
```
Expect: rejected before calling any tool — `SOPInstanceUID` is a
server-generated identifier, never user-settable. The agent should explain
why, not silently drop the override.

```
Generate multi-frame US with 60 frames at 30fps
```
Expect: `generate_study(modality="US", count=60, enhanced=true, cine_rate=30)`
— `count` means frames here, not series, since one multi-frame file is one
instance.

## 2. Priors (advanced flow)

Generating a study that reads as an earlier scan of the same synthetic
patient. Not a `generate_study` parameter — this goes through the manual
spec flow (`request.priorOfStudyUID`/`daysBefore` on the Generation Spec) via
`validate_spec` → `materialize_dataset`. You need a `study_uid` already in the
PACS first (generate one via §1).

```
Generate a prior CT for the same patient as study <study_uid>, 90 days earlier
```
Expect: the result shares `PatientID`/`PatientName` with the reference study,
has a `StudyDate` 90 days earlier, and its own independent
`StudyInstanceUID` — never an edit of the original.

```
Generate a prior study based on <study_uid>
```
Expect: the agent asks how far back rather than picking an arbitrary default
— `daysBefore` has no sensible default.

## 3. Modify

Expected: (locate study) → `modify_dataset` → `validate_dataset` →
(confirmation) → `store_to_pacs`. You need a `study_uid` already in the PACS.

```
/modify study=<study_uid> PatientAge=045Y
```
Expect: the agent asks whether this creates a new derived study
(`regenerate_uids=true`, default) or overwrites in place
(`regenerate_uids=false`) — never assumed silently. A new study gets its own
`StudyInstanceUID`; the original is untouched.

```
Overwrite study <study_uid> in place — set PatientAge=050Y and don't create a new study
```
Expect **three separate steps**: (1) explicit confirmation this is a
destructive, irreversible overwrite; (2) only then
`modify_dataset(regenerate_uids=false, confirm_destructive=true)`; (3) a
**separate** store confirmation. The result should note that whether the PACS
actually overwrote the existing copy depends on Orthanc's own configuration.

```
/modify study=<study_uid> Manufacturer=AcmeCorp SOPClassUID=1.2.3.4
```
Expect: `Manufacturer` accepted (plain IOD-valid tag); `SOPClassUID` rejected
— it's a structural identifier, not a user override.

## 4. Validate

```
/validate path=<output_path from a previous /generate>
```
or
```
/validate study=<study_uid>
```
Expect the full report: `passed`, `checked_instances`, `sampling_ratio`,
`iod_conformance`, the `dcmftest` summary, `errors`/`warnings`.

```
/validate study=not-a-real-study-uid
```
Expect a clear error — never a false `passed: true`.

## 5. Status

```
/status
```
Expect `mcp_server: ok`, `orthanc_reachable`, `dcmtk_binaries_on_path`, and
`kb_edition` (the pinned DICOM standard edition the KB was built from).

```
/status job=<job_id>
```
Expect the job's `state` (`generated`/`modified`/`failed`), `progress_pct`,
`message`.

```
/status job=does-not-exist
```
Expect a clear "no job found" message, not a crash.

## 6. List recipes

A **recipe** is a validated Generation Spec cached from a prior request
(modality + body part + orientation + flags) — a repeat request skips
planning and materializes directly.

```
/list-recipes
```
Expect a compact table of cached recipes (or empty, if none generated yet).

```
/list-recipes modality=MR
```
Expect only MR recipes.

## 7. Generic PACS feature lookup

"Does the PACS already have data with property X" for arbitrary X — no
hardcoded per-feature list. Expected: `check_pacs_feature(tag, value?,
modality?, date_range?)`. The agent must resolve your phrase to the correct
DICOM keyword itself before calling it.

```
Do we have any CT study with a Modality LUT?
```
Expect: resolved to `check_pacs_feature(tag="ModalityLUTSequence", modality="CT")`.

```
Is there a study where RescaleSlope is 1?
```
Expect: `check_pacs_feature(tag="RescaleSlope", value="1")`.

```
Does any study have a weird pixel value scaling?
```
Expect: vague enough that the agent should ask which tag you mean
(`RescaleSlope`? `WindowCenter`?) rather than silently guessing one.
