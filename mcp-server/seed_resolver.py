"""Seed resolution — PACS-first, KB fallback (AI-driven redesign).

Two outcomes only (the old template/none coverage-gap branches are gone — the KB
covers every supported IOD):
  - source_type="pacs": similar data exists in the PACS; the agent should
    extract_spec from a candidate and edit it.
  - source_type="iod": no PACS match; the agent authors a spec from the KB.

Matching stays lightweight (decision): modality queried server-side via Orthanc's
indexed ModalitiesInStudy; body_part/orientation matched as StudyDescription
substrings. No per-instance tag scanning here (that stays in check_pacs_feature).
"""

import iod_lookup as kb
import orthanc_client


def resolve_seed(modality: str, body_part: str | None = None, orientation: str | None = None,
                 enhanced: bool = False) -> dict:
    modality = modality.upper()
    sop_class = kb.resolve_sop_class(modality=modality, enhanced=enhanced)

    if not kb.is_supported(sop_class):
        return {
            "source_type": "unsupported",
            "modality": modality,
            "message": f"Modality '{modality}' has no supported image/PR/KO IOD. Refuse rather than substitute.",
        }

    try:
        candidates = orthanc_client.find_studies(modality=modality)
    except Exception as exc:
        candidates = []
        pacs_error = str(exc)
    else:
        pacs_error = None

    if body_part:
        candidates = [c for c in candidates if body_part.upper() in (c.get("description") or "").upper()]
    if orientation:
        # Soft refinement only: most real StudyDescriptions don't encode orientation
        # at all, so a non-match shouldn't zero out otherwise-good body_part matches.
        oriented = [c for c in candidates if orientation.lower() in (c.get("description") or "").lower()]
        if oriented:
            candidates = oriented

    if candidates:
        return {
            "source_type": "pacs",
            "sop_class_uid": sop_class,
            "candidates": candidates[:5],
            "requires_confirmation": len(candidates) > 1,
            "next_step": "Call extract_spec(study_uid=<chosen>) to seed the order slip from real structure.",
        }

    return {
        "source_type": "iod",
        "sop_class_uid": sop_class,
        "pacs_error": pacs_error,
        "next_step": "No similar PACS data. Call get_iod_requirements(sop_class_uid=...) and author a Generation Spec from the KB.",
    }
