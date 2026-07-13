# Demo prompts

Descriptive, DICOM-literate prompts for live demos. Each one is written the
way a PACS/QA engineer would phrase a real request — modality, anatomy, and
the specific tags/attributes that matter — rather than a terse tool-call
shorthand. See [sample-prompts.md](sample-prompts.md) for the plainer
regression-style prompts and [CLAUDE.md](../CLAUDE.md) for the tool contract.

Each prompt below is followed by:
- **Command** — the slash command that maps to this prompt, if one exists
  (`/generate`, `/modify`, `/validate`, `/status`, `/list-recipes`,
  `/check-feature`). Some flows (priors, PR/KO authoring, the advanced
  extract-and-edit flow) have **no dedicated slash command** — there's no
  `.claude/commands/*.md` for them — so the plain-English prompt is the only
  way in; the agent calls the underlying MCP tool(s) directly from the
  general Pixel Atlas system prompt (`CLAUDE.md`) instead of a scoped
  command file.
- **Expect** — what the agent should actually call.
- **Note** — anything about the tool's current behavior worth knowing before
  you run it live (a caveat, a required follow-up question, or a risk of
  failure).

---

## 1. CT study with multiple series (axial + other orientation)

```
Generate a CT chest study with two series: series 1 should be 40 axial
slices at 5mm spacing, series 2 should be 20 coronal reformats of the same
anatomy. Keep them in the same study, same patient.
```

**Command:** `/generate`, run twice (once per series).

**Expect:** first `find_recipe`/author a CT axial chest spec
(`request.instanceCount=40`) → `validate_spec` → `materialize_dataset` →
confirm → `store_to_pacs` → capture `study_uid`. Then a second spec
(`request.instanceCount=20`, `orientation` coronal,
`request.attachStudyUID=<study_uid from series 1>`) → `validate_spec` →
`materialize_dataset` → confirm → `store_to_pacs`, reusing the same patient
identity per the multi-series chaining rule (§14 in solution-design.md).

**Note:** this is explicitly multi-series ("two series", two orientations),
so the agent should recognize the cardinality up front and not ask — good
prompt to show the "N series" disambiguation rule working correctly. Each
series is its own confirm/store gate — expect two, not one.

---

## 2. Ultrasound study with multiple multi-frame (cine) instances

```
Generate an ultrasound study with 3 separate cine-loop series in the same
study — each series is one multi-frame instance of 50 frames, same patient.
```

**Command:** `/generate`, run three times (once per series).

