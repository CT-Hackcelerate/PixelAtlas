---
description: Check whether the PACS already has data with a given DICOM tag/value
mode: agent
tools: ["pixel-atlas/check_pacs_feature"]
---

# /check-feature tag=<keyword|GGGG,EEEE> [value=] [modality=] [date_range=]

Generic lookup — not specific to any one tag/feature. There is **no**
natural-language-to-tag mapping in the tool itself: you must resolve the
user's phrase to the correct DICOM keyword (or `GGGG,EEEE` hex tag) yourself
before calling it. If you're genuinely unsure which tag the user means, or
the phrase could plausibly map to more than one distinct tag, ask — do not
guess silently, and do not substitute a different, unrelated tag just
because it's a familiar or recently-mentioned one (e.g. "Modality LUT" is
`ModalityLUTSequence`, `0028,3000` — it is a different, unrelated tag from
`RescaleSlope`/`RescaleIntercept`, not a stand-in for it). Do not call any
other tool (e.g. `get_job_status`, `list_pacs_studies`) first or instead.
This is a single, direct call:

1. Resolve the user's phrase to a DICOM tag keyword or hex tag.
2. Call `check_pacs_feature(tag, value?, modality?, date_range?)` directly —
   nothing needs to happen before this call. If the tool returns an
   `{"error": ...}` (e.g. an unrecognized tag), relay that error message
   plainly; do not retry the same call expecting a different result, and do
   not fall back to unrelated tools to "figure it out" a different way.
3. Report `match_count`, the matched studies (up to the 20 returned), and
   whether the candidate list was `truncated`. If `match_count` is 0, say so
   plainly rather than treating it as an error.
4. Note the scope limits when relevant: this checks one representative
   instance per candidate study (not every instance), and only tag
   presence/direct value — not values nested inside a sequence's items.
