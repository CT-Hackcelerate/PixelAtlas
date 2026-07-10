# Sample prompts

3-4 example prompts per use case to type directly into Copilot Chat (Pixel
Atlas chat mode) for manual testing. These are plain natural language, not
slash commands — the agent should map them to the right tool calls itself;
if it doesn't, that's a bug to report, not a wording problem to work around.

Pair with [demo-script.md](demo-script.md) for the scripted end-to-end
walkthrough; this doc is for ad hoc/exploratory testing of one use case at a
time instead.

## 1. Generate (UC-01 / UC-02)

Expected tool sequence: `get_template_info` → `resolve_seed` → (confirmation)
→ `generate_dataset` → `validate_dataset` → (store confirmation) →
`store_to_pacs(confirm_store=True)`. See
[generate.prompt.md](../.github/prompts/generate.prompt.md) for the exact
contract.

**Plain happy path (template fallback)**
```
Generate 3 axial CT chest instances
```
Expect: no matching CHEST/axial CT data in the PACS yet, so the agent tells
you plainly and asks to confirm falling back to the bundled `ct-image`
template (CT Image IOD, generic — CHEST/axial comes from the requested
overrides, not a dedicated use-case template) before generating anything. After confirming: 3 instances
generated and validated, then a **separate** confirmation before storing
anything (even for a count this small) — only after that does it call
`store_to_pacs` and give you the job_id/study_uid summary.

**Large batch — confirmation threshold**
```
Generate 200 axial CT chest scans for load testing
```
Expect: the template-fallback confirmation, a separate explicit confirmation
because count > 50 (before generation starts), and then the store
confirmation from above (before anything reaches the PACS) — three distinct
confirmations, not one blended together.

**With tag overrides**
```
Generate 5 CT chest instances with PatientSex=F and PatientAge=062Y
```
Expect: the agent checks these tags against the template's `protected_tags`
(from `get_template_info`) and the IOD's known tag list before calling
`generate_dataset`. Both should be accepted — `PatientSex`/`PatientAge` are
plain IOD-valid tags, not on the (short) protected list.

**Override rejection (negative test)**
```
Generate 2 CT instances and set the SOPInstanceUID to 12345
```
Expect: `SOPInstanceUID` is one of `ct-image`'s `protected_tags` — it's a
generated identifier the server always regenerates itself, not something a
user should hand-set — so the agent should reject this before calling
`generate_dataset`, explaining why, not silently drop the override or crash.

## 2. Priors

New use case beyond the original solution design (added Phase 3): generating a
study that reads as an earlier scan of the *same* (synthetic) patient, for
before/after comparison workflows. Expected tool call:
`generate_dataset(..., prior_of_study_uid=<uid>, days_before=<n>)`.

You'll need a `study_uid` already in the PACS first — generate one with a
prompt from §1 and note its `study_uid` from the summary before trying these.

**Plain prior request**
```
Generate a prior CT for the same patient as study <study_uid>, 90 days earlier
```
Expect: the agent resolves this to `prior_of_study_uid=<study_uid>`,
`days_before=90`. The result shares `PatientID`/`PatientName` with the
reference study, has a `StudyDate` 90 days earlier, and its own independent
`StudyInstanceUID` — never an edit of the original.

**Vaguer phrasing (tests NL understanding, not just exact syntax)**
```
I need an older scan for comparison against <study_uid> — say 6 months back
```
Expect: the agent converts "6 months" to a `days_before` value (roughly 180)
itself; if it's unsure how you want that rounded, it's fine for it to ask
rather than guess silently.

**Missing days_before (negative test)**
```
Generate a prior study based on <study_uid>
```
Expect: the agent asks how far back, rather than picking an arbitrary
default — `days_before` has no sensible default, and generating one right on
top of the reference date wouldn't read as a genuine "prior."

**Multiple priors in sequence**
```
Generate two priors for <study_uid>: one 30 days earlier and one 180 days earlier
```
Expect: two separate `generate_dataset` calls, each with a distinct
`StudyDate`/`StudyInstanceUID`, both sharing the same `PatientID` as the
reference and each other.

## 3. Modify (UC-03)

Expected tool sequence: `list_pacs_studies` (if the study isn't named
directly) → `get_template_info` (for override validation) →
(same-study-vs-new-study confirmation) → `modify_dataset` →
`validate_dataset` → (store confirmation) →
`store_to_pacs(confirm_store=True)`. See
[modify.prompt.md](../.github/prompts/modify.prompt.md). You'll need a
`study_uid` already in the PACS — generate one via §1 first.