**Expect:** three chained spec authorings for `modality="US"`,
`request.instanceCount=50` (frames), `enhanced` → `validate_spec` →
`materialize_dataset` (first with no `attachStudyUID`, the next two with it
set to the first series' `study_uid`), each confirmed and stored
individually — three series, one instance (one `.dcm`) per series, since
multi-frame is inherently one-instance-per-series.

**Note:** phrase it as "3 series" explicitly, like above — this is exactly
the case CLAUDE.md flags as ambiguous ("N images" vs "N series" for
multi-frame). If you instead say "an ultrasound study with 3 cine
instances," expect the agent to ask you to confirm series-vs-frames before
generating anything, rather than assume.

---

## 3. Ultrasound cine series with varying frame-rate tags

```
Generate 3 US cine-loop instances (separate series, same study) at 15, 30,
and 60 fps respectively — set CineRate accordingly on each, and also stamp
RecommendedFrameRate to match. Each loop is 30 frames.
```

**Command:** `/generate`, run three times (once per series).

**Expect:** three chained specs for `modality="US"`,
`request.instanceCount=30` (frames), each with `attributes` setting
`CineRate=<15|30|60>` and the matching `FrameTime` (1000/rate) the agent
computes itself, plus `RecommendedFrameRate=<rate>` — all three are plain
`attributes` the agent authors directly, nothing is auto-derived from a
single "cine_rate" parameter anymore.

**Note:** `RecommendedFrameRate` is a plain overridable tag (not part of the
protected pixel/UID lists) so it should pass straight through — but it isn't
cross-validated against `CineRate` for consistency, so nothing will stop you
from setting them to different values if you want to demo a mismatch. If you
also want `CineVector` (frame-display direction, SS×3), add it the same way,
e.g. `overrides={"CineVector": [0,0,1]}` — treat this one as a bonus/lower-
confidence ask since it's not part of the documented cine flow and hasn't
been demo-tested.

---

## 4. Priors at specified intervals

```
Study <study_uid> is today's CT. Generate three priors of it for the same
patient at 30, 90, and 180 days before the study date — each its own
independent prior study (not chained off each other).
```

**Command:** none — there's no dedicated `/prior` slash command; ask in
plain English and the agent calls `generate_prior_study` directly.

**Expect:** `generate_prior_study(study_uid, days_before=30)`, then again
with `days_before=90` and `days_before=180` — confirm + `store_to_pacs`
after each. **This bypasses the spec pipeline entirely** (like
`modify_dataset`): no `extract_spec`/`validate_spec`/`materialize_dataset`
involved. `generate_prior_study` clones every series/instance of the source
study via `study_clone.py`, shifts `StudyDate` back by `days_before`, and
always produces a new, independent `StudyInstanceUID` that still shares
`PatientID`/`PatientName` with the reference study.

**Note:** "at specified intervals" isn't a single tool call — there's no
batch/multi-prior parameter, so expect three distinct
call+confirm+store round trips, not one. Say so up front if you want the
demo to look like one ask with three results, so the audience isn't
surprised by three separate confirmations.

---

## 5. CT with explicit rescale slope/intercept

```
Generate a 10-slice CT abdomen series with RescaleSlope=2.5, RescaleIntercept
=-1024, and set WindowCenter/WindowWidth to 40/400 so a viewer applying the
modality LUT shows a sane soft-tissue window.
```

**Command:** `/generate`.

**Expect:** author/reuse a CT abdomen spec (`request.instanceCount=10`) with
`attributes` set to `{"RescaleSlope": "2.5", "RescaleIntercept": "-1024",
"WindowCenter": "40", "WindowWidth": "400"}`. These four tags aren't part of
the protected Image Pixel module, so `validate_spec` accepts them as plain
`attributes`.

**Note:** solid, low-risk prompt — the materializer normally derives
RescaleSlope/Intercept/Window* itself for viewer-safety, and this just sets
them explicitly in `attributes` instead, which is exactly what per-request
tag values are for.

---

## 6. CT with Japanese characters in Patient Name

```
Generate a CT head series where PatientName is a Japanese name in the
standard three-component PN format — alphabetic, ideographic, and phonetic
groups (e.g. "Yamada^Tarou=山田^太郎=やまだ^たろう"), and set
SpecificCharacterSet so the ideographic/phonetic groups decode correctly.
```

**Command:** `/generate`.

**Expect:** author/reuse a CT head spec with `attributes` set to
`{"PatientName": "Yamada^Tarou=山田^太郎=やまだ^たろう", "SpecificCharacterSet":
["ISO 2022 IR 6", "ISO 2022 IR 87", "ISO 2022 IR 13"]}`.

**Note — lower confidence.** I checked the codebase: there's no explicit
`SpecificCharacterSet`/PN-encoding handling anywhere in the MCP server today
— tag values are applied generically via `pydicom` `setattr`, so plain-ASCII
PN values work fine, but nothing in the pipeline currently sets
`SpecificCharacterSet` for you. That means the prompt is only reliable if you
(or the agent) supply `SpecificCharacterSet` explicitly alongside
`PatientName`, as above; if you omit it, expect either a validation error or
mojibake rather than a clean Japanese name. Worth testing once ahead of the
actual demo rather than trusting it cold.

---

## 7. CT study with a PR referencing one instance — line + text annotation

```
Generate a 5-slice CT chest axial series and store it. Then create a
Presentation State (PR) that references the first instance of that series,
draws a straight-line graphic annotation across the image, and adds a text
annotation reading "Hello World" near the top-left.
```

**Command:** `/generate` for the CT series; the PR itself has no dedicated
slash command — it's authored manually (`references` block + graphic
sequences), driven by the plain-English ask.

**Expect:**
1. Author/reuse a CT chest axial spec (`request.instanceCount=5`) →
   `validate_spec` → `materialize_dataset` → confirm → `store_to_pacs` →
   capture `study_uid`, `series_uid`.
2. `list_series_instances(study_uid, series_uid)` → pick instance 1's
   `sopInstanceUID`.
3. Author (not extract) a PR spec with a `references` block naming that
   instance, plus `attributes.GraphicAnnotationSequence` containing one item
   with `GraphicType="POLYLINE"` + `GraphicData=[x1,y1,x2,y2]` (the line),
   and a `TextObjectSequence` item with `BoundingBoxTopLeftHandCorner`/
   `BoundingBoxBottomRightHandCorner` + `UnformattedTextValue="Hello World"`.
4. `validate_spec` → `materialize_dataset` → confirm → `store_to_pacs`.

**Note:** confirmed feasible by reading `materializer.py` —
`GraphicAnnotationSequence` (with nested `ReferencedImageSequence` and
`GraphicsData`) and arbitrary nested sequences like `TextObjectSequence` are
generically supported via the spec's recursive list-of-dict → pydicom
Sequence coercion. This is a good "look what the advanced flow can do" demo
moment — worth showing the PR rendered in a viewer if you have one handy.

