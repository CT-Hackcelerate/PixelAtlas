# Pixel Atlas Quick Start

Minimal guide to get generating DICOM data in minutes.

## Setup

If not yet done, follow [SETUP.md](SETUP.md) (takes ~30 min).

## Common Flows

### 1. Generate a single series (most common)

```
User: "Generate 100 axial CT instances, patient age 34Y"

Claude:
  1. find_recipe(modality="CT", orientation="axial") → miss (first time)
  2. resolve_seed(modality="CT", orientation="axial") → get_iod_requirements("CT")
  3. Authors the Generation Spec: attributes, perInstance rules, pixel directive
  4. validate_spec(spec) with overrides={"PatientAge": "034Y"} applied → spec_id
  5. materialize_dataset(spec_id, instance_count=100)
  6. [shows summary and UIDs]
  7. store_to_pacs(output_path, confirm_store=True)
  8. ✓ Study stored, link to Orthanc; a recipe is auto-cached for next time
```

**Result:** One DICOM study with 100 instances, one series, in the PACS. A
repeat "axial CT" request later hits the recipe cache and skips steps 2-4.

---

### 2. Multi-frame (e.g., 60-frame US cine at 30 fps)

```
User: "Generate a US multi-frame, 60 frames at 30 fps"

Claude:
  1. find_recipe(modality="US", enhanced=True) → author on a miss
  2. Spec: request.instanceCount=60, attributes includes
     CineRate="30", FrameTime="33.333"
  3. validate_spec(spec) → materialize_dataset(spec_id, instance_count=60)
  4. [shows summary]
  5. store_to_pacs(output_path, confirm_store=True)
```

**Result:** One study, one series, one instance with 60 frames.

---

### 3. Multi-series study (e.g., 2 CT series)

```
User: "Generate 2 CT series in the same study"

Claude asks: "Same modality? OK. Series 1: how many instances?"
User: "Series 1: 50 instances, Series 2: 50 instances"

Claude:
  1. [author/reuse CT spec, instanceCount=50] → validate_spec → materialize_dataset
     [shows study_uid = "1.2.3.4.5"]
  2. store_to_pacs(output_path, confirm_store=True)
     ✓ Series 1 stored

  3. [second CT spec, instanceCount=50, request.attachStudyUID="1.2.3.4.5"]
     → validate_spec → materialize_dataset
     [same study, same patient ID/name — reused automatically]
  4. store_to_pacs(output_path, confirm_store=True)
     ✓ Series 2 stored, same study
```

**Result:** One study with 2 series (100 total instances).

---

### 4. Add PR (Presentation State) referencing a series

```
User: "Add a PR markup state pointing to series 1's first image"

Claude:
  1. list_series_instances(study_uid="1.2.3.4.5", series_uid="series1-uid")
     [returns instance UIDs]

  2. [Creates references block from the instance list]

  3. validate_spec(spec) → materialize_dataset → store_to_pacs
     ✓ PR stored in same study
```

**Result:** Study now has Image series + PR in same study.

---

## Key Commands

| What | Command |
|---|---|
| **Check recipe cache** | `find_recipe(modality, body_part=..., orientation=...)` |
| **Ground before authoring** | `get_iod_requirements(modality)`, `describe_attributes(names)` |
| **Validate a spec** | `validate_spec(spec)` |
| **Build files from a spec** | `materialize_dataset(spec_id, instance_count=...)` |
| **Store to PACS** | `store_to_pacs(output_path, confirm_store=True)` |
| **Attach series to existing study** | set `spec["request"]["attachStudyUID"] = "x.y.z"` |
| **List instance UIDs** | `list_series_instances(study_uid, series_uid)` |
| **Check PACS for a tag** | `check_pacs_feature(tag="SOPClassUID")` |
| **Validate generated files** | `validate_dataset(path=...)` |
| **List recipes** | `list_recipes(modality="CT")` |
| **Environment health** | `health_check()` |

---

## Modality Shortcuts

These are all `find_recipe` → author-if-miss → `validate_spec` →
`materialize_dataset` under the hood — Claude handles the mechanics; you just
describe what you want:

| Need | Ask for |
|---|---|
| Basic CT 10 slices | "CT, 10 instances" |
| Enhanced CT 50 frames | "Enhanced CT, 50 frames" |
| US 60-frame cine at 60fps | "US multi-frame cine, 60 frames at 60fps" |
| MR axial T1 | "MR axial, ScanningSequence SE" |
| Chest X-ray (DX) | "DX, 1 instance" |
| Mammogram (MG) | "MG, 2 instances" |

---

## Tips

1. **Always confirm before store** — Claude will show validation results; review them
2. **Reuse UIDs** — Once you store series 1, capture its `study_uid` to attach series 2 to the same study (`request.attachStudyUID`)
3. **Check recipes** — `list_recipes()` shows previously-generated patterns; `find_recipe()` reuses one directly, skipping authoring
4. **Orthanc web UI** — http://localhost:8042 — download, view, or delete studies (useful for testing)
5. **Series vs instances** — "N instances" = one series of N files; "N series" = ask for clarification

---

## Common Issues

| Problem | Fix |
|---|---|
| "Orthanc unreachable" | Check `docker ps` — if orthanc not running, see SETUP.md Part 4 |
| "Cannot attach to study XYZ" | Study not yet stored, or wrong UID — store series 1 first |
| "PR has no instances" | List instances first with `list_series_instances()`, pass exact UIDs |
| "Type 1 tag missing" | Claude repairs a couple of times automatically; if repair fails, check the spec's `attributes` or re-check `get_iod_requirements` |

---

## Next

- See [solution-design.md](solution-design.md) for how this all works under the hood
- See [SETUP.md](SETUP.md) if you need to troubleshoot environment
- See [sample-prompts.md](sample-prompts.md) for more advanced examples
