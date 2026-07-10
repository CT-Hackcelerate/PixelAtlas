"""One-time authoring tool: dump a DICOM IOD's module/tag requirements from
dicom-validator's own standard-derived data into a static, committed
templates/<MODALITY>/<template_id>/iod_spec.yaml.

This is the only place in the codebase that reads dicom-validator's DicomInfo
internals for template knowledge — the MCP server's runtime code (iod_lookup.py,
generator.py, modify.py) only ever reads the committed YAML this script
produces, never dicom-validator directly. Mirrors generate_seed.py's existing
pattern: run manually, review the output, commit it.

Usage (from repo root):
    python scripts/generate_iod_spec.py <sop_class_uid> <output_path>

Example:
    python scripts/generate_iod_spec.py 1.2.840.10008.5.1.4.1.1.2 templates/CT/ct-image/iod_spec.yaml
"""

import sys
from pathlib import Path

import yaml
from pydicom.datadict import keyword_for_tag
from pydicom.tag import Tag

sys.path.insert(0, str(Path(__file__).parent.parent / "mcp-server"))

import config  # noqa: E402
from dicom_validator.spec_reader.edition_reader import EditionReader  # noqa: E402


def _load_dicom_info():
    edition_reader = EditionReader(str(config.DICOM_VALIDATOR_STANDARD_PATH))
    edition = edition_reader.get_edition("current")
    edition_reader.get_edition_path(edition, False)
    return edition_reader.load_dicom_info(edition)


def _tag_to_int(tag_str: str) -> int:
    group, element = tag_str.strip("()").split(",")
    return Tag(int(group, 16), int(element, 16))


def _build_tag_entry(tag_str: str, tag_def: dict, dictionary: dict) -> dict:
    dict_entry = dictionary.get(tag_str, {})
    try:
        keyword = keyword_for_tag(_tag_to_int(tag_str)) or None
    except Exception:
        keyword = None
    entry = {
        "tag": tag_str,
        "keyword": keyword,
        "name": tag_def.get("name"),
        "type": tag_def.get("type"),
        "vr": dict_entry.get("vr"),
        "vm": dict_entry.get("vm"),
    }
    cond = tag_def.get("cond")
    if cond:
        entry["condition_rule"] = cond
        descr = cond.get("descr") if isinstance(cond, dict) else str(cond)
        if descr:
            entry["condition"] = descr
    return entry


def build_iod_spec(sop_class_uid: str) -> dict:
    info = _load_dicom_info()
    iod = info.iods.get(sop_class_uid)
    if iod is None:
        raise ValueError(f"No IOD found for SOP Class UID '{sop_class_uid}' in this DICOM edition")

    modules_out = []
    for module_name, module_def in sorted(iod["modules"].items()):
        usage_raw = module_def.get("use", "U")
        usage = usage_raw[0] if usage_raw else "U"  # "M" / "C - ..." / "U" -> first letter
        module_entry = {
            "module": module_name,
            "ref": module_def.get("ref"),
            "usage": usage,
        }
        if usage == "C":
            module_entry["condition"] = usage_raw
        module_cond = module_def.get("cond")
        if module_cond and module_cond != {"type": "U"}:
            module_entry["condition_rule"] = module_cond

        if usage in ("M", "C", "U"):
            module_tags = info.modules.get(module_def.get("ref"), {})
            module_entry["tags"] = [
                _build_tag_entry(tag_str, tag_def, info.dictionary)
                for tag_str, tag_def in sorted(module_tags.items())
                if isinstance(tag_def, dict) and tag_str.startswith("(")
            ]

        modules_out.append(module_entry)

    return {
        "sop_class_uid": sop_class_uid,
        "iod_title": iod.get("title"),
        "modules": modules_out,
    }


def main() -> None:
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)

    sop_class_uid, output_path = sys.argv[1], Path(sys.argv[2])
    spec = build_iod_spec(sop_class_uid)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(spec, f, sort_keys=False, allow_unicode=True, width=100)
    print(f"Wrote IOD spec for '{spec['iod_title']}' ({sop_class_uid}) to {output_path}")


if __name__ == "__main__":
    main()
