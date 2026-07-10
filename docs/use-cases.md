# Pixel Atlas Copilot Agent — Use Cases

## 1. Purpose

Test engineers, developers, and QA staff regularly need realistic-but-synthetic DICOM
studies (specific modality, instance count, orientation, body part, patient
demographics) to exercise PACS ingestion, viewers, and imaging pipelines. Today this
is done manually with ad-hoc scripts and hand-edited sample files. This document
defines the use cases for a **GitHub Copilot agent** ("Pixel Atlas Agent") that
lets a user request test DICOM data in natural language inside VS Code, and have the
agent plan the required tags, clone/modify a study — preferring similar data already
in the PACS and falling back to a bundled template only when nothing similar exists
— validate the result, and push it to a PACS (Orthanc in the reference environment).

This document covers **what** the agent must do from a user's perspective. See
[solution-design.md](solution-design.md) for **how** it does it, and
[architecture.md](architecture.md) for the components and deployment.

## 2. Actors

| Actor | Description |
|---|---|
| **Test/QA Engineer** (primary) | Requests synthetic studies to test viewers, PACS routing, worklist/HL7 flows, or automated pipelines. Has VS Code + Copilot but is not a DICOM expert. |
| **Developer** (primary) | Needs quick sample data while building or debugging a DICOM-handling feature. Comfortable reading tag names. |
| **Test Data Administrator** (secondary) | Curates the template catalog, reviews/approves new templates, owns the shared test-PACS instance. |
| **CI Pipeline** (future, out of scope v1) | Would invoke the agent headlessly to seed a test PACS before automated regression runs. |

## 3. Glossary

| Term | Meaning |
|---|---|
| **Tag template** | A per-modality/study-type specification (not a full DICOM file) describing *which* DICOM tags are required, their VR, and which are fixed/sequential/randomized/overridable. Used to plan tag values and to validate overrides — consulted on every request, regardless of where the seed data comes from. |
| **Template seed data** | A small, anonymized, structurally-minimal sample `.dcm` file bundled with a tag template, used only as a **fallback** cloning source when no similar data exists in the PACS, and only after explicit user confirmation. |
| **Similarity search** | The agent's PACS query (by modality/body part/orientation/SOP Class) to check whether data close enough to the request already exists, performed *before* considering the template seed fallback. |
| **Generation job** | One invocation of the generate/modify pipeline, tracked by a job ID until it completes or fails. |
| **PACS** | Picture Archiving and Communication System — Orthanc in the default dev setup, see [orthanc-setup.md](orthanc-setup.md). |

## 4. Use Case Catalog

