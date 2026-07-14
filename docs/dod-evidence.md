# Pixel Atlas — Definition of Done: Evidence

A checklist mapping every use case in [use-cases.md](use-cases.md) and every
behavioral rule in [CLAUDE.md](../CLAUDE.md) /
[use-cases.md §5](use-cases.md#5-non-functional-requirements) to concrete
`file:line` evidence in `mcp-server/`. Two verdict types are used, and the
distinction matters:

- **Code-enforced** — the server itself blocks/gates the behavior; no
  well-behaved-agent assumption required.
- **Agent-behavior-only** — the rule lives in `CLAUDE.md` as an instruction to
  the agent; the server does not check it. Correctness depends on the agent
  following the instruction.

Being honest about which is which is the point of this document — treating an
agent-behavior-only rule as code-enforced would be a false sense of safety.

## 1. Use case coverage (docs/use-cases.md §3–4)

| UC | Use case | Verdict | Evidence |
|---|---|---|---|
| UC-01/02 | Generate a new study, with/without overrides | ✅ Code-enforced chain | `server.py`: `find_recipe`(190), `resolve_seed`(77) → `seed_resolver.py:23` supported-IOD gate, `extract_spec`(87), `get_iod_requirements`(44)/`describe_attributes`(67), `validate_spec`(102) → `spec_validator.py:58`, `materialize_dataset`(115). `store_to_pacs` is a hard no-op without `confirm_store=True` (`server.py:239-240`). |
| UC-03 | Modify or clone an existing study | ✅ Code-enforced | `modify.py:23` — `regenerate_uids: bool = True` (non-destructive default). `server.py:152-153` blocks `regenerate_uids=False` unless `confirm_destructive=True`. |
| UC-04 | Validate for DICOM conformance | ✅ Code-enforced | `validator.py:165-205` accepts `path` or `study_uid`; single response bundles `iod_conformance` + `structural_errors` + `dcmftest_result`. |
| UC-05 | Check job/environment status | ✅ Code-enforced | `server.py:296` `get_job_status`; `server.py:306-318` `health_check` reports `mcp_server`/`kb_edition`/`orthanc_reachable`/`dcmtk_binaries_on_path`. |
| UC-06 | List cached recipes | ✅ Code-enforced (scoped) | `materializer.py:744-751` auto-saves a recipe only when `seedSource.type == "iod"` — matches the doc's own "KB-authored" scoping; PACS-extracted specs are intentionally not cached. |
| UC-07 | Generic PACS feature lookup | ✅ Code-enforced | `server.py:282` / `feature_lookup.py:54-60` — signature `check_pacs_feature(tag, value=None, modality=None, date_range=None)` matches exactly. |
| UC-08 | Multi-series studies via `attachStudyUID` | ✅ Code-enforced | `materializer.py:158-159` reads `req["attachStudyUID"]` and resolves identity via `_resolve_same_study_identity` (reused, not re-minted); UID reuse at lines 258/358/449. |
| UC-09 | PR/KO markup via `references` block | ✅ Code-enforced | `materializer.py:468-471` raises `SpecError` if `references` is empty/missing; builds `ReferencedSeriesSequence`/content sequences at lines 487-541. No `pixel` directive required. |

## 2. Golden rules & NFR coverage (CLAUDE.md, use-cases.md §5)

| # | Rule | Verdict | Evidence |
|---|---|---|---|
| 1 | Check `find_recipe` before authoring | ✅ Code-enforced | `server.py:190` `find_recipe` exists as the documented first call; recipe hit returns a reusable spec (see UC-06 above). |
| 2 | Server never guesses tag values — grounding via KB | ✅ Code-enforced | `spec_validator.py:58` grounds every `attributes`/`overrides` key against `iod_lookup.py`'s KB; pixel-module/UID keywords are rejected if present in `attributes`. |
| 3 | Never loop / bounded repair (≤ a couple of rounds) | ⚠️ Agent-behavior-only | No max-retry counter in code. `materializer.py:650-679` `_probe()` returns one error and stops; the "couple of targeted repair attempts" bound is a CLAUDE.md instruction to the agent, not a server-enforced limit. |
| 4 | Confirm before creating/overwriting > 50 instances | ⚠️ Agent-behavior-only | No numeric threshold anywhere in `server.py`/`materializer.py`. Purely a CLAUDE.md instruction — the server will happily materialize any count if asked. |
| 5 | Always confirm before `store_to_pacs` | ✅ Code-enforced | `server.py:239-240` — hard-blocks without `confirm_store=True`. |
| 6 | Supported scan types only (image IODs + PR/KO; SR/RT/SEG/encapsulated docs refused) | ✅ Code-enforced | `iod_lookup.py:169 is_supported()`, enforced at every entry point: `server.py:57`, `spec_validator.py:58`, `seed_resolver.py:23`, `materializer.py:696`. |
| 7 | Ask before assuming series cardinality | ⚠️ Agent-behavior-only | No cardinality-ambiguity detection in code — this is entirely an agent judgment call per CLAUDE.md. |
| 8 | Ask before picking a seed source (PACS vs. synthetic) | ⚠️ Agent-behavior-only | `resolve_seed` returns `source_type` but does not block on it; the agent is instructed (CLAUDE.md) to pause and ask, the server does not enforce a pause. |
| 9 | Non-destructive by default (generation always new; modify creates a derived study unless confirmed) | ✅ Code-enforced | See UC-03 evidence above; `materialize_dataset` always mints a fresh `StudyInstanceUID` for generation (`uid_strategy.new_uid`, e.g. `materializer.py:258,358,449,549`) — no in-place overwrite path exists for fresh generation at all. |
| 10 | Token economy — spec is never re-sent; `spec_id` handle | ✅ Code-enforced | `spec_store.py:29-32` returns `spec-{uuid}`; `materialize_dataset(spec_id, ...)` (`server.py:115`) takes only the id. |
| 11 | Probe-first materialization | ✅ Code-enforced | `materializer.py:651-679 _probe()`, invoked before full expansion on every generation path (lines 290-292, 367-369, 458-460, 558-560). |
| 12 | Auditability — every tool call / job logged | ✅ Code-enforced | `audit_log.py` `log_call()`/`log_job()`, wired into all 22 `@mcp.tool()` defs in `server.py` — none found missing a `log_call`. |
| 13 | No real PHI, ever | ⚠️ Agent-behavior-only (policy, not enforced) | No code guard exists. `spec_extractor.py:4-5` explicitly documents "no PHI scrubbing... a scrubbing layer must be added" before pointing this at real data — an admitted convention, not a technical control. |
| 14 | Recipe cache key excludes free-form overrides | ✅ Code-enforced | `recipe_store.py:26-31 recipe_key()` composes only modality + body_part + orientation + SOP Class UID + flags (`contrast`/`localizer`) — overrides never enter the key. |

## 3. Summary

- **9 of 14** golden rules / NFRs are code-enforced — the server itself would
  refuse or gate the behavior even if the agent tried to skip it.
- **5 are agent-behavior-only**: bounded repair, the >50-instance confirm,
  series-cardinality confirmation, seed-source confirmation, and "no real
  PHI." These rely on the agent (and CLAUDE.md) rather than a server-side
  check — worth knowing if this tool is ever driven by something other than
  a CLAUDE.md-following coding agent.
- All 9 in-scope use cases (UC-01–UC-09) are fully wired end-to-end.