---

## 8. CT study with VOI LUT — window/level and a full LUT sequence

```
Generate a CT abdomen series, 8 slices, with an explicit VOI LUT: set
WindowCenter=50/WindowWidth=350 with WindowCenterWidthExplanation="SOFT
TISSUE", AND add a full VOILUTSequence entry with LUTDescriptor=[4096,
-1024, 16] (entries, first stored value, bits/entry), a monotonically
increasing LUTData array, and LUTExplanation="Soft tissue LUT".
```

**Command:** `/generate`.

**Expect:** author/reuse a CT abdomen spec (`request.instanceCount=8`) with
`attributes` set to `{"WindowCenter": "50", "WindowWidth": "350",
"WindowCenterWidthExplanation": "SOFT TISSUE", "VOILUTSequence": [{
"LUTDescriptor": [4096, -1024, 16], "LUTData": [...], "LUTExplanation":
"Soft tissue LUT"}]}`.

**Note:** the simple Window Center/Width half of this is well-trodden (same
mechanism as #5). The full `VOILUTSequence` (an actual lookup table, not
just a linear window) is a nested-sequence override — structurally
supported by the same recursive coercion used for PR graphics (#7), but it
hasn't specifically been demo-tested with a real LUTData array this large.
If the agent has to author `LUTData` by hand, ask it to keep the array short
(e.g. 16–32 entries) rather than a clinically-sized one, since LUT arrays
are numeric payload the AI would otherwise have to enumerate token-by-token.

---

## 9. Derive a CT study from an existing one, varying ImagePositionPatient

Two variants — pick one, or run both to show the difference:

**9a — shift the whole series in Z (simple slice-spacing change):**
```
Take study <study_uid> (a multi-slice axial CT) and regenerate it as a new
study with the same instance count, but change the slice spacing so
ImagePositionPatient's Z component steps by 2mm instead of whatever the
original used — SliceLocation should track the same steps.
```

**9b — shift the whole stack's origin (translate X/Y, keep spacing):**
```
Take study <study_uid> and regenerate it as a new study with every
instance's ImagePositionPatient shifted by (+20, +20, 0) mm relative to the
original, keeping the same slice-to-slice spacing.
```

**Command:** none — this needs the advanced manual flow (rewriting
`perInstance` rules), which no slash command covers; `/modify` only takes
flat `overrides`/`per_instance` value maps, not rule edits like this.

**Expect (both):** `extract_spec(study_uid)` → AI edits the `perInstance`
rule for `ImagePositionPatient`/`SliceLocation` (rule kinds available:
`linspace`, `derive_from_slice`, `index+1`, `const`) → `validate_spec` →
`materialize_dataset(regenerate_uids=true)` → confirm → `store_to_pacs`.
9a is a `linspace` step-size edit; 9b needs a per-axis offset added on top of
the existing derived position (a small custom rule/const-offset combo).

**Note:** solid for 9a — `linspace`/`derive_from_slice` are exactly what the
per-instance rule engine already supports. 9b (arbitrary X/Y translation) is
a bit more bespoke since the built-in `derive_from_slice` rule only varies
Z from `SliceLocation` — the agent will need to author a slightly more
custom per-instance expression; still within what the spec format allows,
just less of a beaten path than 9a.

---

## 10. Modify — tweak a few tags on an existing MR study, non-destructively

```
Take study <study_uid> (an existing MR study) and create a new derived study
with MagneticFieldStrength=3.0, RepetitionTime=2000, EchoTime=30, and
Manufacturer="AcmeMR" — everything else should stay as in the source study.
```

**Command:** `/modify`.

**Expect:** locate the study (`list_pacs_studies` if not named directly) →
check the four tags are valid for the study's actual IOD
(`get_iod_requirements`/`describe_attributes`) → `modify_dataset(study_uid,
overrides={"MagneticFieldStrength": "3.0", "RepetitionTime": "2000",
"EchoTime": "30", "Manufacturer": "AcmeMR"}, regenerate_uids=true)` →
`validate_dataset(path=output_path)` → confirm → `store_to_pacs`.
**`modify_dataset` is a self-contained tool — it never calls
`extract_spec`/`validate_spec`/`materialize_dataset`.** It fetches every
instance of every series directly via `study_clone.py` and applies the
overrides in one pass.

**Note:** ask explicitly for a **new derived study**, as above, so the
agent uses `regenerate_uids=true` rather than asking you to choose (or it
will ask, per the golden rules — that's expected too). Straightforward: all
four tags are plain overridable attributes, no sequences or per-instance
rules involved. Good "boring but reliable" prompt to run first in a demo
before the fancier PR/VOI LUT ones.

---

## 11. Modify — per-instance renumbering across an existing series

```
Study <study_uid> has one CT series. Rename its SeriesDescription to
"Re-reviewed — QA pass 2" and renumber AcquisitionNumber sequentially
starting at 100 (100, 101, 102, ...) across every instance. Keep it as a
new derived study.
```

**Command:** `/modify`.

**Expect:** `modify_dataset(study_uid, overrides={"SeriesDescription":
"Re-reviewed — QA pass 2"}, per_instance={"AcquisitionNumber": {"rule":
"index+1", "start": 100}}, regenerate_uids=true)` → `validate_dataset` →
confirm → `store_to_pacs`. `SeriesDescription` is uniform (`overrides`);
`AcquisitionNumber` varies per instance (`per_instance`) — same
uniform-vs-varying split the spec-authoring flow uses for `attributes` vs
`perInstance`, just under `modify_dataset`'s own parameter names.

**Note:** good demo of `modify_dataset`'s `per_instance` parameter, which is
easy to overlook next to the more commonly-shown flat `overrides`. Per-
instance rules here are re-applied within each original series in
instance-number order — a multi-series source study would renumber each
series independently starting at 100, not continue the count across series.

---

## 12. Modify — attempt to change a protected tag, to show the refusal path

```
Take study <study_uid> and change its Rows to 1024 and its SOPClassUID to
1.2.840.10008.5.1.4.1.1.4 (MR Image Storage) — I want to see what happens
when you ask for something modify isn't allowed to do.
```

**Command:** `/modify`.

**Expect:** the agent should recognize (or `modify_dataset` should reject)
`Rows` (Image Pixel module — pixel data would no longer match) and
`SOPClassUID` (a structural identifier, not a user override) as protected
tags and refuse before or via the tool call, reporting exactly which tags
are disallowed and why — not silently drop them and modify only the
allowed ones without saying so.

**Note:** good companion to #10/#11 — shows the same guardrail
`validate_spec` enforces for fresh generation (pixel-module/UID tags
rejected in `attributes`) also holds for the modify path, even though
`modify_dataset` never touches the spec pipeline. If the agent instead
silently ignores the two bad tags and reports success, that's a bug worth
flagging, not expected behavior.

---

## Bonus prompts (impactful, not in the original list)

**A. Full workflow in one breath — generate → validate → check-feature:**

**Command:** `/generate` → `/validate` → `/check-feature`, chained in one ask.

```
Generate a 20-slice CT chest series, validate it, store it to PACS, then
tell me whether ModalityLUTSequence is present anywhere in it.
```
Nicely demonstrates the generate → validate → store → check_pacs_feature
chain end to end with a single ask, and shows off `check_pacs_feature`
resolving a plain-English question ("Modality LUT") to the right keyword.

**B. Key Object Selection tying two series together:**

**Command:** `/generate`, run twice for the two series; the KO itself has no
dedicated slash command (same as PR in #7) — authored manually.

```
Generate two CT series in one study (axial, 10 slices each — call them
series A and series B). Then create a Key Object Selection document titled
"Of Interest" that references the first instance of series A and the last
instance of series B as the key images.
```
Good companion demo to #7 — shows the KO branch of the reference-object flow
(vs. PR), including cross-series references within one study (§14 of
solution-design.md).

**C. Destructive in-place overwrite, shown deliberately:**

**Command:** `/modify`.

```
Overwrite study <study_uid> in place: change PatientAge to 077Y. Do not
create a new study — I want to see the destructive-overwrite confirmation
flow.
```
Useful for showing the three-gate destructive path explicitly
(destructive-intent confirmation → `modify_dataset(regenerate_uids=false,
confirm_destructive=true)` → separate store confirmation) rather than
letting an audience assume `/modify` is always non-destructive.

**D. A deliberately-ambiguous prompt, to show the agent asking back:**

**Command:** none — plain English only, same as #4.

```
Generate a prior study based on <study_uid>.
```
No `daysBefore` given — the right behavior is the agent asking how far back
rather than guessing. Good for demonstrating the tool refuses to silently
invent a default where none is sensible (already called out in
sample-prompts.md §2).

**E. An intentionally out-of-scope ask, to show the refusal path:**

**Command:** `/generate` (the request maps to it, but the agent should
refuse before calling any tool that would misrepresent the result).

```
Generate an RTSTRUCT for study <study_uid> outlining the liver.
```
RTSTRUCT is explicitly out of family (solution-design.md §10) — the agent
should refuse by name and point at the roadmap rather than trying to
approximate it with a supported IOD.