**Non-destructive modify (default)**
```
/modify study=<study_uid> PatientAge=045Y
```
Expect: the agent **explicitly asks** whether this should create a new
derived study or overwrite the original in place, even though
`regenerate_uids` defaults to `true` — that default should never be applied
silently. After you confirm "new study": a brand new derived study is
created (new `StudyInstanceUID`) and validated, then a **separate**
confirmation before anything is stored. The original study is untouched;
confirm this by checking the original study_uid still shows its old
`PatientAge` afterward.

**Same, phrased as natural language**
```
Change the patient sex to F on study <study_uid> but don't touch the original
```
Expect: same behavior as above — "don't touch the original" should be
enough for the agent to treat `regenerate_uids=true` as already decided
(no need to ask again), but it should still ask for store confirmation
separately before anything reaches the PACS.

**Destructive in-place overwrite (the important negative-then-positive test)**
```
Overwrite study <study_uid> in place — set PatientAge=050Y and don't create a new study
```
Expect **three things in sequence**:
- First, the agent should explicitly confirm with you that this is a
  destructive, irreversible overwrite of the original before doing anything.
- Only after you confirm, it calls `modify_dataset` with
  `regenerate_uids=false` and `confirm_destructive=true`. If you say "yes"
  too quickly and the agent calls it anyway without asking — that's the bug
  to report, not a successful test.
- Then a **separate** store confirmation before `store_to_pacs` runs — don't
  let the destructive-overwrite confirmation double as the store
  confirmation, they're two different questions.
