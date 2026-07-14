# Pixel Atlas — Design Change: Templates → AI-Driven Knowledge

> **Status: implemented — historical record.** This is the change/migration document for the redesign in
> [solution-design.md](../solution-design.md) and
> [architecture.md](../architecture.md). It maps every delta
> against the *current* template-based design
> (solution-design.md,
> architecture.md, [use-cases.md](../use-cases.md)) and the code
> under [mcp-server/](../../mcp-server/). Kept as a record of the migration, which is
> now complete.

## 1. Summary of the change

Replace **hand-authored per-template DICOM knowledge** with **AI-authored,
standard-grounded knowledge**:

- DICOM IOD requirements move from N committed `iod_spec.yaml` files into **one
  standard-derived DICOM Knowledge Base (KB)** covering every SOP Class.
- The agent authors a **DICOM Generation Spec** — a JSON document (canonically
  the DICOM JSON Model, PS3.18 Annex F; XML alternate) — for **any valid
  request**, grounded on the KB rather than picking from a fixed template
  catalog.
- A deterministic **Materializer** library converts the spec into `.dcm` files.
- The template catalog is replaced by an **auto-grown recipe cache** of
  validated specs; authoring a template is no longer a prerequisite for coverage.

## 2. Assumptions & decisions (confirmed)

1. **Canonical IR = DICOM JSON Model (JSON); XML (Native DICOM Model) supported
   as an alternate serialization.** JSON is directly `pydicom.from_json`-loadable
   and lighter on tokens.
2. **Delivered as new draft docs alongside the existing ones** — current
   template-based docs remain intact for comparison until the migration is
   approved.
