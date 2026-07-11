# Comprehensive Build Plan — AI-Driven Pixel Atlas

> The complete scope of work, organized by **what needs building**, not by phase.
> Phasing/sequencing is decided separately (a suggested ordering lives in
> [execution-plan-ai-driven.md](execution-plan-ai-driven.md)). Rationale and detail
> live in the design docs:
> [simple overview](ai-driven-simple-overview.md) ·
> [solution design](solution-design.md) ·
> [architecture](architecture.md) ·
> [what's changing](design-change-ai-driven.md).
>
> Written in plain language on purpose. Every work item is a checkbox so it can be
> assigned to a phase later.

---

## 1. Purpose & scope

**Goal:** let a person ask, in plain English, for synthetic DICOM test scans of
*any standard image type*, and have the assistant build valid files and load them
into the test PACS — using the AI's DICOM knowledge (grounded on the official
standard) instead of hand-made templates.

**In scope (the scan types we support):**

- All standard image types, single-frame *and* multi-frame (CT, MR, US, CR, DX, XA,
  RF, MG, NM, PT, OCT, and their Enhanced/multi-frame variants).
- Presentation States (PR) and Key Object Selection (KO) — "markup" objects that
  point at existing scans.

**Out of scope (the assistant says "not supported"):**

- Structured Reports (SR), RT objects (RTSTRUCT/RTPLAN/RTDOSE), Segmentation (SEG),
  Encapsulated documents (PDF/CDA/STL), Waveforms, and other non-image/highly
  structured types.
- Compressed pixel data (we write uncompressed only).
- Clinically realistic pixels (we make noise/gradient/simple shapes).
- PHI scrubbing (deferred — this is a test tool on test data; see §13).

---

## 2. Plain glossary

| Term | Plain meaning |
|---|---|
| **Knowledge Base (KB)** | The DICOM rulebook in lookup form — for any scan type, which tags are required, their format (VR), and rules. Built once from the standard. |
| **Order slip / Generation Spec** | The short JSON file the AI writes describing what to build. Fed to the Materializer. |
| **Materializer** | Plain code that turns one order slip into many `.dcm` files. |
| **Grounding** | Checking the AI's order slip against the rulebook before building. |
| **Probe** | Building and fully checking **one** file before making the rest. |
| **Recipe** | A saved, working order slip, reused for the same kind of request. |
| **spec_id** | A short ticket number for a stored order slip, so it isn't re-sent between steps (saves tokens). |

---

## 3. End-to-end flow (what happens on one request)

1. Person asks (e.g. "make 100 axial CT scans").
2. Assistant checks the PACS for a similar existing study (cheap, description-based).
3. **If found:** copy that study's structure into an order slip (`extract_spec`).
   **If not found:** assistant writes an order slip from the rulebook
   (`get_iod_requirements` → author).
4. Safety check the order slip (`validate_spec`) → get a ticket number (`spec_id`).
   Fix and retry if needed (bounded).
5. Confirm with the person if it's a big batch.
6. Build **one** file and fully validate it (probe). Fix and retry if needed.
7. Build the rest (`materialize_dataset`), validate the set (`validate_dataset`).
8. Store to PACS (`store_to_pacs`), report back (IDs, counts, link).
9. Save the working order slip as a recipe for next time.

---

## 4. Component inventory (everything we build, change, or reuse)

### 4.1 New components

| Component | What it does | Key tasks |
|---|---|---|
| **Knowledge Base** (`iod_lookup.py`, expanded) | Rulebook lookups for any scan type | see §5 |
| **Spec Validator** (`spec_validator.py`) | Grounds + safety-checks the order slip | see §7 |
| **Spec Store** (`spec_store.py`) | Holds order slips by `spec_id`, applies repair diffs | see §8 |
| **Materializer** (`materializer.py`) | Order slip → `.dcm` files | see §9 |
| **Spec Extractor** (`spec_extractor.py`) | Existing PACS study → order slip | see §10 |
| **Recipe Store** (`recipe_store.py`) | Save/reuse working order slips | see §11 |

### 4.2 Changed components

