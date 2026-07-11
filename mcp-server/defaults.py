"""Server-side baseline Generation Specs + required-tag autofill.

This is what makes `generate_study` a one-shot call: the server builds a
conformant baseline spec from sensible per-modality defaults (no AI authoring, no
giant IOD dumps), the caller only supplies modality/count/overrides. Any mandatory
Type-1 tag the baseline misses is autofilled with a VR/enum-appropriate placeholder
so the result is conformant for *any* supported modality — synthetic test data, so
placeholder values are acceptable.
"""

import iod_lookup as kb

# Curated per-modality attribute defaults (verified conformant). Everything else
# falls back to the generic baseline + autofill.
_MODALITY_ATTRS = {
    "CT": {
        "ImageType": ["ORIGINAL", "PRIMARY", "AXIAL"], "KVP": "120",
        "AcquisitionNumber": "1", "PatientPosition": "HFS",
    },
    "MR": {
        "ImageType": ["ORIGINAL", "PRIMARY", "M", "NORM"], "PatientPosition": "HFS",
        "ScanningSequence": "SE", "SequenceVariant": "NONE", "ScanOptions": "",
        "MRAcquisitionType": "2D", "EchoTime": "10", "RepetitionTime": "500",
        "EchoTrainLength": "1",
    },
    "US": {"ImageType": ["ORIGINAL", "PRIMARY", "", ""]},
    "PT": {"ImageType": ["ORIGINAL", "PRIMARY"], "PatientPosition": "HFS"},
}
# Modalities whose slices carry a per-instance geometry progression.
_CROSS_SECTIONAL = {"CT", "MR", "PT"}

# Per-modality pixel directive (single-frame + classic MF). US default mono for
# simplicity; override to RGB if desired.
_MODALITY_PIXEL = {
    "US": {"rows": 128, "columns": 128, "samplesPerPixel": 1,
           "photometricInterpretation": "MONOCHROME2", "bitsAllocated": 8, "generator": "phantom"},
}
_DEFAULT_PIXEL = {"rows": 128, "columns": 128, "samplesPerPixel": 1,
                  "photometricInterpretation": "MONOCHROME2", "bitsAllocated": 16, "generator": "phantom"}

# VR → placeholder value for autofilled Type-1 tags. Single source of truth
# lives in iod_lookup.py (shared with the KB's generic macro-skeleton builder).
_VR_PLACEHOLDER = kb.VR_PLACEHOLDER
# VRs we must NOT blindly autofill (managed elsewhere or need real content).
_SKIP_AUTOFILL_VR = {"UI", "SQ", "AT", "OB", "OW", "OF", "UN"}


def baseline_spec(modality: str, count: int, body_part: str | None = None,
                  orientation: str | None = None, enhanced: bool = False,
                  overrides: dict | None = None, study_uid: str | None = None) -> dict:
    modality = modality.upper()
    sop_class = kb.resolve_sop_class(modality=modality, enhanced=enhanced)
    attrs = dict(_MODALITY_ATTRS.get(modality, {"ImageType": ["DERIVED", "SECONDARY"]}))
    attrs["Modality"] = modality
    # Enhanced (functional-group) IODs must use a DERIVED ImageType, else the
    # acquisition-specific conditional macros become mandatory.
    if kb.multiframe_kind(sop_class) == "enhanced":
        attrs["ImageType"] = ["DERIVED", "PRIMARY", "VOLUME", "NONE"]
    if body_part:
        attrs["BodyPartExamined"] = body_part.upper()
    attrs.setdefault("Manufacturer", "Pixel Atlas Synthetic")

    per_instance = {"InstanceNumber": {"rule": "index+1"}}
    # Enhanced (functional-group) IODs carry geometry inside the Shared/Per-Frame
    # Functional Groups instead (materializer builds those separately) — setting
    # these at the dataset root there is a validator "TagUnexpected", not a fill.
    if modality in _CROSS_SECTIONAL and kb.multiframe_kind(sop_class) != "enhanced":
        attrs.setdefault("ImageOrientationPatient", ["1", "0", "0", "0", "1", "0"])
        attrs.setdefault("PixelSpacing", ["0.7", "0.7"])
        attrs.setdefault("SliceThickness", "1.5")
        per_instance["SliceLocation"] = {"rule": "linspace", "start": -120.0, "step": 1.5}
        per_instance["ImagePositionPatient"] = {"rule": "derive_from_slice"}

    spec = {
        "pixelAtlasSpec": "1.0",
        "request": {"prompt": f"generate {count} {modality}", "modality": modality,
                    "instanceCount": count, "bodyPart": body_part, "orientation": orientation,
                    "seedSource": {"type": "iod", "sopClassUID": sop_class}},
        "attributes": attrs,
        "perInstance": per_instance,
        "pixel": dict(_MODALITY_PIXEL.get(modality, _DEFAULT_PIXEL)),
        "identity": {"mode": "synthetic"},
        "provenance": {"grounded": False, "specSource": "generate_study", "authoredBy": "server-defaults"},
    }
    if orientation:
        spec["request"]["orientation"] = orientation
    if study_uid:
        spec["request"]["attachStudyUID"] = study_uid
    if overrides:
        spec["overrides"] = dict(overrides)
    return spec