- The result should include a caveat noting that whether the PACS actually
  overwrote the existing copy depends on the PACS's own configuration
  (Orthanc doesn't overwrite same-SOPInstanceUID instances by default) —
  the agent should relay that, not claim the overwrite definitely took
  visible effect.

**Unknown override tag (negative test)**
```
/modify study=<study_uid> Manufacturer=AcmeCorp SOPClassUID=1.2.3.4
```
Expect: `Manufacturer` should be accepted (a plain IOD-valid tag, not
protected), but `SOPClassUID` should be rejected before `modify_dataset` is
ever called — it's a structural identifier (which IOD this data even is),
not a user-facing override.

## 4. Validate (UC-04)

Standalone diagnostic command — expected tool call: `validate_dataset(path=...)`
or `validate_dataset(study_uid=...)`. Unlike `/generate`'s compact summary,
this should return the **full** report. See
[validate.prompt.md](../.github/prompts/validate.prompt.md).

**Validate a job's output folder**
```
/validate path=<output_path from a previous /generate>
```
Expect the full report: `passed`, `checked_instances`, `sampling_ratio`,
`iod_conformance` (with `files_with_errors`/`example_errors`), the
`dcmftest` summary, and `errors`/`warnings` lists.

**Validate a study already in the PACS**
```
/validate study=<study_uid>
```
Expect: the agent fetches every instance of that study into a temporary
folder first (this can take a few seconds longer than the path= form), then
runs the same checks. Report format should be identical to above.

**Natural language, no slash command**
```
Can you check whether the study I just generated actually conforms to the DICOM standard?
```
Expect: the agent infers the target study/path from conversation context
(the most recent `/generate` or `/modify` result) and calls
`validate_dataset` without you having to restate the UID — if it can't infer
the target, it should ask which study/path you mean, not silently pick one.

**Invalid target (negative test)**
```
/validate study=not-a-real-study-uid
```
Expect: a clear error message ("Failed to fetch study ... from the PACS: no
study found...") — not a crash, not a false "passed: true".

## 5. Status (UC-05)

Expected tool calls: `health_check()` (no job id) or `get_job_status(job_id)`.
See [status.prompt.md](../.github/prompts/status.prompt.md).

**Environment health check**
```
/status
```
Expect a status table: `mcp_server: ok`, `orthanc_reachable: true` (with
Orthanc's version and URL), `dcmtk_binaries_on_path` (expect `dcmodify`/
`storescu`/`findscu`/`dcmftest` `true` if DCMTK's `bin` folder is on PATH,
`dciodvfy` always `false` — that's expected, see the chatmode's validation
caveat), and `template_count`.

**Check a specific job**
```
/status job=<job_id from a previous /generate or /modify>
```
Expect: the job's `state` (`generated`/`modified`/`completed`/`failed`),
`progress_pct`, and `message`.

**Natural language**
```
Is the Pixel Atlas server working right now?
```
Expect: same as above — the agent should map this to `health_check()` even
without the slash command.

**Nonexistent job (negative test)**
```
/status job=does-not-exist
```
Expect: a clear "no job found with that id" message, not an empty/blank
response or a crash.

## 6. List templates (UC-06)

Expected tool call: `list_templates(modality?, body_part?, orientation?)`.
See [list-templates.prompt.md](../.github/prompts/list-templates.prompt.md).

**List everything**
```
/list-templates
```
Expect a table with the four implemented IOD templates: `ct-image` (CT, CT
Image IOD), `mr-image` (MR, MR Image IOD), `us-image` (US, Ultrasound Image
IOD), `mg-image` (MG, Digital Mammography X-Ray Image IOD) — each with blank
body_part/orientation (generic, IOD-level) and `has_seed_data: true`.

**Filtered by modality**
```
/list-templates modality=MR
```
Expect exactly one result: `mr-image`.

**Natural language discovery**
```
What kinds of test data can this agent generate for me?
```
Expect: the agent calls `list_templates()` and summarizes — should mention
CT, MR, US, and MG are available as generic IOD templates, and that
use-case-specific protocols (e.g. a dedicated chest-CT or screening-mammo
template) aren't built yet — a known scope limit, not implied broader
coverage.

**Tag-level detail for a specific template**
```
What tags can I override when generating a CT study?
```
Expect: the agent calls `get_template_info("ct-image")` and explains it the
other way around from what the tool literally returns — `protected_tags`
(`ImagePositionPatient`, `InstanceNumber`, `MediaStorageSOPClassUID`,
`MediaStorageSOPInstanceUID`, `SOPClassUID`, `SOPInstanceUID`,
`SeriesInstanceUID`, `SliceLocation`, `StudyInstanceUID`) are the tags that
can't be set; anything else valid for the CT Image IOD (see
`get_iod_requirements`) can be. Not the full `tag_rules` dump, and not a
literal recitation of `protected_tags` without that framing — the useful
answer to "what can I override" is "everything except this short list."

## 7. Generic PACS feature lookup

New use case (added Phase 3): "does the PACS already have data with property
X" for an arbitrary X, not hardcoded per-feature. Expected tool call:
`check_pacs_feature(tag, value?, modality?, date_range?)`. **By design there
is no natural-language-to-tag mapping inside the tool** — the agent must
resolve your phrase to the correct DICOM keyword itself before calling it.
See the chatmode's instructions on this.

Reachable both as natural language and as the explicit `/check-feature`
slash command (`.github/prompts/check-feature.prompt.md`) — the slash
command restricts the model to just the `check_pacs_feature` tool, which is
the recommended way to invoke this if the freeform phrasing ever sends the
model off calling unrelated tools (`get_job_status`, etc.) instead of the
one it actually needs; that happened in practice before the dedicated prompt
file existed.

**Sequence-tag presence**
```
Do we have any CT study with a Modality LUT?
```
or, more reliably:
```
/check-feature tag=ModalityLUTSequence modality=CT
```
Expect: the agent recognizes "Modality LUT" as `ModalityLUTSequence` (tag
`0028,3000`) and calls `check_pacs_feature(tag="ModalityLUTSequence", modality="CT")`
directly — no other tool calls first. Likely 0 matches unless you've
generated data with one.

**Value-filtered lookup**
```
Is there a study where RescaleSlope is 1?
```
Expect: `check_pacs_feature(tag="RescaleSlope", value="1")`, returning the
matching studies (and correctly excluding any study that lacks
`RescaleSlope` entirely, e.g. a real de-identified sample without CT
rescale tags).

**Orientation, phrased as the original ask that motivated this feature**
```
Do we already have an axial study in the PACS?
```
Expect: the agent maps "axial" to `ImageType` or a similar orientation-bearing
tag itself and calls `check_pacs_feature` accordingly — and should be upfront
if its answer is based on a specific tag's value rather than true geometric
orientation (`ImageOrientationPatient`), since "axial" can be represented
more than one way in DICOM.

**Ambiguous tag name (tests whether the agent asks instead of guessing)**
```
Does any study have a weird pixel value scaling?
```
Expect: this is vague enough that the agent should either ask which specific
tag you mean (`RescaleSlope`? `RescaleIntercept`? `WindowCenter`?) or state
its assumption explicitly before calling `check_pacs_feature` — silently
guessing one tag and reporting results as if that's definitively what you
asked about would be the wrong behavior to see here.