| Component | Change |
|---|---|
| `iod_lookup.py` | Grows from per-template file reader into the full KB (all scan types). |
| `seed_resolver.py` | `resolve_seed` returns just two outcomes: "found in PACS" or "build from rulebook." |
| `modify.py` | Reworked to: extract → AI edits → materialize. Keeps the destructive-edit guard. |
| `server.py` | Registers the new tools; drops the old template tools at cleanup. |
| `audit_log.py` | Records the full order slip + where the knowledge came from + rulebook edition (written to disk only, costs no tokens). |
| `scripts/generate_iod_spec.py` | Repurposed to build the KB, not per-template files. |

### 4.3 Reused unchanged

`orthanc_client.py`, `pacs_store.py`, `uid_strategy.py`, `validator.py`,
`job_registry.py`, `feature_lookup.py`, `config.py`.

### 4.4 Retired at cleanup

`generator.py` (folded into Materializer), `templates.py`, `scripts/generate_seed.py`,
the whole `templates/` folder, and the old `list_templates`/`get_template_info`/
`generate_dataset` tools.

---

## 5. Knowledge Base (the reusable rulebook)

**What it is:** one lookup source, built from `dicom-validator`'s standard data plus
the pydicom dictionary, covering every standard scan type. Loaded once per run and
kept warm.

### 5.0 Feasibility spike — DONE ✅ (findings)

Ran against `dicom-validator` 0.8.2, DICOM edition **2026c** (pin these).

- **Coverage: 16/16 target scan types present** — every single-frame image, every
  multi-frame image, GSPS (PR), and Key Object (KO). No coverage gap.
- **Data shape** — `EditionReader.load_dicom_info(edition)` returns a `DicomInfo`
  with three dicts:
  - `.iods` (171 entries) keyed by **SOP Class UID** → `{title, modules, group_macros}`.
  - `.modules` (673 entries) keyed by **ref** (e.g. `C.8.2.1`) → `{ "(GGGG,EEEE)":
    {name, type, [cond], [enums], [items]} }`. **Type (1/1C/2/2C/3) lives here.**
  - `.dictionary` (5267 entries) keyed by `(GGGG,EEEE)` → `{name, vr, vm, prop}`.
    So **VR/VM comes from here (or pydicom `datadict`)**, joined to the module's type.
- **Bonuses discovered (use them):**
  - Enumerated values are in the data (`enums`), so `validate_spec` can check
    allowed CS values, not just VR.
  - Conditions for 1C/2C tags are semi-structured (`cond`), not always free text.
  - **Nested structure is fully walkable:** modules/macros expose `include` refs and
    sequence `items:{include:[{ref}]}`. Multi-frame IODs carry `group_macros` (29 for
    Enhanced CT) plus the `Shared`/`Per-Frame Functional Groups Sequence` (SQ) with
    macro includes; PR exposes `Presentation State Relationship`; KO exposes
    `Current Requested Procedure Evidence Sequence` + `SR Document Content`.
    → **We can auto-inject the mandatory nested-sequence skeleton from the KB** rather
    than trusting the AI for deep nesting — this de-risks decision #3 for MF/PR/KO.
- **Sizing:** CT Image mandatory-module tags ≈ small (tens), confirming an order slip
  is O(1) and cheap.

**Conclusion: the KB approach is validated; proceed. No rethink needed.**

**Remaining KB tasks:**

- [x] Feasibility spike (above).
- [x] The KB is **committed in-repo** as plain JSON at `mcp-server/kb/2026c/`
      (`dict_info.json`/`iod_info.json`/`module_info.json`), pinned to edition
      2026c — no network fetch, no ~40s parse, reproducible across every
      environment. `iod_lookup.get_dicom_info()` loads it directly (a local
      `DicomInfo` stand-in, duck-typed for `dicom_validator`'s
      `DicomFileValidator`). Rebuild by re-copying dicom-validator's
      `~/.dicom-validator/<edition>/json/` output if the pinned edition changes.
