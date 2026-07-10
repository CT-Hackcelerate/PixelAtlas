"""Tag template catalog + manifest loading (filesystem-backed, no PACS calls).

Reads templates/catalog.yaml and templates/<path>/manifest.yaml per
solution-design.md §6. Loaded fresh on each call for now (v1 has no
hot-reload requirement beyond "not stale on server restart").
"""

from pathlib import Path

import yaml

import config
import override_policy


def _catalog_path() -> Path:
    return config.TEMPLATES_DIR / "catalog.yaml"


def load_catalog() -> list[dict]:
    path = _catalog_path()
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("templates", [])


def list_templates(modality: str | None = None, body_part: str | None = None, orientation: str | None = None) -> list[dict]:
    """body_part/orientation are used to narrow among templates that declare
    a specific value; a template with an empty body_part/orientation is a
    generic IOD-level template (e.g. ct-image) and matches any requested
    value rather than being excluded by it."""
    entries = load_catalog()
    if modality:
        entries = [e for e in entries if e.get("modality", "").upper() == modality.upper()]
    if body_part:
        entries = [e for e in entries if not e.get("body_part") or e.get("body_part", "").upper() == body_part.upper()]
    if orientation:
        entries = [e for e in entries if not e.get("orientation") or e.get("orientation", "").lower() == orientation.lower()]
    return entries


def find_catalog_entry(template_id: str) -> dict | None:
    for entry in load_catalog():
        if entry.get("template_id") == template_id:
            return entry
    return None


def load_manifest(template_id: str) -> dict | None:
    entry = find_catalog_entry(template_id)
    if entry is None:
        return None
    manifest_path = config.TEMPLATES_DIR / entry["path"] / "manifest.yaml"
    if not manifest_path.exists():
        return None
    with open(manifest_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_template_info(template_id: str) -> dict | None:
    """Tag rules + protected tags only — no seed/pixel data. protected_tags
    are the only tags NOT safe to pass as an override to generate_dataset:
    anything else valid for this template's IOD (see get_iod_requirements) is
    fair game."""
    manifest = load_manifest(template_id)
    if manifest is None:
        return None
    tag_rules = manifest.get("tag_rules", {})
    return {
        "template_id": manifest["template_id"],
        "modality": manifest["modality"],
        "body_part": manifest.get("body_part"),
        "orientation": manifest.get("orientation"),
        "sop_class_uid": manifest.get("sop_class_uid"),
        "has_seed_data": manifest.get("has_seed_data", False),
        "tag_rules": tag_rules,
        "protected_tags": sorted(override_policy.protected_tags_for(tag_rules)),
        "required_for_validation": manifest.get("required_for_validation", []),
    }
