"""Read-only access to the committed IOD knowledge base (templates/<MODALITY>/<template_id>/iod_spec.yaml).

Pure YAML reader — no dicom-validator import here or anywhere else in the
server's runtime path. iod_spec.yaml files are static, human-reviewed
artifacts produced once by scripts/generate_iod_spec.py; this module just
loads and queries them, the same way templates.py loads manifest.yaml.
"""

from pathlib import Path

import yaml

import config
import templates as template_catalog


def _iod_spec_path(entry: dict) -> Path:
    return config.TEMPLATES_DIR / entry["path"] / "iod_spec.yaml"


def _find_entry_by_sop_class_uid(sop_class_uid: str) -> dict | None:
    for entry in template_catalog.load_catalog():
        if entry.get("sop_class_uid") == sop_class_uid:
            return entry
        # catalog entries don't carry sop_class_uid themselves (that's in the
        # manifest) — fall back to reading each manifest until one matches.
        manifest = template_catalog.load_manifest(entry.get("template_id", ""))
        if manifest and manifest.get("sop_class_uid") == sop_class_uid:
            return entry
    return None


def load_iod_spec(template_id: str | None = None, sop_class_uid: str | None = None) -> dict | None:
    """Load the committed iod_spec.yaml for a template_id or a SOP Class UID.

    Returns None if neither is given, or no template covers that SOP Class —
    callers treat that the same as "no knowledge base entry available" (e.g.
    an existing PACS study whose IOD nobody has authored a template for yet).
    """
    entry = None
    if template_id:
        entry = template_catalog.find_catalog_entry(template_id)
    elif sop_class_uid:
        entry = _find_entry_by_sop_class_uid(sop_class_uid)
    if entry is None:
        return None

    spec_path = _iod_spec_path(entry)
    if not spec_path.exists():
        return None
    with open(spec_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def all_tags(spec: dict) -> list[dict]:
    """Flatten every tag across every module that has tag-level detail
    (mandatory/conditional/user-optional — see generate_iod_spec.py). Includes
    tags from conditional (usage "C") and user-optional (usage "U") modules —
    they're legitimate tags for this IOD even when the module itself doesn't
    always (or ever) have to be present, which is what matters for "is this a
    real tag for this IOD" checks (e.g. modify.py)."""
    return [tag for module in spec.get("modules", []) for tag in module.get("tags", [])]


def mandatory_tags(spec: dict) -> list[dict]:
    """Type 1/Type 2 tags from unconditionally mandatory (usage "M") modules
    only. Deliberately excludes conditional (usage "C") modules' tags — a
    Type 1 tag inside e.g. the CT "Multi-energy CT Image" module is only
    required if that module applies at all (module condition), which isn't
    safe to evaluate generically. Used by generator.py's fill-in-the-blanks
    safety net, where a false positive would block generation entirely."""
    return [
        tag
        for module in spec.get("modules", [])
        if module.get("usage") == "M"
        for tag in module.get("tags", [])
        if tag.get("type") in ("1", "2")
    ]
