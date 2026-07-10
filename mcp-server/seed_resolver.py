"""Seed resolution — PACS-first, template-fallback (solution-design.md §3).

resolve_seed is the single decision point consulted before any data is
generated: it checks the PACS for existing similar data first, and only
reports the bundled template seed as a fallback candidate requiring
explicit user confirmation.
"""

import orthanc_client
import templates as template_catalog


def resolve_seed(modality: str, body_part: str | None = None, orientation: str | None = None) -> dict:
    modality = modality.upper()

    try:
        pacs_candidates = orthanc_client.find_studies(modality=modality)
    except Exception as exc:
        pacs_candidates = []
        pacs_error = str(exc)
    else:
        pacs_error = None

    if body_part:
        pacs_candidates = [c for c in pacs_candidates if body_part.upper() in (c.get("description") or "").upper()]
    if orientation:
        pacs_candidates = [c for c in pacs_candidates if orientation.lower() in (c.get("description") or "").lower()]

    if pacs_candidates:
        return {
            "source_type": "pacs",
            "candidates": pacs_candidates[:5],
            "requires_confirmation": len(pacs_candidates) > 1,
        }

    matching_templates = template_catalog.list_templates(modality=modality, body_part=body_part, orientation=orientation)
    template_with_seed = next((t for t in matching_templates if t.get("has_seed_data")), None)

    if template_with_seed:
        return {
            "source_type": "template",
            "template_id": template_with_seed["template_id"],
            "requires_confirmation": True,
            "message": (
                f"No similar {modality} data found in the PACS"
                + (f" for body_part={body_part}" if body_part else "")
                + (f" orientation={orientation}" if orientation else "")
                + f". Use the built-in '{template_with_seed['template_id']}' template seed instead?"
            ),
        }

    closest = template_catalog.list_templates(modality=modality)
    return {
        "source_type": "none",
        "requires_confirmation": False,
        "closest_alternatives": closest,
        "pacs_error": pacs_error,
        "message": f"No PACS data or template seed found for modality={modality}.",
    }
