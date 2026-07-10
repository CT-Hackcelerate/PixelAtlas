"""check_pacs_feature — generic DICOM tag presence/value lookup against the PACS.

New scope beyond solution-design.md (Phase 3): "do we have any axial study" or
"do we have any study with a Modality LUT" turned out to be two instances of
the same underlying need — checking whether some tag is present (optionally
with a specific value) on data already in the PACS. Rather than hardcoding
per-feature logic, this is one generic lookup keyed by DICOM tag; the model
is expected to resolve the user's natural-language phrase to the correct
DICOM keyword itself (it already knows DICOM) before calling this tool.

Scope: presence/value-equality checks on tags visible directly on one
representative instance per candidate study — including sequence tags (their
key is present with a non-null value even though we don't inspect inside the
sequence). Matching a value *inside* a sequence's items (e.g. a specific LUT
Descriptor) is out of scope for this pass.

Not indexed: unlike modality/date (Orthanc's MainDicomTags), arbitrary tags
require fetching each candidate study's tags one at a time — there is no fast
index for this. Always narrow with modality/date_range on a large PACS.
"""

from pydicom.datadict import dictionary_keyword, tag_for_keyword

import orthanc_client

DEFAULT_MAX_STUDIES = 200


class FeatureLookupError(ValueError):
    """Raised when the requested tag can't be resolved to a known DICOM keyword."""


def _normalize_tag_keyword(tag: str) -> str:
    """Accept a DICOM keyword (e.g. 'RescaleSlope') or a 'GGGG,EEEE' tag; return
    the canonical keyword used as the key in Orthanc's simplified tag JSON."""
    tag = tag.strip()
    if "," in tag:
        cleaned = tag.replace("(", "").replace(")", "")
        try:
            group_str, elem_str = cleaned.split(",")
            tag_int = (int(group_str, 16) << 16) | int(elem_str, 16)
        except ValueError as exc:
            raise FeatureLookupError(f"'{tag}' is not a valid DICOM tag (expected a keyword or 'GGGG,EEEE')") from exc
        keyword = dictionary_keyword(tag_int)
        if not keyword:
            raise FeatureLookupError(f"Unknown DICOM tag '{tag}'")
        return keyword

    if tag_for_keyword(tag) is None:
        raise FeatureLookupError(f"Unknown DICOM tag keyword '{tag}'")
    return tag


def check_pacs_feature(
    tag: str,
    value: str | None = None,
    modality: str | None = None,
    date_range: str | None = None,
    max_studies: int = DEFAULT_MAX_STUDIES,
) -> dict:
    keyword = _normalize_tag_keyword(tag)

    candidates = orthanc_client.find_studies(modality=modality, date_range=date_range)
    truncated = len(candidates) > max_studies
    candidates = candidates[:max_studies]

    checked = 0
    matched = []
    for study in candidates:
        study_uid = study["study_uid"]
        try:
            instance_id = orthanc_client.get_first_instance_id(study_uid)
            instance_tags = orthanc_client.get_instance_tags(instance_id)
        except Exception:
            continue
        checked += 1

        if keyword not in instance_tags or instance_tags[keyword] is None:
            continue
        if value is not None and str(instance_tags[keyword]) != str(value):
            continue

        matched.append(
            {
                "study_uid": study_uid,
                "modality": study.get("modality", ""),
                "date": study.get("date", ""),
                "tag_value": instance_tags[keyword],
            }
        )

    return {
        "tag": keyword,
        "value_filter": value,
        "candidate_studies": len(candidates),
        "checked_studies": checked,
        "truncated": truncated,
        "match_count": len(matched),
        "matched_studies": matched[:20],
    }
