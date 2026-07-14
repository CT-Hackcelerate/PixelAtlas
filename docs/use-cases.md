# Pixel Atlas — Use Cases

What the tool must do from a user's perspective. See
[solution-design.md](solution-design.md) for **how**, and
[architecture.md](architecture.md) for components/deployment.

## 1. Purpose

Test engineers, developers, and QA staff need realistic-but-synthetic DICOM
studies (modality, instance count, orientation, body part, demographics) to
exercise PACS ingestion, viewers, and imaging pipelines — without hand-editing
sample files. Pixel Atlas lets a user ask in plain language inside an AI
coding agent (Claude Code or Copilot Chat), and have the agent build valid
files (grounded on a DICOM standard-derived Knowledge Base, not hand-authored
templates) and load them into a test PACS (Orthanc).

## 2. Actors

| Actor | Description |
|---|---|
| **Test/QA Engineer** (primary) | Requests synthetic studies to test viewers, PACS routing, worklist/HL7 flows, or automated pipelines. Not a DICOM expert. |
| **Developer** (primary) | Needs quick sample data while building/debugging a DICOM-handling feature. |
| **CI Pipeline** (future, out of scope) | Would invoke the tool headlessly to seed a test PACS before regression runs. |

## 3. Use Case Catalog

| ID | Name | Command |
|---|---|---|
| UC-01 | Generate a new synthetic study | `/generate` (→ `find_recipe`/spec authoring → `validate_spec` → `materialize_dataset`) |
| UC-02 | Generate with tag overrides | `/generate` |
| UC-03 | Modify or clone an existing PACS study | `/modify` (→ `modify_dataset`) |
| UC-04 | Validate a dataset for DICOM conformance | `/validate` |
| UC-05 | Check job or environment status | `/status` |
| UC-06 | List cached recipes | `/list-recipes` |
| UC-07 | Generic PACS feature lookup | `/check-feature` |
| UC-08 | Multi-series studies (same study, multiple series) | `/generate` with `study_uid` |
| UC-09 | PR/KO markup referencing existing instances | manual spec flow |
| UC-10 (future) | Headless/CI-triggered generation | n/a |

## 4. Detailed Use Cases

### UC-01/02 — Generate a new synthetic study

- **Trigger:** *"Generate 200 axial CT instances"* or with overrides, *"...
  PatientAge 34Y, manufacturer Siemens"*.
- **Main flow:**
  1. Agent resolves modality/count/body part/orientation from the request.
  2. Agent calls `find_recipe(...)` for this request signature. On a hit,
     reuses the cached spec. On a miss, resolves a seed (`resolve_seed`) and
     either extracts a spec from a matching PACS study (`extract_spec`) or
     authors one from the KB (`get_iod_requirements`/`describe_attributes`) —
     grounded, not templated.
  3. Agent applies any requested tag values into `attributes`/`perInstance`,
     calls `validate_spec` → `materialize_dataset`.
  4. Agent confirms with the user if count > 50 or cardinality is ambiguous
     (e.g. "N instances" could mean N frames for a multi-frame ask).
  5. Agent shows the compact summary (UIDs, count, validation, approx token
     estimate), gets a **separate** confirmation, then calls
     `store_to_pacs(confirm_store=True)`.
- **Alternate flow (unsupported modality/type):** `get_iod_requirements`/
  `resolve_seed` reports the IOD family as unsupported (e.g. SR/RT/SEG/
  encapsulated docs) — the agent reports it and stops, never substitutes a
  different modality.
- **Postconditions:** A new, valid, conformant study exists in the PACS;
  nothing existing is modified.

### UC-03 — Modify or clone an existing PACS study

- **Trigger:** *"Change PatientAge on study 1.2.3.4.5, keep the original."*
- **Main flow:**
  1. Agent locates the source study (`list_pacs_studies` if not named directly).
  2. Agent calls `modify_dataset(study_uid, overrides, regenerate_uids=true)`
     — **default is non-destructive**: a new derived study is created.
  3. Agent validates and stores the derived study.
