# Pixel Atlas Quick Start

Minimal guide to get generating DICOM data in minutes.

## Setup

If not yet done, follow [SETUP.md](SETUP.md) (takes ~30 min).

## Common Flows

### 1. Generate a single series (most common)

```
User: "Generate 100 axial CT instances, patient age 34Y"

Claude:
  1. generate_study(modality="CT", count=100, orientation="axial", overrides={"PatientAge": "034Y"})
  2. [shows summary and UIDs]
  3. store_to_pacs(output_path, confirm_store=True)
  4. ✓ Study stored, link to Orthanc
```

**Result:** One DICOM study with 100 instances, one series, in the PACS.

---

### 2. Multi-frame (e.g., 60-frame US cine at 30 fps)

```
User: "Generate a US multi-frame, 60 frames at 30 fps"

Claude:
  1. generate_study(modality="US", count=60, enhanced=True, cine_rate=30)
  2. [shows summary]
  3. store_to_pacs(output_path, confirm_store=True)
```

**Result:** One study, one series, one instance with 60 frames.

---

### 3. Multi-series study (e.g., 2 CT series)

```
User: "Generate 2 CT series in the same study"

Claude asks: "Same modality? OK. Series 1: how many instances?"
User: "Series 1: 50 instances, Series 2: 50 instances"

Claude:
  1. generate_study(modality="CT", count=50)
     [shows study_uid = "1.2.3.4.5"]
  2. store_to_pacs(output_path, confirm_store=True)
     ✓ Series 1 stored
  
  3. generate_study(modality="CT", count=50, study_uid="1.2.3.4.5")
     [same study, same patient ID/name]
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
| **Generate study** | `generate_study(modality, count, overrides=...)` |
| **Store to PACS** | `store_to_pacs(output_path, confirm_store=True)` |
| **Attach series to existing study** | `generate_study(..., study_uid="x.y.z")` |
| **List instance UIDs** | `list_series_instances(study_uid, series_uid)` |
| **Check PACS for a tag** | `check_pacs_feature(tag="SOPClassUID")` |
| **Validate generated files** | `validate_dataset(path=...)` |
| **List recipes** | `list_recipes(modality="CT")` |
| **Environment health** | `health_check()` |

---

## Modality Shortcuts

| Need | Command |
|---|---|
| Basic CT 10 slices | `generate_study("CT", 10)` |
| Enhanced CT 50 frames | `generate_study("CT", 50, enhanced=True)` |
| US 60-frame cine at 60fps | `generate_study("US", 60, enhanced=True, cine_rate=60)` |
| MR axial T1 | `generate_study("MR", 40, orientation="axial", overrides={"ScanningSequence": "SE"})` |
| Chest X-ray (DX) | `generate_study("DX", 1)` |
| Mammogram (MG) | `generate_study("MG", 2)` |

---

## Tips

1. **Always confirm before store** — Claude will show validation results; review them
2. **Reuse UIDs** — Once you store series 1, capture its `study_uid` to attach series 2 to the same study
3. **Check recipes** — `list_recipes()` shows previously-generated patterns; reuse them
4. **Orthanc web UI** — http://localhost:8042 — download, view, or delete studies (useful for testing)
5. **Series vs instances** — "N instances" = one series of N files; "N series" = ask for clarification

---

## Common Issues

| Problem | Fix |
|---|---|
| "Orthanc unreachable" | Check `docker ps` — if orthanc not running, see SETUP.md Part 4 |
| "Cannot attach to study XYZ" | Study not yet stored, or wrong UID — store series 1 first |
| "PR has no instances" | List instances first with `list_series_instances()`, pass exact UIDs |
| "Type 1 tag missing" | Claude will repair automatically; if repair fails, check `overrides` or ask for schema |

---

## Next

- See [solution-design.md](solution-design.md) for how this all works under the hood
- See [SETUP.md](SETUP.md) if you need to troubleshoot environment
- See [sample-prompts.md](sample-prompts.md) for more advanced examples