- [x] Build the KB reader in `iod_lookup.py`:
  - [x] `requirements(sop_class)` → modules (mandatory/conditional/optional) + tags.
  - [x] `describe(tag_or_keyword)` → keyword, VR, VM.
  - [x] `is_multiframe(sop_class)` and `is_reference_object(sop_class)` (PR/KO).
  - [x] `PIXEL_MODULE_KEYWORDS` → the set of tags the Materializer owns (so the
        validator can reject them in the order slip).
  - [x] `macro_skeleton(ref, context)` / `mandatory_group_macros(sop_class)` —
        generic functional-group/macro nested-sequence builder straight from
        `group_macros` + module `include`/`items`, with a small structured
        condition evaluator (`_cond_holds`) for Type-1C/2C tags. Replaces what
        was a one-off `_add_ct_functional_groups` Python function in
        materializer.py with something that works for any modality (CT/MR/PT/
        future) with zero per-modality code — see §9.
- [x] Build the **modality → default scan class** table (`_CLASSIC`/`_ENHANCED`
      in iod_lookup.py). Note: `_ENHANCED` currently only covers CT/MR/US —
      PT's Enhanced PET Image Storage isn't wired up yet (falls back to classic
      PT), a known gap, not yet closed.
- [x] Build the **supported/unsupported** list (`is_supported`) so the assistant
      can say "no" cleanly.
- [x] Wire tools `get_iod_requirements` and `describe_attributes` (see §12).
- [ ] Small deterministic tests: correct tag lists for a few scan types.

---

## 6. The order slip (Generation Spec) — full definition

One JSON file. Body uses the standard DICOM JSON Model; the envelope adds the
build instructions. Full field list:

- [ ] `pixelAtlasSpec` — format version string.
- [ ] `request` — `{ prompt, modality, instanceCount, seedSource }` where
      `seedSource` is `{type:"iod", sopClassUID}` or `{type:"pacs", studyUID}`.
- [ ] `attributes` — study/series-level tags shared by every file, in DICOM JSON
      Model form. **Must not** include pixel-module tags (validator rejects them).
- [ ] `perInstance` — rules evaluated per file (or per frame for multi-frame):
      `SOPInstanceUID:{rule:"uid"}`, `InstanceNumber:{rule:"index+1"}`,
      `SliceLocation:{rule:"linspace",start,step}`, `ImagePositionPatient:
      {rule:"derive_from_slice"}`, etc.
- [ ] `pixel` — the picture directive (IOD path only): `rows, columns,
      samplesPerPixel, photometricInterpretation, bitsAllocated, generator`.
      Authored by the AI from its knowledge; ignored on the PACS path.
- [ ] `identity` — synthetic identity policy (IOD path). On the PACS path, source
      identity is kept as-is for now.
- [ ] `overrides` — tag→value tweaks parsed from the request, applied last.
- [ ] `references` — **PR/KO only** (finalized shape). The images the markup points
      at, plus a small type-specific block. The Materializer builds the required
      sequences from this; the AI does **not** hand-author the nested SQ:
      ```jsonc
      "references": {
        "studyUID": "1.2.3",
        "series": [{ "seriesUID": "1.2.3.1",
                     "instances": [{ "sopClassUID": "…", "sopInstanceUID": "…" }] }],
        // PR only — minimal viable display settings:
        "presentation": { "window": {"center": 40, "width": 400},
                          "displayedArea": "full" },
        // KO only — minimal viable document header:
        "keyObject": { "titleCode": {"value":"113000","scheme":"DCM","meaning":"Of Interest"},
                       "description": "Key images" }
      }
      ```
- [ ] `multiFrame` — **multi-frame only** (finalized minimal set). Which settings go
      Shared vs Per-Frame; the Materializer injects the mandatory functional-group
      macro skeleton from the KB (`group_macros`):
      ```jsonc
      "multiFrame": {
        "numberOfFrames": 60,
        "shared":   { "PixelMeasures": {"PixelSpacing":["0.7","0.7"],"SliceThickness":"1.0"},
                      "PlaneOrientation": {"ImageOrientationPatient":["1","0","0","0","1","0"]} },
        "perFrame": { "PlanePosition": {"rule":"ImagePositionPatient linspace"},
                      "FrameContent":  {"rule":"index"} },
        "dimensionOrganization": "stack"   // minimal DimensionIndexSequence
      }
      ```