3. **Migration is additive first:** the current template path keeps working while
   the AI-driven path is built beside it; templates are retired only after the
   KB/spec path reaches parity (see [§9](#9-phased-migration)).

## 3. Before / after

| Aspect | Current (template-based) | Proposed (AI-driven) |
|---|---|---|
| Source of IOD knowledge | Per-template `iod_spec.yaml` (hand-generated, committed) | One standard-derived **Knowledge Base**, all SOP Classes |
| Coverage | Only modalities/study types someone authored | **Any valid** modality/IOD the standard defines |
| What the AI produces | A modality choice + a flat set of tag overrides | A full **Generation Spec** (JSON/XML IR) grounded on the KB |
| How tags get filled | `manifest.yaml` `fixed`/`sequence`/`randomized` rules | AI-authored `attributes` + `perInstance` rules in the spec |
| Seed of the data | A bundled `seed/IM0001.dcm` per template, or a cloned PACS study | `extract_spec` from a PACS study, or a KB-built minimal base |
| Pixel data | Cloned from the seed `.dcm` | Synthesized from a `pixel` directive (modality-agnostic) |
| "Catalog" | Hand-curated `catalog.yaml` + template folders | **Recipe cache**, auto-grown from successful generations |
| No-match outcome | Coverage gap → no generation (UC-07) | KB fallback → always generatable; only *invalid* requests stop |
| Pre-generation safety | `override_policy` allow-list from manifest | `validate_spec` grounding vs KB (any IOD) |
| Post-generation safety | `validate_dataset` (unchanged) | `validate_dataset` (**unchanged**) |

## 4. Conceptual shift

```
CURRENT:  request → pick template → clone seed → apply manifest rules + overrides → validate → store
                     └── knowledge is baked into the chosen template ──┘

PROPOSED: request → (extract_spec from PACS  OR  author spec from KB) → validate_spec
                    → materialize (expand N, synth pixels, UIDs) → validate → store → cache recipe
                     └── knowledge is the reusable KB; the AI applies it per request ──┘
```

The template stops being the *unit of knowledge* and is replaced by (a) the KB
as the reusable knowledge, and (b) the recipe cache as emergent, reusable
*results*.

## 5. Impact on existing design documents

| Doc | Impact |
|---|---|
| [use-cases.md](../use-cases.md) | UC-01/02/03 flows re-expressed as spec author/extract → materialize (same user experience). **UC-07 shrinks** from "coverage gap" to "invalid-request" handling — no PACS match no longer implies no generation. Glossary: "tag template"/"template seed data" → "Knowledge Base"/"Generation Spec"/"recipe." Non-functional requirements (PHI, non-destructive, token economy, conformance, idempotency) all carry over. |
| solution-design.md | §1 principles revised ([new §2](../solution-design.md#2-design-principles-revised)); §3 seed resolution keeps PACS-first but the fallback becomes KB-authoring not template-seed; §5 GenerationPlan → **Generation Spec** IR; **§6 Template System → §6 Knowledge Base + §5 IR + §14 Recipe cache**; §8 generation execution → **Materialization** (same machinery, spec-driven); §7 UID, §9 modify, §10 validation, §11 store, §13 status, §15 error handling, §16 security **largely unchanged**; §12 no-match → [no coverage gaps](../solution-design.md#11-no-more-coverage-gaps). |
| architecture.md | §2 components: Template Engine → **KB + Spec Validator + Materializer + Spec Extractor + Recipe Store**; §3 tool contract updated ([new §3](../architecture.md#3-revised-mcp-tool-contract)); §5 deployment, §6 prerequisites **unchanged** (no new services/prereqs); §9 Path B unchanged and better-fit. |
| The old build logs (implementation-status, execution-plan-phase4/phases1-3) | Deleted in the docs cleanup — this redesign realized what the superseded "Phase 4" plan had proposed (KB-driven generation), via an explicit JSON IR + Materializer + grounding loop. |
| [docs/README.md](../README.md), [root README.md](../../README.md) | Updated to point at the AI-driven docs. |
| [templates/README.md](../templates/README.md), [scripts/README.md](../scripts/README.md) | Reframed once templates are retired (see §6/§9). |

## 6. Impact on code (mcp-server/ and friends)

Grounded in the actual files under [mcp-server/](../../mcp-server/),
[templates/](../templates/), and [scripts/](../scripts/).

| File | Change |
|---|---|
| [iod_lookup.py](../../mcp-server/iod_lookup.py) | **Becomes the KB.** Expand from per-template `iod_spec.yaml` reads to standard-derived lookups across all SOP Classes; back `get_iod_requirements` + new `describe_attributes`. Single wrapper over `dicom-validator` standard data + pydicom dictionary. |
| **`spec_validator.py`** (new) | Implements `validate_spec` — grounding vs KB + the curated **cross-tag consistency rules** (decision #1) + pixel-module-tag rejection (decision #2). Absorbs [override_policy.py](../../mcp-server/override_policy.py)'s protected-tag logic, generalized from manifest-derived to KB-derived. On success stores the spec and returns a `spec_id` (decision #6). |
| **`spec_store.py`** (new) | Server-side store of validated specs keyed by `spec_id` (decision #6) so specs aren't re-sent between tools; supports diff-apply for repairs. |
| **`materializer.py`** (new) | Implements `materialize_dataset` — takes a `spec_id` → `.dcm`. Largely a refactor of [generator.py](../../mcp-server/generator.py): reuse UID assignment, override application, `strict_value_validation`, staging output, job-registry updates, and `_fill_missing_iod_tags`. Adds **probe-first** validation (decision #5), **multi-frame/PR/KO** branches (decision #4), and **preserves source pixels on the PACS path** (decision #2). |
| **`spec_extractor.py`** (new) | Implements `extract_spec` — fetch a study via [orthanc_client.py](../../mcp-server/orthanc_client.py), emit DICOM JSON Model. **No PHI scrubbing for now** (decision #8) — identity/pixels preserved as-is. |
| [seed_builder.py](../../mcp-server/seed_builder.py) | **Generalize** its pixel synthesis to be fully modality-agnostic (driven by the spec's `pixel` directive); it becomes the Image Pixel module synthesizer for the `iod`-seed path **only** (decision #2). Its `build_minimal_seed` becomes the base-dataset builder. |
| [generator.py](../../mcp-server/generator.py) | Superseded by `materializer.py`; kept during migration for the template path (§9), then retired. |
| [seed_resolver.py](../../mcp-server/seed_resolver.py) | Simplify `resolve_seed` outcomes to `pacs` / `iod` (drop `template`/`none` coverage-gap branch). |
| [modify.py](../../mcp-server/modify.py) | Reframe over `extract_spec` → overrides → `materialize_dataset`; keep the `confirm_destructive` gate and `regenerate_uids` semantics. |
| **`recipe_store.py`** (new) | Cache/browse validated specs; back `list_recipes`/`get_recipe`. Replaces [templates.py](../../mcp-server/templates.py). |
| [templates.py](../../mcp-server/templates.py) | Retired once `recipe_store.py` reaches parity; `list_templates`/`get_template_info` deprecated → `list_recipes`/`get_recipe`. |
| [validator.py](../../mcp-server/validator.py) | **Unchanged** (already the right post-generation gate; already loads the standard data the KB will share). |
| [audit_log.py](../../mcp-server/audit_log.py) | **Extended** (decision #11) — record full spec + provenance + KB edition per job. Server-side only, zero token cost. |
| [uid_strategy.py](../../mcp-server/uid_strategy.py), [pacs_store.py](../../mcp-server/pacs_store.py), [feature_lookup.py](../../mcp-server/feature_lookup.py), [orthanc_client.py](../../mcp-server/orthanc_client.py), [job_registry.py](../../mcp-server/job_registry.py), [config.py](../../mcp-server/config.py) | **Unchanged.** |
| [server.py](../../mcp-server/server.py) | Register new tools (`describe_attributes`, `validate_spec`, `materialize_dataset`, `extract_spec`, `list_recipes`, `get_recipe`); keep old tools during migration behind a deprecation notice. |
| [scripts/generate_iod_spec.py](../scripts/generate_iod_spec.py) | Repurposed to **build the KB** (one artifact) instead of per-template `iod_spec.yaml`. |
| [scripts/generate_seed.py](../scripts/generate_seed.py) | Retired — pixel data is synthesized at materialization from the `pixel` directive, not pre-generated per template. |
| [templates/](../templates/) (`CT/ct-image`, `MR/mr-image`, `US/us-image`, `MG/mg-image`, `catalog.yaml`) | Retired as a *prerequisite*; any still-valuable ones can be re-committed as curated **recipes**. |
| [.github/prompts/](../.github/prompts/), [.github/chatmodes/pixel-atlas.chatmode.md](../.github/chatmodes/pixel-atlas.chatmode.md), [.github/copilot-instructions.md](../.github/copilot-instructions.md) | Update to instruct the agent to author/extract + ground a spec (and use `validate_spec` + the repair loop), replace `/list-templates` with `/list-recipes`. |

## 7. MCP tool changes at a glance

- **New:** `describe_attributes`, `validate_spec`, `materialize_dataset`,
  `extract_spec`, `list_recipes`, `get_recipe`.
- **Changed:** `get_iod_requirements` (full-KB), `resolve_seed` (outcomes
  `pacs`/`iod`), `modify_dataset` (wrapper over extract→materialize).
- **Deprecated:** `generate_dataset` → `materialize_dataset`; `list_templates` /
  `get_template_info` → `list_recipes` / `get_recipe`.
- **Unchanged:** `validate_dataset`, `store_to_pacs`, `list_pacs_studies`,
  `check_pacs_feature`, `get_job_status`, `health_check`.

## 8. What is explicitly preserved

- PACS-first seed sourcing; non-destructive-by-default; validate-before-store;
  fail-loud-on-ambiguity.
- Deterministic per-`(job_id, index)` UIDs and idempotent retry.
- The full post-generation `validate_dataset` conformance + structural pipeline
  and its sampling/report-capping policy.
- Token economy: one bounded LLM planning artifact per study; all bulk work in a
  single deterministic tool call; no binaries/pixels in chat.
- Prior-study generation, `check_pacs_feature`, the destructive-overwrite gate,
  the audit log, and the local `.venv`-MCP-server-plus-Dockerized-Orthanc
  deployment.

## 9. Phased migration

Additive, so the current path never breaks mid-flight:

1. **KB foundation** — expand `iod_lookup.py` to the full standard-derived KB;
   add `describe_attributes`; verify `get_iod_requirements` for several SOP
   Classes with no existing template. *No behavior change to the template path.*
2. **Spec + grounding** — define the Generation Spec schema; build
   `spec_validator.py` + `validate_spec`. Test grounding against known-good and
   deliberately-broken specs.
3. **Materializer — classic single-frame IODs first** (the build-order decision):
   build `materializer.py` + `materialize_dataset` + `spec_store.py` (spec_id) by
   refactoring `generator.py`'s reusable core; generalize `seed_builder.py` pixel
   synthesis; add probe-first (decision #5). Prove `materialize → validate_dataset`
   gives `files_with_errors: 0` for a **single-frame** modality with no template.
   *This proves the whole pipeline end-to-end at the lowest complexity.*
4. **Extract + unify** — build `spec_extractor.py` + `extract_spec` (no scrub,
   decision #8); reframe `modify_dataset`; simplify `resolve_seed` to `pacs`/`iod`.
5. **Recipe cache** — build `recipe_store.py`; cache successful specs; add
   `list_recipes`/`get_recipe`; deprecate the template tools.
6. **Multi-frame IODs** — add the MF branch (count = frames, per-frame functional
   groups). AI authors the functional-group sequences (decision #3); **test output,
   then refine** — if a specific IOD churns the repair loop, add a
   Materializer-injected curated sequence for it.
7. **PR / KO IODs** — add the reference-based branch (`references` block resolved
   against the PACS, no pixel synthesis). **Test output, then refine.**
8. **Chat wiring + cutover** — update prompts/chatmode/instructions to the
   spec-authoring flow and the repair loop; run end-to-end through Copilot Chat
   (the still-open interactive-verification gap); retire `templates/`,
   `generator.py`, `templates.py`, `generate_seed.py`.
9. **Docs cutover** — fold the AI-driven drafts into the primary docs and update the
   reading order.

Steps 6–7 (MF, PR/KO) are explicitly **test-first**: land a minimal viable version,
inspect real output, then iterate — rather than trying to fully specify their
nested-sequence behavior up front.

Each phase is independently testable via direct tool calls (as Phases 1–3 were),
with the template path available as a fallback until Phase 6.

## 10. Risks & mitigations

| Risk | Mitigation |
|---|---|
| AI hallucinates a tag / wrong VR | `validate_spec` (pre-materialize) + `validate_dataset` (pre-store) — two deterministic gates |
| `dicom-validator` internal KB shape changes | Pin version; isolate behind `iod_lookup.py` |
| Repair loop token cost on hard requests | Bounded retries; recipe cache avoids re-paying for known requests |
| Regression vs the proven template path during migration | Keep both paths live until Phase 6; golden-spec regression tests mirror today's golden-template tests |
| XML fidelity | JSON canonical; XML gated behind a round-trip test |
| Loss of human review that templates got | Curated recipes can be committed/PR-reviewed; conformance enforced regardless |

## 11. Decisions ledger

All pre-implementation review points are resolved. The full list (earlier
decisions plus the 11-point pre-implementation review):

**From earlier rounds:**

- **Seed matching → lightweight (description-based), unchanged from today.**
  `resolve_seed` queries only indexed `ModalitiesInStudy` server-side and matches
  `body_part`/`orientation` as `StudyDescription` substrings; **no per-instance tag
  scanning**. See
  [solution-design.md §4.1](../solution-design.md#41-seed-matching-criteria-kept-lightweight).
- **KB edition policy → pin one edition for now**; recipes versioned by edition,
  re-validated/dropped only on a deliberate future bump.
- **IR format → JSON canonical (DICOM JSON Model), XML alternate.**

**Pre-implementation review (11 points):**

1. **Cross-tag consistency → add curated rules to `validate_spec`** (pixel-module
   group, Modality↔SOPClass, geometry triplet). Not full clinical validation;
   accept "conformant-but-plausible" otherwise. → sol-design §9.
2. **Pixel/Image-Pixel module → Materializer-owned from the `pixel` directive;
   `validate_spec` rejects pixel-module tags in `attributes`.** On the **PACS-seed
   path, don't touch them** — source pixels/pixel-module tags are cloned as-is. →
   sol-design §5.3, §10.
3. **Sequences → let the AI author them; the validator + probe + repair loop catch
   failures.** Not scoped out of v1. Highest repair-churn risk; watch in testing. →
   sol-design §8, §17.
4. **IOD family → all standard single-frame *and* multi-frame image IODs, plus PR
   and KO; refuse the rest** (SR, RT, SEG, encapsulated docs, waveforms). MF ⇒
   count = frames + per-frame functional groups; PR/KO ⇒ reference-based, no
   pixels. → sol-design §10, §11.
5. **Post-materialize failures → probe-first:** materialize + fully validate one
   instance before expanding to N. → sol-design §10, §13.
6. **Token optimization → spec-handle (`spec_id`) pattern:** AI emits the spec
   once; `validate_spec` stores it and returns `spec_id`; `materialize_dataset`
   and repairs reference it (diffs only). ~halves the new-path premium. →
   sol-design §13; arch §3.
7. **Recipe key → coarse structural tuple + a small set of module-affecting flags**
   (contrast, localizer, …), overrides re-applied fresh (7a). Richer/semantic
   keying is future scope (7b). → sol-design §14.
8. **PHI scrubbing → DEFERRED (reverses the earlier "privacy-first" call).** Tool
   is not for production; the reference PACS is assumed to hold test data, so
   `extract_spec` reuses source identity/pixels as-is. Side effect: priors stay
   linked with no identity map. **Must add a scrubbing layer before any real-PHI
   production use.** → sol-design §8, §15.
9. **Testing → small deterministic fixture set** for `validate_spec`/materializer/
   `extract_spec`; the rest validated interactively by the user. Don't
   snapshot-test AI authoring. → §9 of this doc.
10. **KB coverage/warm-up → optimize + best practice:** load standard data once,
    keep warm across calls; verify target-modality coverage in the phase-1 spike. →
    sol-design §13, §17.
11. **Audit trail → extend** (full spec + provenance + KB edition per job). Free on
    tokens because it's written server-side only, never to chat. → sol-design §15;
    arch §2.

**Still open (non-blocking):**

- **Deprecation window** — how long to keep `generate_dataset`/`list_templates`
  as aliases before removal.
- **XML promotion** — ship XML from day one, or JSON-only until a round-trip test
  suite exists?
- **`extract_spec` scrubbing design** — deferred (decision #8), but must be
  designed + signed off before any real-PHI use.
- **Hard-IOD fallback** — if a specific multi-frame/PR/KO IOD proves consistently
  hard for AI-authored sequences (decision #3), add a Materializer-injected
  curated sequence for it.