| ID | Name | Primary Actor | Command |
|---|---|---|---|
| UC-01 | Generate a new synthetic study from a template | QA/Dev | `/generate` |
| UC-02 | Generate with custom attributes/overrides | QA/Dev | `/generate` |
| UC-03 | Modify or clone an existing PACS study | QA/Dev | `/modify` |
| UC-04 | Validate a dataset for DICOM conformance | QA/Dev | `/validate` |
| UC-05 | Check job or environment status | QA/Dev | `/status` |
| UC-06 | List available tag templates / discover coverage | QA/Dev/Admin | `/list-templates` |
| UC-07 | Handle a true coverage gap — no PACS match and no template (notify + suggest/contribute) | QA/Dev/Admin | `/generate` (fallback path) |
| UC-08 | Bulk/multi-study generation for a test suite | QA/Dev | `/generate` (batch mode) |
| UC-09 (future) | Headless/CI-triggered generation | CI Pipeline | n/a (Skillset API, see [architecture.md](architecture.md#9-extensibility--path-b-hosted-copilot-extension)) |

## 5. Detailed Use Cases

### UC-01 — Generate a new synthetic study, preferring existing PACS data over templates

- **Trigger:** User types e.g. *"Generate CT data with 200 axial instances"* in Copilot Chat.
- **Preconditions:** DICOM MCP server running and registered; Orthanc reachable. A tag template for CT does **not** need to exist yet at this point — see alternate flows.
- **Main flow:**
  1. Agent parses intent → modality=CT, instance_count=200, orientation=axial.
  2. Agent calls `get_template_info`/`list_templates` for CT to learn which tags are required/overridable for this modality (the tag template — see [solution-design.md §6](solution-design.md#6-template-system)). This does **not** yet decide where the seed data comes from.
  3. Agent calls `resolve_seed(modality=CT, orientation=axial)` to check the PACS **first** for existing data similar enough to clone from.
  4. **If similar data is found in the PACS** (the expected, preferred case): agent proceeds using that PACS study as the seed — see Alternate Flow A.
  5. **If no similar data is found in the PACS:** agent explicitly tells the user and asks before falling back to the bundled template seed data — see Alternate Flow B.
  6. Once a seed is resolved, agent confirms the plan with the user (modality, count, body part, seed source, target PACS) since count > 50.
  7. User confirms.
  8. Agent calls `generate_dataset(...)`, which clones the resolved seed, rewrites tags per the tag template, and generates new UIDs.
  9. Agent calls `validate_dataset(...)` on the output.
  10. Agent calls `store_to_pacs(...)`.
  11. Agent reports: StudyInstanceUID, instance count stored, validation summary, seed source used, and an Orthanc link.
- **Alternate Flow A — similar data found in PACS:** `resolve_seed` returns one or more candidate studies already in the PACS. If exactly one strong match, the agent uses it automatically (no extra confirmation beyond the standard count threshold in step 6 — using real, already-trusted PACS data is the preferred path, not a risky one). If multiple candidates match, the agent lists up to 5 and asks the user to pick one (or to use the template fallback instead).
- **Alternate Flow B — no similar data in PACS, template available:** Agent states plainly that no similar data was found in the PACS for the requested criteria, and asks: *"Use the built-in CT template seed instead?"* Generation only proceeds using template seed data after the user explicitly confirms. See also [UC-07](#uc-07--handle-a-true-coverage-gap-no-pacs-match-and-no-template).
- **Alternate Flow C — no similar data in PACS and no template exists either:** True coverage gap — see [UC-07](#uc-07--handle-a-true-coverage-gap-no-pacs-match-and-no-template).
- **Postconditions:** A new, valid, conformant study exists in the PACS; nothing in the template catalog and no existing PACS study was modified (generation always writes a new study).
- **Related MCP tools:** `resolve_seed`, `list_templates`, `get_template_info`, `list_pacs_studies`, `generate_dataset`, `validate_dataset`, `store_to_pacs`, `get_job_status`.

### UC-02 — Generate with custom attributes/overrides

- **Trigger:** *"Generate 50 MR sagittal instances, PatientAge 34Y, manufacturer Siemens, body part BRAIN."*
- **Main flow:** Same as UC-01 (PACS-first seed resolution, then template-seed fallback with confirmation if needed), but the parsed plan includes explicit tag overrides that are validated against the tag template (is the tag allowed to be overridden? is the value type-correct for its VR?) before generation.
- **Alternate flow:** If a requested override tag is not recognized or its value fails VR validation (e.g., a non-numeric `PatientAge`), the agent reports the specific tag/value problem instead of guessing, and asks for a corrected value.
- **Postconditions:** Generated study reflects the resolved seed (PACS or template) plus the explicit overrides.

### UC-03 — Modify or clone an existing PACS study

- **Trigger:** *"Take study 1.2.3.4.5 from PACS and make a copy as an MR instead of CT, keep everything else."*
- **Preconditions:** The source study exists in the configured PACS (found via `list_pacs_studies` or a supplied StudyInstanceUID).
- **Main flow:**
  1. Agent locates/fetches the source study.
  2. Agent calls `modify_dataset(source, overrides, regenerate_uids=true)` — **default is non-destructive**: a new Study/Series/SOP UID set is generated so the original study is never mutated.
  3. Agent validates and stores the derived study as a new PACS entry.
  4. Agent reports the new StudyInstanceUID alongside the original one.
- **Alternate flow (explicit in-place edit):** If the user explicitly asks to overwrite the existing study (`regenerate_uids=false`), the agent restates that this is destructive and requires an explicit confirmation before proceeding.
- **Postconditions:** Either a new derived study exists (default) or the original study was overwritten (only on explicit confirmation).

### UC-04 — Validate a dataset for DICOM conformance

- **Trigger:** *"Validate the study I just generated"* or *"/validate study=1.2.3.4.5"*.
- **Main flow:**
  1. Agent resolves the target (job output path, or StudyInstanceUID to pull from PACS).
  2. Agent calls `validate_dataset(...)`.
  3. Agent reports pass/fail per check category (IOD conformance, UID uniqueness, cross-instance consistency, pixel data integrity), with a bounded number of example errors, not a full per-instance dump.
- **Postconditions:** No data is changed; a validation report is returned to the user.

### UC-05 — Check job or environment status

- **Trigger:** *"/status"*, *"/status job=abc123"*, or *"Is the MCP server and PACS up?"*
- **Main flow:**
  1. If a job ID is given, agent calls `get_job_status(job_id)` and reports state/progress.
  2. If no job ID is given, agent runs an environment health check (MCP server reachable, DCMTK binaries found, PACS reachable) and reports a short status table.
- **Postconditions:** Read-only; nothing is changed.

### UC-06 — List available tag templates / discover coverage

- **Trigger:** *"What templates do we have for MR?"* or *"/list-templates"*.
- **Main flow:** Agent calls `list_templates(...)` with optional filters and returns a compact table (modality, body part, orientation, required-tag summary, whether fallback seed data is bundled). Long lists are paginated rather than dumped in full. This is a catalog browse — it does not query the PACS.
- **Postconditions:** Read-only.

### UC-07 — Handle a true coverage gap (no PACS match and no template)

- **Trigger:** *"Generate 100 PET axial instances"* when the PACS has no PET data at all and no PET tag template exists in the catalog.
- **Main flow:**
  1. `resolve_seed(modality=PET, orientation=axial)` returns no PACS candidates.
  2. `list_templates(modality=PET)` also returns empty.
  3. Agent explicitly tells the user that neither existing PACS data nor a built-in template was found for the request (never silently substitutes a different modality).
  4. Agent lists the closest available alternatives (e.g., existing CT/MR PACS data or templates, or a PET template with a different orientation) using catalog and PACS metadata.
  5. Agent explains how to contribute a new tag template (see [solution-design.md §6.5](solution-design.md#65-adding-a-new-tag-template)) and offers to open a tracking note/issue if the user wants one filed.
- **Postconditions:** No generation happens against a mismatched template or unrelated PACS data; the user has a clear next step.

### UC-08 — Bulk/multi-study generation for a test suite

- **Trigger:** *"Generate 5 CT studies and 3 MR studies for the regression suite."*
- **Main flow:** Agent expands the request into a list of individual generation plans, confirms the full batch once (not per study), and executes each as an independent `generate_dataset` job so a single failure doesn't block the rest. A single consolidated summary table is returned at the end.
- **Postconditions:** Multiple independent studies in PACS; a per-study status list (succeeded/failed) is reported.

### UC-09 (Future) — Headless/CI-triggered generation

- Out of scope for v1 (VS Code Agent Mode requires an interactive chat session). Documented as the motivating use case for the hosted Copilot Extension/Skillset extensibility path — see [architecture.md §9](architecture.md#9-extensibility--path-b-hosted-copilot-extension).

## 6. Non-Functional Requirements

| Requirement | Detail |
|---|---|
| **PACS-first sourcing** | The agent always checks the PACS for similar existing data before considering the bundled template seed data as a fallback, and never uses the fallback without explicit user confirmation. See [UC-01](#uc-01--generate-a-new-synthetic-study-preferring-existing-pacs-data-over-templates). |
| **No real PHI, ever** | All generated/modified data must be synthetic. Template seed data checked into the repo must already be anonymized before being added to the catalog. |
| **Non-destructive by default** | Cloning/modifying never overwrites the source PACS study, the source template, or an existing PACS study unless the user explicitly confirms an in-place edit. |
| **Token economy** | Bulk operations (e.g., 200-instance loops) run as deterministic code inside a single MCP tool call, not as repeated LLM turns. See [solution-design.md §14](solution-design.md#14-token--cost-economy). |
| **Conformance** | Every generated/modified study must pass IOD-level DICOM validation before being stored. |
| **Predictable performance** | Generating 200 instances from an existing template should complete in low tens of seconds on a dev laptop, dominated by file I/O and `storescu`, not LLM latency. |
| **Auditability** | Every generation/modify/store action is logged with job ID, requested plan, and outcome. |
| **Idempotency** | Re-running a failed job with the same job ID resumes/retries rather than duplicating already-stored instances. |

## 7. Out of Scope (v1)

- Clinically validated / diagnostic-quality pixel data — pixel data is either reused from the template or synthetically generated placeholder content, not medically meaningful.
- Multi-tenant SaaS hosting, per-user auth beyond GitHub/Copilot identity.
- Headless/CI invocation (UC-09) — documented as a future extensibility path only.
- Automatic template authoring from arbitrary uploaded files without human review.