- **Alternate flow (explicit in-place edit):** User asks to overwrite in
  place — agent confirms this is destructive and irreversible before calling
  `modify_dataset(regenerate_uids=false, confirm_destructive=true)`.
- **Postconditions:** Either a new derived study (default) or the original
  overwritten (only on explicit confirmation).

### UC-04 — Validate a dataset for DICOM conformance

- **Trigger:** *"Validate the study I just generated"* or *"/validate study=..."*.
- **Main flow:** Agent calls `validate_dataset(path?|study_uid?)` and reports
  pass/fail per check category (IOD conformance, structural checks,
  `dcmftest`) with a bounded number of example errors.
- **Postconditions:** Read-only.

### UC-05 — Check job or environment status

- **Trigger:** *"/status"* or *"/status job=abc123"*.
- **Main flow:** `get_job_status(job_id)` if a job ID is given, else
  `health_check()` (MCP server, Orthanc, DCMTK binaries, KB edition).
- **Postconditions:** Read-only.

### UC-06 — List cached recipes

- **Trigger:** *"What have we generated before for MR?"* or *"/list-recipes"*.
- **Main flow:** `list_recipes(modality?, body_part?, orientation?)` returns
  cached, previously-validated Generation Specs. A recipe hit means the next
  matching request skips planning and materializes directly.
- **Postconditions:** Read-only. (Recipes auto-grow — there's no separate
  "author a new recipe" step or coverage gap to fill; the KB covers every
  supported IOD from the first request.)

### UC-07 — Generic PACS feature lookup

- **Trigger:** *"Do we have any CT study with a Modality LUT?"*
- **Main flow:** Agent resolves the phrase to a DICOM keyword itself (no
  built-in NL-to-tag mapping), then calls `check_pacs_feature(tag, value?,
  modality?, date_range?)`.
- **Postconditions:** Read-only.

### UC-08 — Multi-series studies

- **Trigger:** *"Generate a CT series and an MR series in the same study."*
- **Main flow:** Generate + store series 1, note its `study_uid`, then for
  series 2 set `spec["request"]["attachStudyUID"] = <series 1's study_uid>`
  before `validate_spec`/`materialize_dataset` — it pins to the same study
  and reuses PatientID/PatientName/StudyDate automatically. Repeat per
  series.
- **Postconditions:** One study, multiple series, consistent identity.

### UC-09 — PR/KO markup referencing existing instances

- **Trigger:** *"Add a presentation state marking up the CT I just stored."*
- **Main flow:** `list_series_instances(study_uid, series_uid)` to get
  concrete instance UIDs, author a spec with a `references` block naming
  them, then `validate_spec` → `materialize_dataset`. PR/KO always point at
  data that must already exist — no `pixel` directive.
- **Postconditions:** A new PR or KO instance in the same study, referencing
  the named instances.

### UC-10 (Future) — Headless/CI-triggered generation

- Out of scope today (requires an interactive agent chat session). Documented
  as a future extensibility path only.

## 5. Non-Functional Requirements

| Requirement | Detail |
|---|---|
| **No real PHI, ever** | All generated/modified data is synthetic. |
| **Non-destructive by default** | Generation always creates a new study; modify creates a derived study unless the user explicitly confirms an in-place overwrite. |
| **Token economy** | One Generation Spec per study (O(1) in instance count); the Materializer expands to N files in a single deterministic tool call, not N LLM turns. |
| **Conformance** | Every generated/modified study passes IOD-level DICOM validation (probe-first, then full sampled validation) before store. |
| **Auditability** | Every tool call and every generated job is logged locally (spec + provenance + KB edition), at zero token cost. |
| **No coverage gaps** | The KB covers every standard image IOD plus PR/KO from the first request — no "no template for this yet" dead end within that supported family. |

## 6. Out of Scope

- Clinically realistic pixel data — synthesized noise/gradient/phantom only.
- Structured Reports (SR), RT objects, Segmentation (SEG), encapsulated
  documents, Waveforms — the agent says "not supported," never substitutes.
- PHI scrubbing — deferred; this is a test tool on test/synthetic data only.
- Multi-tenant SaaS hosting, headless/CI invocation (UC-10).
