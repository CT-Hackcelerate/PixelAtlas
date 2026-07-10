# `mcp-server/`

The Pixel Atlas MCP server — a local Python process that exposes DICOM
generation/validation/PACS tools over MCP stdio to Copilot Chat (or any other
MCP client). See [architecture.md §3](../docs/architecture.md#3-dicom-mcp-server--bare-minimum-spec)
for the full tool contract and [execution-plan-phases1-3.md](../docs/execution-plan-phases1-3.md)
for what's implemented so far.

## Files

| File | Responsibility |
|---|---|
| `server.py` | Entry point. Registers all MCP tools on a `FastMCP` instance and runs over stdio — including `get_iod_requirements(template_id?, sop_class_uid?)`, a read-only lookup into a template's `iod_spec.yaml` knowledge base. Start here to see the full tool list. Also attaches a stderr handler to the root logger at import time, **before** anything else runs — `dicom_validator` attaches its own stdout handler to the root logger on first use if none exists yet, which would corrupt the stdio JSON-RPC channel; don't remove this without checking that dependency's logging behavior first. |
| `config.py` | All environment-driven configuration (template/staging/log directories, Orthanc URL + credentials, test UID root, `dicom-validator`'s standard-cache path). Nothing else in this folder should read `os.environ` directly. |
| `orthanc_client.py` | Thin wrapper around the Orthanc REST API — reachability (`is_reachable`), study search (`find_studies`), a study's patient identity/date (`get_study_details`, used by priors), every instance ID for a study (`list_instance_ids`, used by `modify_dataset`/standalone validate), an instance's full tag set (`get_instance_tags`, used by `check_pacs_feature`), fetching instance bytes (`fetch_instance_bytes`/`fetch_first_instance_bytes`), and uploading an instance (`upload_instance`, the `storescu`-unavailable fallback for `store_to_pacs`). |
| `templates.py` | Loads `templates/catalog.yaml` and per-template `manifest.yaml` files (generation fill-rules). No PACS or subprocess calls — pure filesystem reads. |
| `iod_lookup.py` | Loads/queries each template's committed `iod_spec.yaml` (the IOD knowledge base: mandatory/conditional/optional modules and their tags — see `templates/README.md`). Pure YAML reader, no `dicom-validator` import here or anywhere else in the runtime path (`scripts/generate_iod_spec.py` is the only place that reads `dicom-validator` directly, offline, to author the committed file). Backs the `get_iod_requirements` tool, `generator.py`'s fill-in-the-blanks safety net, and `modify.py`'s override validation against a study's actual SOP Class. |
| `seed_builder.py` | `build_minimal_seed(...)`/`write_seed(...)` — one shared, modality-agnostic builder for a template's pixel-only fallback seed (`seed/IM0001.dcm`). Used by `scripts/generate_seed.py`, not imported by `server.py` directly. |
| `job_registry.py` | In-memory `job_id -> {state, progress_pct, message}` store (v1, no persistence across restarts). Written to by `generator.py`/`modify.py`, and by `server.py`'s `store_to_pacs`/`validate_dataset` wrappers (which infer `job_id` from the staging folder name), read by `get_job_status`. |
| `uid_strategy.py` | `new_uid(job_id, index)` — deterministic UID generation under `config.TEST_OID_ROOT` (solution-design.md §7). Same `(job_id, index)` always yields the same UID, so a retried job doesn't create duplicates. |
| `seed_resolver.py` | `resolve_seed(modality, body_part?, orientation?)` — PACS-first/template-fallback seed resolution (solution-design.md §3). |
| `override_policy.py` | Shared override-tag validation used by both `generator.py` and `modify.py`: `validate_overrides(overrides, tag_rules, valid_keywords)` rejects a tag only if it's `protected` (a template's `tag_rules.sequence` keys, plus the UIDs the generator always regenerates — `protected_tags_for(tag_rules)`) or absent from the target IOD's known tag list. Everything else valid for the IOD is a legal override — there's no separate hand-curated allow-list. Also owns `PlanError` (re-exported by `generator.py` for existing importers). Dependency-free by design (no imports of `generator`/`modify`/`templates`/`iod_lookup`) to avoid an import cycle. |
| `generator.py` | `generate_dataset(...)` — the core generation loop: loads the resolved seed, applies the template's tag rules + overrides via `pydicom` (not `dcmodify` — see module docstring), runs a fill-in-the-blanks safety net against `iod_lookup`'s IOD knowledge base for any unconditional Type 1/Type 2 tag still missing (empty for Type 2, a clear `PlanError` naming the tag for Type 1), writes new UIDs, saves to `staging/<job_id>/`. Also supports **priors**: pass `prior_of_study_uid`/`days_before` to reuse a reference study's `PatientID`/`PatientName`/`StudyDate` (offset earlier) instead of drawing a new synthetic patient — see `_resolve_prior_identity`. Exposes `apply_overrides`/`strict_value_validation`, reused by `modify.py` rather than duplicated. |
| `modify.py` | `modify_dataset(study_uid, overrides?, regenerate_uids=True, job_id?)` — fetches every instance of an existing PACS study (sorted by `InstanceNumber` — Orthanc's listing order doesn't guarantee that), validates overrides via `override_policy.validate_overrides` against the study's actual IOD (`iod_lookup`) and a best-effort `tag_rules` match by modality (for sequence-tag protection), applies overrides via `generator.apply_overrides`, and either writes a new derived study (`regenerate_uids=True`, default) or keeps the original UIDs (`regenerate_uids=False` — destructive; gated behind `confirm_destructive` at the `server.py` tool layer, not here). |
| `validator.py` | `validate_dataset(path?, study_uid?)` — IOD conformance via `dicom-validator` (not `dciodvfy` — see module docstring), cross-instance structural checks (100% of instances), and `dcmftest` on a sampled subset. `study_uid` fetches every instance into a throwaway `staging/validate-<id>/` folder first (`_materialize_study`, also sorted by `InstanceNumber`) and reuses the same path-based checks. |
| `pacs_store.py` | `store_to_pacs(path)` — `storescu` batch C-STORE, falling back to `orthanc_client.upload_instance` if `storescu` isn't on PATH. The `server.py` tool wrapper requires `confirm_store=True` on every call (not just large/destructive ones) — this is the one step that reaches the shared PACS, so it's gated the same way `confirm_destructive` gates `modify_dataset`'s in-place path. |
| `feature_lookup.py` | `check_pacs_feature(tag, value?, modality?, date_range?)` — generic "does the PACS already have a study with this tag/value" lookup. Accepts a DICOM keyword or `GGGG,EEEE` hex tag (normalized via `pydicom.datadict`); checks one representative instance per candidate study. No NL-to-tag mapping here by design — the model resolves the user's phrase to a DICOM keyword itself before calling it. |
| `audit_log.py` | Appends one JSON line per tool call to `.pixel-atlas/logs/agent.log` — timestamp, tool name, input summary, outcome. No raw PHI-shaped values are logged. |
| `requirements.txt` | `mcp`, `pydicom`, `PyYAML`, `requests`, `numpy`, `dicom-validator`. Install into the repo-root `.venv` (see root [README.md](../README.md)). |

## Adding a new tool

1. Write the function in `server.py` (or a new module imported by it) and
   decorate with `@mcp.tool()` — the docstring becomes the tool description
   shown to the model.
2. Call `audit_log.log_call(...)` before returning, so every invocation is
   traceable.
3. If it's a Phase 3+ tool that mutates state (e.g. `modify_dataset`), update
   `job_registry` and reuse `generator`/`validator`/`pacs_store` rather than
   re-implementing tag/PACS logic inline.
4. Add a corresponding `.github/prompts/<command>.prompt.md` if it should be
   reachable as a slash command (see [.github/README.md](../.github/README.md)).

## Running it directly (outside VS Code)

```powershell
..\.venv\Scripts\python server.py
```

It idles waiting for MCP stdio messages — fine for confirming there's no
import/startup error, but for functional testing it's easier to import the
tool functions directly in a Python shell, e.g.:

```python
import server
server.health_check()
server.list_templates()
```