- [ ] `provenance` — `{grounded, knowledgeRefs, authoredBy, specSource, kbEdition}`.

**Tasks:**

- [ ] Write the schema (as a JSON Schema or a documented shape).
- [ ] Write 3–4 example order slips (single-frame CT, US color, one multi-frame, one
      KO) to drive the validator/materializer tests.
- [ ] **XML (Native DICOM Model) is JSON-only for now** — not built until a real
      consumer needs it (finalized; see §19).

---

## 7. Spec Validator + repair loop

**What it does:** cheap, deterministic check of the order slip before building.

**Checks (tasks):**

- [ ] Tag exists (KB / pydicom dictionary).
- [ ] Value matches the tag's VR (reuse `generator.strict_value_validation`).
- [ ] Tag is allowed for this scan type (KB).
- [ ] All required (Type 1) tags present and non-empty; Type 2 present (may be empty).
- [ ] Protected tags (UIDs, per-file computed tags) are **not** pinned in
      `attributes`.
- [ ] **Pixel-module tags rejected** in `attributes` (Materializer owns them).
- [ ] **Cross-tag "make sense together" rules:**
  - [ ] Pixel group: `SamplesPerPixel` ↔ `PhotometricInterpretation` ↔
        `PlanarConfiguration`; `BitsAllocated ≥ BitsStored > HighBit`;
        `PixelRepresentation ∈ {0,1}`.
  - [ ] `Modality` matches the scan class implied by `SOPClassUID`.
  - [ ] Geometry triplet (`ImageOrientationPatient` / `ImagePositionPatient` /
        `PixelSpacing`) present-together and well-formed when any is present.
- [ ] Return a compact error list `{tag, keyword, reason}`.
- [ ] On success, store the slip and return a `spec_id`.

**Repair loop tasks:**

- [ ] Bounded retries (e.g. ≤ 2). On failure, hand the AI the specific errors so it
      fixes just those fields (send a diff, not the whole slip).
- [ ] After max retries, stop and report clearly (fail loud).

---

## 8. Spec Store (ticket numbers)

