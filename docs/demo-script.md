# Demo script

A walkthrough of everything implemented through Day 3, in the order a live
demo would run it. Each step names the slash command (or natural-language
prompt) and what to expect. Run `scripts/setup.ps1` first if the environment
isn't already up.

Referenced by [execution-plan-3day.md](execution-plan-3day.md) Day 3's
"dry-run the full demo script twice" task — dry-run status is noted per step
below; script-level (tool functions called directly, bypassing Copilot Chat)
for both runs, interactive Copilot Chat run-through is still outstanding for
every command (tracked in execution-plan-3day.md, not just this doc).

## 1. Environment check

```
/status
```
Expect `mcp_server: ok`, `orthanc_reachable: true`, `template_count: 4`,
`dcmtk_binaries_on_path` mostly `false` unless DCMTK's `bin` folder is on
PATH for this session (soft dependency — see `mcp-server/README.md`).

```
/list-templates
```
Expect four rows, one generic IOD template per modality: `ct-image` (CT),
`mr-image` (MR), `us-image` (US), `mg-image` (MG) — each `has_seed_data: true`.

## 2. Generate — template-fallback path

```
Generate 3 axial CT chest instances
```
Since Orthanc has no matching CHEST/axial CT data yet (or only the
pre-existing "KUNAS" study, which doesn't match), expect:
- `resolve_seed` returns `source_type=template`
- explicit confirmation prompt before using the bundled seed
- `generate_dataset` -> `validate_dataset` (passed, `iod_conformance`
  populated)
- a **separate** confirmation prompt before storing anything — summarizing
  study_uid, instance count, and the validation result — regardless of how
  small the count is; only after that does `store_to_pacs(confirm_store=True)`
  actually run
- summary with `job_id`, `study_uid`, seed source, validation result

## 3. Generate — large batch confirmation

```
Generate 200 axial CT chest instances
```
Same as above, plus an explicit >50-instance confirmation prompt before
generation starts.

## 4. Priors

```
Generate a prior CT for the same patient as <study_uid from step 2>, 90 days earlier
```
Expect the agent to map this to
`generate_dataset(..., prior_of_study_uid=<uid>, days_before=90)`. Result
shares `PatientID`/`PatientName` with the reference study, has a `StudyDate`
90 days earlier, and its own independent `StudyInstanceUID`.

## 5. Modify — non-destructive (default)

```
/modify study=<study_uid from step 2> PatientAge=045Y
```
Expect the agent to **explicitly ask** whether this should create a new
derived study or overwrite the original in place — even though
`regenerate_uids` defaults to `true`, that choice should never be applied
silently. After you confirm "new study": `modify_dataset` runs, then
`validate_dataset`, then a **separate** confirmation before
`store_to_pacs(confirm_store=True)` actually stores anything. The original
study is untouched throughout.

## 6. Modify — destructive, gated

```
/modify study=<study_uid from step 2> PatientAge=050Y regenerate_uids=false
```
Expect the agent to restate that this overwrites the original in place and
ask for explicit confirmation before calling `modify_dataset` with
`confirm_destructive=true`. After that, expect the *same* store confirmation
as step 5 before `store_to_pacs` runs — the destructive-overwrite
confirmation and the store confirmation are two separate questions, not one.
The result includes a `note` about the PACS's own overwrite-policy caveat
(Orthanc defaults to *not* overwriting same-SOPInstanceUID instances unless
`OverwriteInstances` is configured — observed directly during Day 3 testing,
not just a theoretical caveat).

## 7. Validate — standalone

```
/validate study=<study_uid from step 2>
```
Expect the full report (not the compact `/generate` summary): `passed`,
`checked_instances`, `sampling_ratio`, `iod_conformance`, `dcmftest`,
`errors`/`warnings`.

## 8. Generic PACS feature lookup

```
Do we have any CT study with a Modality LUT?
Is there a study where RescaleSlope is 1?
```
Expect the agent to resolve these itself to
`check_pacs_feature(tag="ModalityLUTSequence", modality="CT")` and
`check_pacs_feature(tag="RescaleSlope", value="1")` respectively, with no
tag-name mapping logic in the tool itself.

## 9. Known gaps to state plainly if asked

- `dciodvfy` specifically is not run (dicom-validator covers the same IOD-conformance
  ground, but isn't literally `dciodvfy`).
- No UC-08 bulk/multi-study batch chat logic (`Generate 5 CT + 3 MR studies` in
  one request) — `generate_dataset` supports it per-study, the batching UX doesn't exist.
- Only generic IOD-level templates (`ct-image`, `mr-image`, `us-image`,
  `mg-image`) — no dedicated use-case/protocol templates yet (e.g. chest-CT,
  screening-mammo), and no CR/XA/other-modality IODs.
- No idempotent retry-on-partial-failure for `store_to_pacs`.
- None of this has been run through Copilot Chat interactively yet — every
  verification so far calls the MCP tool functions directly.

## Dry-run log

| Run | Date | Method | Result |
|---|---|---|---|
| 1 | 2026-07-07 | Direct tool calls (steps 2, 5, 6, 7 — generate/modify/validate) | All passed; step 6 confirmed Orthanc's overwrite-policy caveat is real, not hypothetical (see `execution-plan-3day.md` §3) |
| 2 | 2026-07-07 | Direct tool calls (steps 2, 4, 8 — generate, priors, feature lookup) | All passed; priors confirmed shared PatientID + correct StudyDate offset in Orthanc |