def autofill_required(spec: dict) -> list[str]:
    """Add VR/enum-appropriate placeholders for mandatory Type-1 tags the baseline
    doesn't already set (skipping pixel-module/UID/sequence tags). Returns the list
    of tags it could NOT autofill (sequence Type-1 etc.) so the caller can report a
    precise error instead of looping. Mutates spec['attributes']."""
    sop_class = (spec.get("request") or {}).get("seedSource", {}).get("sopClassUID")
    if not sop_class:
        return []
    attrs = spec.setdefault("attributes", {})
    overrides = spec.get("overrides") or {}
    per_instance = spec.get("perInstance") or {}
    present = set(attrs) | set(overrides) | set(per_instance)
    pixel = spec.get("pixel") or {}
    # What mandatory_tags' condition evaluator can already resolve at this
    # point — closes gaps like Enhanced MR's Complex Image Component, which
    # conditions on SOPClassUID only (see iod_lookup._cond_holds).
    context = {**attrs, **overrides}
    if pixel.get("photometricInterpretation"):
        context["PhotometricInterpretation"] = pixel["photometricInterpretation"]
    if pixel.get("samplesPerPixel"):
        context["SamplesPerPixel"] = str(pixel["samplesPerPixel"])
    unfilled = []
    for tag in kb.mandatory_tags(sop_class, context=context):
        kw, vr = tag["keyword"], tag.get("vr")
        if tag["type"] not in ("1", "1C") or not kw or kw in kb.PIXEL_MODULE_KEYWORDS or kw in kb.PROTECTED_UID_KEYWORDS:
            continue
        if kw in present:
            continue
        if tag.get("enums"):
            first = tag["enums"][0]
            attrs[kw] = first[0] if isinstance(first, list) and first else first
        elif vr in _SKIP_AUTOFILL_VR or vr not in _VR_PLACEHOLDER:
            unfilled.append(f"{kw} ({vr})")
        else:
            attrs[kw] = _VR_PLACEHOLDER[vr]
    return unfilled


def fill_missing_tags(spec: dict, missing: list) -> int:
    """Probe-guided repair: given the validator's (module, tag_id, code) list, add a
    conformant placeholder for each TOP-LEVEL missing tag (skip nested
    'seqA / tagB' functional-group items). Type-2/2C sequences → empty; scalars →
    VR/enum placeholder. Returns how many it filled. Mutates spec['attributes']."""
    attrs = spec.setdefault("attributes", {})
    sop_class = (spec.get("request") or {}).get("seedSource", {}).get("sopClassUID")
    enum_by_kw, type_by_kw = {}, {}
    if sop_class:
        req = kb.requirements(sop_class)
        if req:
            for m in req["modules"]:
                for t in m["tags"]:
                    if t["keyword"]:
                        type_by_kw[t["keyword"]] = t.get("type", "")
                        if t.get("enums"):
                            enum_by_kw[t["keyword"]] = t["enums"]
    placeholder_code = [{"CodeValue": "UNKNOWN", "CodingSchemeDesignator": "99PXA", "CodeMeaning": "Unknown"}]
    filled = 0
    for module, tag_id, code in missing:
        if "/" in tag_id or code not in ("TagMissing", "TagEmpty"):
            continue  # nested functional-group item, or a non-fillable problem
        desc = kb.describe(tag_id)
        if not desc or not desc.get("keyword"):
            continue
        kw, vr = desc["keyword"], desc.get("vr")
        if kw in kb.PIXEL_MODULE_KEYWORDS or kw in kb.PROTECTED_UID_KEYWORDS:
            continue
        # re-fill only if absent or empty (TagEmpty case)
        if kw in attrs and attrs[kw] not in ([], "", None):
            continue
        is_type1 = type_by_kw.get(kw, "").startswith("1")
        if kw in enum_by_kw:
            first = enum_by_kw[kw][0]
            attrs[kw] = first[0] if isinstance(first, list) and first else first
        elif vr == "SQ":
            # Type-1 sequences need content (usually a code item); Type-2 can be empty.
            attrs[kw] = placeholder_code if is_type1 else []
        elif vr in _VR_PLACEHOLDER:
            attrs[kw] = _VR_PLACEHOLDER[vr]
        else:
            continue
        filled += 1
    return filled