- [ ] Store order slips in memory keyed by `spec_id`.
- [ ] Look up a slip by `spec_id` for `materialize_dataset`.
- [ ] Apply a small repair **diff** to a stored slip (so repairs don't resend it).
- [ ] Note the limitation: in-memory, lost on restart (acceptable for now).

---

## 9. Materializer (order slip → files)

Refactor `generator.py` into `materializer.py`. Core loop is reused; the seed source
and pixel handling change.

**Common tasks:**

- [ ] Take a `spec_id` (not the full slip).
- [ ] Build the base dataset:
  - [ ] PACS seed: load the fetched source instance; **keep its pixels and
        pixel-module tags untouched**; ignore the `pixel` directive.
  - [ ] Rulebook seed: build a minimal base (`file_meta` + fresh UIDs) from the scan
        class; **synthesize the pixel module** from the `pixel` directive.
- [ ] Set `file_meta` transfer syntax = **Explicit VR Little Endian, uncompressed**.
- [ ] Apply `attributes` via pydicom `from_json`.
- [ ] **Probe-first:** make one file, run the **full** `validate_dataset` on it; stop
      for repair if it fails, before making the rest.
- [ ] Make new Study/Series/SOP UIDs (reuse `uid_strategy`, deterministic per job).
- [ ] Loop: clone base, apply `perInstance` rules, apply `overrides`, run the
      fill-in-the-blanks safety net (any missing required tag → set empty or error),
      write to staging.
- [ ] Update the job registry throughout; return `{job_id, study_uid, output_path,
      count}`.

**Pixel synthesis tasks (generalize `seed_builder.py`):**

- [ ] Make a modality-agnostic pixel generator (noise/gradient/simple phantom),
      sized by rows/columns/bits/samples/photometric.
- [ ] Set viewer-safety defaults where needed (e.g. CT/MR `RescaleSlope`/`Intercept`,
      `WindowCenter`/`Width`) consistent with the generated value range.

**Multi-frame branch tasks:**

- [x] Treat `instanceCount` as **frames within one file**; set `NumberOfFrames`.
- [x] **Inject the mandatory functional-group skeleton from the KB** (`group_macros`
      + `Shared`/`Per-Frame Functional Groups Sequence` includes) — the code builds
      the required nested SQ structure; the AI only supplies the leaf values via the
      `multiFrame` block. (This is the spike-confirmed way to make deep nesting
      reliable — decision #3's safety valve.) Implemented generically in
      `iod_lookup.mandatory_group_macros()`/`macro_skeleton()`, consumed by
      `materializer._add_kb_functional_groups()` — verified end-to-end for
      Enhanced CT and Enhanced MR (probe passes with no per-modality code).
- [x] Fill Shared groups (Pixel Measures, Plane Orientation) + Per-Frame groups
      (Plane Position per frame, Frame Content) + a minimal Multi-frame Dimension.
- [ ] Probe validates that single multi-frame file.
- [ ] **Test-first:** land minimal viable, inspect, then refine.

**PR / KO branch tasks:**

- [ ] No pixel synthesis.
- [ ] Require a `references` block; resolve the referenced instances against the PACS;
      fail loud if they don't exist.
- [ ] **Inject the mandatory reference/document sequences from the KB** (PR:
      `Presentation State Relationship` → ReferencedSeriesSequence; KO:
      `Current Requested Procedure Evidence Sequence` + `SR Document Content`) from the
      `references` block — AI supplies leaf values (title code, window/level), code
      builds the SQ skeleton.
- [ ] **Test-first:** minimal viable, inspect, refine.

---

## 10. Extract, Modify, Prior (all one path)

- [ ] `spec_extractor.py` / `extract_spec`: fetch a study, turn it into an order slip
      (DICOM JSON Model). **No PHI scrubbing for now** — identity and pixels kept
      as-is.
- [ ] `/modify`: extract → AI applies overrides → materialize. Default makes a new
      study; in-place overwrite still needs the explicit `confirm_destructive` gate.
- [ ] Prior studies: extract the reference study → keep its identity → shift
      `StudyDate` → materialize. (Works naturally now that identity is preserved.)
- [ ] Simplify `resolve_seed` to two outcomes (`pacs` / `iod`); keep seed matching
      lightweight (modality query + `StudyDescription` substring; no per-file scans).

---

## 11. Recipe reuse

- [ ] `recipe_store.py`: save a working order slip after success.
- [ ] Key = modality + body part + orientation + scan class + a few module-flags
      (start with `contrast`, `localizer`). Overrides are **not** in the key —
      re-applied fresh each time.
- [ ] On a matching request, load the recipe and skip AI authoring + grounding.
- [ ] Version recipes by rulebook edition; drop/revalidate on an edition change.
- [ ] `list_recipes` / `get_recipe` tools (replace the old template tools).
- [ ] (Future) richer/semantic keying — noted, not built now.

---

## 12. MCP tools (the assistant's toolbox)

**New:**

- [ ] `get_iod_requirements(sop_class | modality)` → modules + tags.
- [ ] `describe_attributes(keywords[] | tags[])` → VR/VM/keyword lookups.
- [ ] `validate_spec(spec)` → `{grounded, spec_id, errors[], warnings[]}`.
- [ ] `materialize_dataset(spec_id, instance_count?, target_pacs?, job_id?)`.
- [ ] `extract_spec(study_uid | path)` → order slip.
- [x] `list_recipes(filters)` / `find_recipe(modality, body_part?, orientation?, ...)`.

**Changed:**

- [ ] `resolve_seed` → outcomes `pacs` / `iod`.
- [ ] `modify_dataset` → wrapper over extract → materialize.

**Unchanged:** `validate_dataset`, `store_to_pacs`, `list_pacs_studies`,
`check_pacs_feature`, `get_job_status`, `health_check`.

**Removed at cleanup:** `generate_dataset`, `list_templates`, `get_template_info`.

- [ ] Register/deregister all of the above in `server.py`.

---

## 13. Security, privacy, audit, token reporting

- [ ] Confirm the tool only points at the test PACS; add a clear warning that it is
      not for real patient data until scrubbing exists.
- [ ] Design note (not built now): the future `extract_spec` scrubbing layer — what
      it must strip before any real-PHI use. Needs sign-off then.
- [ ] Extend `audit_log` to record per job: full order slip (`spec_id` + content),
      provenance, rulebook edition. Disk only, no token cost.

### 13.1 Token-usage summary (answers "can we summarize tokens after generating?")

**What's possible and what isn't:**

- The MCP server **cannot see the full Copilot/GPT-4o token usage** — the system
  prompt, chat history, and the model's own reasoning live on the Copilot cloud side
  and are not exposed to tools. GitHub Copilot's own usage/premium-request view is the
  only authoritative source for actual billed usage.
- What the server **can** measure is the **tool-boundary payload**: the size of the
  order slip and every tool's arguments and results that flow through it. That's a good
  proxy for the "planning" cost the new design adds.

**Tasks:**

- [ ] Add a small `token_estimate` helper: count tokens of tool inputs/outputs (the
      order slip, `validate_spec`/`materialize_dataset` payloads) using a local
      tokenizer (`tiktoken`) or a `chars/4` fallback.
- [ ] Include an **`approx_tokens`** field in `materialize_dataset`'s final summary
      and in the audit log, clearly labelled *"tool-boundary estimate, excludes chat
      overhead."* Break it down: spec size + tool I/O + repair rounds used.
- [ ] Because pixels and file bytes never cross the tool boundary, this number stays
      small and confirms the token story to the user after each run.

**On "will the live Copilot run waste tokens?"** No — it's the acceptance test, not
waste. Each request is a few thousand tokens (see solution-design §13), and the
`approx_tokens` summary lets the user see it per run. The recipe cache means repeat
requests cost almost nothing.

---

## 14. Copilot Chat integration

- [ ] Update `.github/copilot-instructions.md`: the new flow (write/extract order slip
      → validate_spec → materialize), the ticket-number habit, no PHI, confirm big
      batches, say "no" for unsupported types.
- [ ] Update `.github/chatmodes/pixel-atlas.chatmode.md`: tool list, model.
- [ ] Update prompt files: `/generate`, `/modify`, `/validate`, `/status`, and
      `/list-recipes` (replacing `/list-templates`).
- [ ] Run the whole thing through a live Copilot Chat session (this has never been
      done end-to-end — expect follow-up fixes).

---

## 15. Testing

- [ ] **Deterministic tests (the code):** fixed order slips through `validate_spec`,
      `materialize_dataset`, `extract_spec`; expected pass/fail and file counts.
- [ ] **Good + broken order-slip fixtures** for the validator (every check has one).
- [ ] **End-to-end (no AI):** rulebook → order slip fixture → materialize → validate →
      store → re-query Orthanc, for one single-frame type.
- [ ] **PACS-seed end-to-end:** extract → materialize → validate → store.
- [ ] **By-hand checks (the AI parts):** a short list of real requests the user runs
      and eyeballs — especially multi-frame and PR/KO output.
- [ ] Keep the deterministic set small (per your call); the rest is user-validated.

---

## 16. Deployment & config

- [ ] No new services or prerequisites (KB uses existing `dicom-validator`; pixels use
      NumPy; XML converter, if added, is pure Python).
- [ ] New on-disk items: `recipes/` folder; the built KB artifact.
- [ ] Update `scripts/setup.ps1` only if the new folders/deps need it.

---

## 17. Cleanup / retirement

- [ ] Remove `templates/` and its catalog.
- [ ] Remove `generator.py`, `templates.py`, `scripts/generate_seed.py`.
- [ ] Remove old tools from `server.py`.
- [ ] Fold the AI-driven design docs into the main docs; mark the template-based docs
      as replaced; update the README reading order.

---

## 18. Decisions already locked (reference)

All from the pre-implementation review — see
[design-change-ai-driven.md §11](design-change-ai-driven.md#11-decisions-ledger) for
the full ledger. Short version:

1. Cross-tag consistency rules added to `validate_spec`.
2. Materializer owns the pixel module (rulebook path); PACS path keeps source pixels.
3. AI authors sequences; validator + probe catch mistakes.
4. Scope = all standard single- + multi-frame image types + PR + KO; refuse the rest.
5. Probe-first (validate one file before the rest).
6. `spec_id` ticket-number pattern to save tokens.
7. Recipe key = broad scan type + a few module-flags; overrides re-applied.
8. PHI scrubbing deferred (test tool on test data).
9. Small deterministic test set; rest validated by user.
10. Pin one rulebook edition; keep it warm.
11. Extend audit trail (disk only).
Plus: JSON canonical / XML later; seed matching stays description-based.

---

## 19. Previously-open items — now finalized (best-practice defaults)

- **Old tool aliases → none.** There is no v1 to keep compatible; remove
  `generate_dataset` / `list_templates` / `get_template_info` outright at cleanup
  (§17). Clean cut, no alias window.
- **XML serialization → not now.** JSON only (YAGNI). Build the Native DICOM Model
  XML converter only if/when a real consumer needs it; keep it a documented optional
  add-on.
- **Recipe module-flags → `contrast`, `localizer`** to start (single- vs multi-frame
  is already distinguished by SOP Class in the key, so no separate flag needed).
  Extend the list only as real needs appear.
- **`references` block (PR/KO) → finalized** — shape defined in §6; the Materializer
  builds the SQ skeleton from the KB, AI supplies leaf values.
- **Multi-frame functional groups → finalized minimal set** — Shared: Pixel Measures
  + Plane Orientation; Per-Frame: Plane Position + Frame Content; plus a minimal
  Multi-frame Dimension. Skeleton injected from KB `group_macros` (§6, §9).
- **PHI-scrubbing design → remains deliberately deferred** (decision #8). Not built;
  flagged as a hard prerequisite before any real-PHI use. No further action now.

No open blockers remain. Anything genuinely new will be handled as it surfaces during
the build.

---

## 20. Known issues / risks (flagged)

1. **Rulebook coverage — RESOLVED** by the §5 spike: 16/16 target types covered in
   edition 2026c. Pin `dicom-validator` 0.8.2 + edition 2026c so it stays stable.
2. **Never run through Copilot Chat yet** — §14 is the first real live test;
   historically where surprises appear.
3. **Multi-frame & PR/KO nested structures** — mitigated: the spike showed the KB
   exposes the full nested skeleton (`group_macros`, sequence `include`s), so the
   **code injects the mandatory SQ skeleton and the AI only fills leaf values**
   (§9). Still test-first, since leaf-value correctness needs real-output review.
4. **PR/KO need targets to exist first** — generate/find them before the markup.
5. **Synthetic pixels are noise** — valid and viewable, not realistic. Out of scope.
6. **No PHI scrubbing now** — test data only; must add before real use.
7. **In-memory state** (`spec_id`, jobs) lost on restart — fine for now.
8. **AI values correct-but-not-always-sensible** — checks guarantee valid, not
   clinically real.

---

## 21. Master task checklist (grouped for phasing)

Copy these groups into phases when you decide sequencing.

- **A. Foundations:** KB spike, KB reader + tables, order-slip schema + examples.
- **B. Build core (single-frame):** Spec Validator + repair, Spec Store, Materializer
  core + pixel synthesis, probe-first, `materialize_dataset`.
- **C. Reuse existing data:** `extract_spec`, `modify_dataset` rework, `resolve_seed`
  simplify, prior studies.
- **D. Recipes:** `recipe_store`, keying, `list_recipes`/`get_recipe`.
- **E. Hard scan types (test-first):** multi-frame branch, PR/KO branch.
- **F. Assistant wiring:** instructions, chatmode, prompts, live Copilot run.
- **G. Quality:** deterministic tests, fixtures, end-to-end tests, audit extension.
- **H. Cleanup:** retire template code/tools/docs, update README.
