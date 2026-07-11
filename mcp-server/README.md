# `mcp-server/`

The Pixel Atlas MCP server — a local Python process exposing DICOM
generation/validation/PACS tools over MCP stdio to an AI coding agent (Claude
Code, Copilot Chat, or any MCP client). This is the **AI-driven** design: the
agent authors a Generation Spec grounded on the DICOM Knowledge Base, which a
deterministic Materializer turns into `.dcm` files. See
[architecture.md](../docs/architecture.md) and
[ai-driven-comprehensive-plan.md](../docs/ai-driven-comprehensive-plan.md).

## Pipeline

**Preferred (one-shot):** `generate_study(modality, count, ...)` → `store_to_pacs`.
`generate_study` builds a conformant study server-side (defaults + probe-guided
auto-repair), so the agent makes one call — no spec authoring, no giant IOD dumps,
no loops.

**Advanced (manual authoring):** `resolve_seed` → (`extract_spec` from PACS, or
author from KB) → `validate_spec` (→ `spec_id`) → `materialize_dataset`
(probe-first) → `validate_dataset` → `store_to_pacs`. For editing existing studies
and PR/KO. Successful KB-authored specs are cached as recipes.

## Files

| File | Responsibility |
|---|---|
| `server.py` | Entry point. Registers all MCP tools on a `FastMCP` instance over stdio. Also attaches a stderr handler to the root logger at import time — `dicom_validator` would otherwise attach a stdout handler on first use and corrupt the stdio JSON-RPC channel; don't remove it. |
| `config.py` | Environment-driven config (recipes/staging/log dirs, Orthanc URL + credentials, test UID root, KB dir/edition). Nothing else reads `os.environ`. |
| `iod_lookup.py` | **The Knowledge Base.** Loads the **committed** KB JSON (`kb/2026c/dict_info.json`/`iod_info.json`/`module_info.json` — pinned edition, no network, no parse delay) once, shared with `validator.py`; answers `requirements(sop_class)`, `describe(tag)`, `valid_keywords`, `mandatory_tags`, modality↔SOP-Class resolution, and the supported-family / multi-frame / reference-object checks. Also the generic functional-group builder — `macro_skeleton(ref)`/`mandatory_group_macros(sop_class)` walk `group_macros` + nested `items`/`include` to build any modality's mandatory macro structure with zero per-modality Python, and `_cond_holds` resolves Type-1C/2C tags whose condition is already known (e.g. SOPClassUID-based). Backs `get_iod_requirements`/`describe_attributes`. |
| `spec_store.py` | In-memory store of validated Generation Specs keyed by `spec_id` (the token-saving handle); `apply_diff` for repairs. Owns `SpecError`. |
| `dicom_apply.py` | Shared value application: `apply_value_map` (keyword→value with strict VR validation) + sequence coercion. Used by the validator and materializer. |
| `defaults.py` | Per-modality baseline Generation Specs + `autofill_required`/`fill_missing_tags` (probe-guided placeholder fill). What makes `generate_study` a one-shot: conformant study with no agent authoring. |
| `spec_validator.py` | `validate_spec` — grounds a spec vs the KB (tag existence, VR, IOD validity, pixel-module/UID placement) plus curated cross-tag rules (pixel group, Modality↔SOPClass, geometry). Stores the spec and returns a `spec_id` on success. |
| `seed_builder.py` | Pixel synthesis (`synth_pixels`: noise/gradient/phantom, single- or multi-frame) and `build_base` — the minimal base dataset for the KB (no-PACS-seed) path. Materializer-owned Image Pixel module. |
| `materializer.py` | `materialize_dataset(spec_id)` — builds `.dcm` files: single-frame (N files, probe-first), multi-frame (one file; functional-group skeleton built generically from the KB for any modality — CT/MR/PT/future, zero per-modality code), and PR/KO (reference-based, no pixels). Reuses `uid_strategy`, `job_registry`, `orthanc_client`, `seed_builder`, and `validator` (for the probe). Applies viewer-safety defaults, priors, synthetic identity; emits `approx_tokens`; auto-saves a recipe. |
| `spec_extractor.py` | `extract_spec(study_uid|path)` — turns an existing study into a Generation Spec (no PHI scrubbing; test data only) for the PACS-first and modify paths. |
| `recipe_store.py` | File-based recipe cache under `config.RECIPES_DIR`, keyed by modality+body_part+orientation+SOP-Class+flags; `save_recipe`/`find_recipe`/`list_recipes`/`get_recipe`. Replaces the old template catalog. |
| `modify.py` | `modify_dataset(study_uid, overrides?, regenerate_uids=True, …)` — fetches every instance (sorted by `InstanceNumber`), validates overrides via the KB, applies them via `dicom_apply`, and writes a new derived study or (gated) an in-place overwrite. |
| `seed_resolver.py` | `resolve_seed` — PACS-first; returns `pacs` / `iod` / `unsupported` (no coverage-gap branch — the KB covers every supported IOD). Lightweight matching (modality + StudyDescription substring). |
| `uid_strategy.py` | `new_uid(job_id, index)` — deterministic UIDs under `config.TEST_OID_ROOT`. |
| `validator.py` | `validate_dataset(path?|study_uid?)` — IOD conformance (`dicom-validator`), cross-instance structural checks, `dcmftest`. Skips the PixelData check for reference objects (PR/KO). Shares the KB's standard-data loader. |
| `pacs_store.py` | `store_to_pacs(path)` — `storescu` batch C-STORE, Orthanc REST fallback. Gated by `confirm_store=True` at the tool layer. |
| `feature_lookup.py` | `check_pacs_feature(tag, value?, …)` — generic "does the PACS have this tag/value" lookup. |
| `orthanc_client.py` | Thin Orthanc REST wrapper (reachability, study search, instance fetch/upload, study details for priors). |
| `job_registry.py` | In-memory `job_id -> {state, progress_pct, message}` (no cross-restart persistence). |
| `token_util.py` | `estimate(obj)` — rough tool-boundary token estimate (tiktoken if present, else chars/4). |
| `audit_log.py` | `log_call` (one JSON line per tool call) + `log_job` (full spec + provenance + KB edition per job; disk only). |
| `requirements.txt` | `mcp`, `pydicom`, `requests`, `numpy`, `dicom-validator` (+ optional `tiktoken`). Install into the repo-root `.venv`. |
| `kb/2026c/` | The **committed DICOM Knowledge Base** — `dict_info.json`/`iod_info.json`/`module_info.json`, pinned to standard edition 2026c. Checked into the repo so every environment sees identical data with no network fetch. Rebuild only if the pinned edition changes (re-copy dicom-validator's `~/.dicom-validator/<edition>/json/` output). |

## Adding a new tool

1. Write the function in `server.py` (or a module it imports), decorate with
   `@mcp.tool()` — the docstring is the tool description shown to the model.
2. Call `audit_log.log_call(...)` before returning.
3. Reuse `spec_validator`/`materializer`/`validator`/`pacs_store` rather than
   re-implementing tag/PACS logic; raise `SpecError` for plan failures.
4. Add a `.github/prompts/<command>.prompt.md` if it should be a slash command.

## Running it directly (outside VS Code)

```powershell
..\.venv\Scripts\python server.py
```

It idles on MCP stdio (confirms no import/startup error). For functional testing,
import the modules and drive the pipeline directly (`spec_validator.validate_spec`
→ `materializer.materialize_dataset` → `validator.validate_dataset`).
