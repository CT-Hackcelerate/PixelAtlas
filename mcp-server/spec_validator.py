"""validate_spec — deterministic grounding of a Generation Spec against the KB
*before* the expensive materialization.

Checks (see docs/solution-design.md §8):
  - SOP Class is known and in the supported family.
  - every attribute is a real DICOM keyword (error) and valid for the IOD (warning).
  - pixel-module tags and protected UID tags are not pinned in `attributes` (error).
  - every value is VR-correct (error) — checked on a scratch dataset.
  - curated cross-tag "make sense together" rules (error/warning):
      * pixel directive internal consistency
      * Modality <-> SOPClass
      * geometry triplet completeness
On success, stores the spec and returns a spec_id (the token-saving handle).
"""

import pydicom

import iod_lookup as kb
import spec_store
from dicom_apply import apply_value_map
from spec_store import SpecError

_ALLOWED_GENERATORS = {"noise", "gradient", "phantom"}


def _resolve_sop_class(spec: dict) -> str | None:
    seed = (spec.get("request") or {}).get("seedSource") or {}
    if seed.get("sopClassUID"):
        return seed["sopClassUID"]
    attrs = spec.get("attributes") or {}
    if attrs.get("SOPClassUID"):
        return attrs["SOPClassUID"]
    return kb.resolve_sop_class(modality=(spec.get("request") or {}).get("modality"))


def _check_pixel_directive(pixel: dict, errors: list):
    spp = pixel.get("samplesPerPixel", 1)
    photo = pixel.get("photometricInterpretation", "MONOCHROME2")
    ba = pixel.get("bitsAllocated", 16)
    bs = pixel.get("bitsStored", 12 if ba == 16 else ba)
    if spp == 1 and photo not in ("MONOCHROME1", "MONOCHROME2", "PALETTE COLOR"):
        errors.append({"tag": "pixel", "reason": f"SamplesPerPixel=1 is incompatible with PhotometricInterpretation={photo}"})
    if spp == 3 and photo not in ("RGB", "YBR_FULL", "YBR_FULL_422"):
        errors.append({"tag": "pixel", "reason": f"SamplesPerPixel=3 requires an RGB/YBR PhotometricInterpretation, not {photo}"})
    if not (ba >= bs > 0):
        errors.append({"tag": "pixel", "reason": f"BitsAllocated({ba}) >= BitsStored({bs}) > 0 must hold"})
    if pixel.get("generator", "noise") not in _ALLOWED_GENERATORS:
        errors.append({"tag": "pixel", "reason": f"generator must be one of {sorted(_ALLOWED_GENERATORS)}"})


def validate_spec(spec: dict) -> dict:
    errors: list[dict] = []
    warnings: list[dict] = []

    sop_class = _resolve_sop_class(spec)
    if not sop_class:
        return {"grounded": False, "errors": [{"tag": "request", "reason": "could not resolve a SOP Class from modality/seedSource/SOPClassUID"}], "warnings": []}
    if not kb.is_supported(sop_class):
        return {"grounded": False, "errors": [{"tag": "SOPClassUID", "reason": f"SOP Class {sop_class} is outside the supported family (image IODs + PR/KO). Refuse this request."}], "warnings": []}

    req = kb.requirements(sop_class)
    if req is None:
        return {"grounded": False, "errors": [{"tag": "SOPClassUID", "reason": f"SOP Class {sop_class} is not in the knowledge base"}], "warnings": []}
    valid_kw = kb.valid_keywords(sop_class)

    attributes = spec.get("attributes") or {}

    # per-attribute checks
    for keyword in attributes:
        if keyword in kb.PIXEL_MODULE_KEYWORDS:
            errors.append({"tag": keyword, "reason": "pixel-module tag is Materializer-owned; put it in the `pixel` directive, not `attributes`"})
            continue
        if keyword in kb.PROTECTED_UID_KEYWORDS:
            errors.append({"tag": keyword, "reason": "UID/SOPClass tag is managed automatically; do not set it in `attributes`"})
            continue
        if kb.describe(keyword) is None:
            errors.append({"tag": keyword, "reason": "not a recognized DICOM tag/keyword"})
            continue
        if keyword not in valid_kw:
            warnings.append({"tag": keyword, "reason": f"not listed for this IOD ({req['title']}); allowed but double-check"})

    # VR value check on a scratch dataset (reuses strict validation)
    try:
        apply_value_map(pydicom.Dataset(), {k: v for k, v in attributes.items()
                                            if k not in kb.PIXEL_MODULE_KEYWORDS and k not in kb.PROTECTED_UID_KEYWORDS and kb.describe(k)})
    except SpecError as exc:
        errors.append({"tag": "value", "reason": str(exc)})

    # cross-tag rules
    if not kb.is_reference_object(sop_class):
        _check_pixel_directive(spec.get("pixel") or {}, errors)

    declared_modality = attributes.get("Modality") or (spec.get("request") or {}).get("modality")
    expected_modality = kb.modality_for_sop_class(sop_class)
    if declared_modality and expected_modality and str(declared_modality).upper() != expected_modality:
        errors.append({"tag": "Modality", "reason": f"Modality={declared_modality} disagrees with SOP Class {sop_class} (expected {expected_modality})"})

    # geometry triplet completeness (warning)
    per_instance = spec.get("perInstance") or {}
    geo_present = {g for g in ("ImageOrientationPatient", "ImagePositionPatient", "PixelSpacing")
                  if g in attributes or g in per_instance}
    if geo_present and not kb.is_reference_object(sop_class):
        missing = {"ImageOrientationPatient", "PixelSpacing"} - set(attributes) - set(per_instance)
        if missing and geo_present:
            warnings.append({"tag": "geometry", "reason": f"partial geometry: consider also setting {sorted(missing)} for a valid frame of reference"})

    grounded = len(errors) == 0
    result = {"grounded": grounded, "errors": errors, "warnings": warnings, "sop_class_uid": sop_class}
    if grounded:
        # stamp the resolved SOP class + KB edition into the spec before storing
        spec.setdefault("request", {}).setdefault("seedSource", {}).setdefault("sopClassUID", sop_class)
        spec.setdefault("provenance", {})["kbEdition"] = kb.kb_edition()
        result["spec_id"] = spec_store.store(spec)
    return result
