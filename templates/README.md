# `templates/`

The IOD knowledge base + tag template catalog — see
[solution-design.md §6](../docs/solution-design.md#6-template-system) for the
full design. A "template" here is **three things**, not a full binary study:

1. `iod_spec.yaml` — a static, human-reviewable dump of what the DICOM
   standard itself requires for this IOD: every module (mandatory/
   conditional/user-optional) and, for mandatory/conditional modules, every
   tag with its Type (1/1C/2/2C/3), VR, and any machine-checkable condition.
   Generated once via `scripts/generate_iod_spec.py`, then committed and
   maintained like any other source file — **never read from
   `dicom-validator` at request time**, only at authoring time.
2. `manifest.yaml` — generation-convenience fill defaults on top of that IOD
   (`fixed`/`sequence`/`randomized` tag rules). There's no separate override
   allow-list: `mcp-server/override_policy.py` computes each template's
   `protected_tags` (its `tag_rules.sequence` keys, plus the UIDs the
   generator always regenerates) — any other tag valid for the IOD can be
   overridden.
3. `seed/IM0001.dcm` — pixel data and enough structure to be a loadable file.
   **Not** the source of tag-conformance truth — replaceable at any time with
   any other pixel-bearing file, since tag correctness comes from (1) and (2)
   at generation time, not from what's baked into this binary.

This is consulted for more than `/generate`: `get_iod_requirements` lets the
agent check a tag's legitimacy/type directly against an IOD (used by
`/modify` to validate a requested tag edit against an existing PACS study's
*actual* SOP Class, not a guessed modality match), and is meant to back
future advanced PACS queries that reason about which tags are meaningful for
a given modality.

## Layout

Templates are organized primarily by **DICOM IOD**, not by use case: each
`<MODALITY>/<template_id>/` folder here is the generic Image IOD for that
modality — `ct-image` is the CT Image IOD, `mr-image` is the MR Image IOD, and
so on. Use-case templates (a chest-CT protocol, a screening-mammography
protocol, ...) can be added later as sibling folders under the same modality,
layering their own tag rules and seed data on top of the same IOD — see
below.

```
templates/
  catalog.yaml                     # flat index read by list_templates — add new templates here
  <MODALITY>/<template_id>/
    iod_spec.yaml                  # the knowledge base: modules/tags this IOD requires/allows,
                                    # committed, generated once via scripts/generate_iod_spec.py
    manifest.yaml                  # generation fill defaults (read by get_template_info)
    seed/                          # pixel-data-only fallback seed .dcm(s), replaceable any time —
                                    # only used if resolve_seed finds nothing similar in the PACS
```

Currently implemented, one generic IOD template per modality:

| template_id | IOD | modality |
|---|---|---|
| `CT/ct-image` | CT Image IOD | CT |
| `MR/mr-image` | MR Image IOD | MR |
| `US/us-image` | Ultrasound Image IOD | US |
| `MG/mg-image` | Digital Mammography X-Ray Image IOD (For Presentation) | MG |

There's a single `scripts/generate_seed.py <template_id>` shared by every
modality — the per-modality pixel shape (bit depth, samples per pixel,
whether a Frame of Reference UID is needed) is an optional `seed_params`
block in that template's `manifest.yaml`, read by `seed_builder.py`'s
`build_minimal_seed`, not a separate script per modality.

`generator.py` also runs a safety-net fill step at generation time: any
unconditional Type 1/Type 2 tag from `iod_spec.yaml` still missing after
`tag_rules` and overrides are applied gets an empty value (Type 2) or raises
a clear error naming exactly which mandatory tags need a rule (Type 1) —
catching a template author's mistake at generation time instead of only via
`validate_dataset`'s after-the-fact `dicom-validator` check.

## Adding a new template

Follow [solution-design.md §6.5](../docs/solution-design.md#65-adding-a-new-tag-template).
Two kinds of additions:

- **A new IOD** (e.g. CR, XA): run
  `python scripts/generate_iod_spec.py <sop_class_uid> templates/<MODALITY>/<modality>-image/iod_spec.yaml`,
  review the output by hand, then author `manifest.yaml` (fill defaults for
  the Type 1/2 tags `iod_spec.yaml` says are mandatory; add a `seed_params`
  block only if this modality's pixel shape needs to differ from
  `seed_builder.build_minimal_seed`'s defaults — e.g. 8-bit grayscale, or a
  Frame of Reference module). There's one shared `scripts/generate_seed.py
  <template_id>` for every modality — no per-modality script to write.
- **A use-case template on top of an existing IOD** (e.g. a chest-CT or
  screening-mammography protocol): add a sibling folder under the same
  modality (e.g. `CT/ct-chest-axial/`) that points at the same
  `sop_class_uid` (and can reuse that IOD's `iod_spec.yaml` — no need to
  regenerate it) with its own `manifest.yaml` layering additional
  `fixed`/`sequence`/`randomized` rules (body part, orientation, protocol
  specifics), plus its own seed data if needed.

Either way:

1. Generate/reuse `iod_spec.yaml` — the knowledge base of what this IOD
   requires. This is what you read to know which tags `manifest.yaml` needs
   fill rules for.
2. Write `manifest.yaml` under `<MODALITY>/<template_id>/` describing
   `fixed`/`sequence`/`randomized` tag rules. No allow-list to write — any
   `tag_rules.sequence` key is automatically protected from overrides.
3. Add 1-3 anonymized sample instances under `seed/`, or generate a
   pixel-only one via `python scripts/generate_seed.py <template_id>` — never
   real patient data; run through an anonymizer first if sourced from a real
   system.
4. Add an entry to `catalog.yaml` (`template_id`, `iod_name`, `modality`,
   `body_part`, `orientation`, `path`, `has_seed_data`).
5. Restart the MCP server and confirm `list_templates`/`get_template_info`/
   `get_iod_requirements` pick it up. Run `generate_dataset` for a small
   count and `validate_dataset` the result before trusting it further.

No template-authoring UI or upload endpoint exists (or is planned for v1) —
this folder is edited directly and reviewed via normal PR, per
[solution-design.md §6.5](../docs/solution-design.md#65-adding-a-new-tag-template).
