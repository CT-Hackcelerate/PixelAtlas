---
description: Validate a folder of generated DICOM instances, or a study already in the PACS
mode: agent
tools: ["pixel-atlas/validate_dataset"]
---

# /validate path=<folder> | study=<StudyInstanceUID>

Give exactly one target:

- `path=<folder>` — typically a prior `/generate` or `/modify` job's
  `output_path`. Call `validate_dataset(path=<folder>)` directly.
- `study=<StudyInstanceUID>` — a study already stored in the PACS.
  Call `validate_dataset(study_uid=<uid>)`; the tool fetches every instance
  into a throwaway folder before running the same checks, so this can take a
  few seconds longer than the `path=` form.

This is a standalone diagnostic command, not part of a generate/modify
pipeline — unlike `/generate`'s compact summary, report the **full** report
back to the user: `passed`, `checked_instances`, `sampling_ratio`,
`iod_conformance` (`files_with_errors` and any `example_errors`), the
`dcmftest` summary, and the `errors`/`warnings` lists. If neither `path` nor
`study` was given, or the target doesn't resolve, relay the tool's error
message plainly rather than guessing what the user meant.
