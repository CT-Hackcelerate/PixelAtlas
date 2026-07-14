"""extract_spec — turn an existing PACS study (or local .dcm) into a Generation
Spec so the AI can edit real structure (the PACS-first / modify path).

No PHI scrubbing for now (decision #8): this is a test tool on a test PACS, so
identity is kept as-is. If ever pointed at real PHI, a scrubbing layer must be
added here first.
"""

import io

import pydicom

import iod_lookup as kb
import orthanc_client
from spec_store import SpecError

# Tags we never surface in `attributes` (pixel module is Materializer-owned; UIDs
# and group-length/PixelData are managed automatically).
_SKIP = kb.PIXEL_MODULE_KEYWORDS | kb.PROTECTED_UID_KEYWORDS | {
    "PixelData", "FloatPixelData", "DoubleFloatPixelData",
    "SharedFunctionalGroupsSequence", "PerFrameFunctionalGroupsSequence",
}


def _jsonable(value):
    """Convert a pydicom element value into a JSON-serializable form the spec/
    materializer round-trip: sequences -> list of {keyword: value} dicts."""
    if isinstance(value, pydicom.Sequence):
        out = []
        for item in value:
            d = {}
            for elem in item:
                if elem.keyword and elem.keyword not in _SKIP:
                    d[elem.keyword] = _jsonable(elem.value)
            out.append(d)
        return out
    if isinstance(value, pydicom.multival.MultiValue):
        return [str(v) for v in value]
    if isinstance(value, (bytes, bytearray)):
        return None
    return str(value)


def _dataset_to_attributes(ds: pydicom.Dataset) -> dict:
    attrs = {}
    for elem in ds:
        kw = elem.keyword
        if not kw or kw in _SKIP or elem.VR == "OB" or elem.VR == "OW":
            continue
        val = _jsonable(elem.value)
        if val is not None:
            attrs[kw] = val
    return attrs


def _pixel_directive(ds: pydicom.Dataset) -> dict:
    return {
        "rows": int(getattr(ds, "Rows", 64)),
        "columns": int(getattr(ds, "Columns", 64)),
        "samplesPerPixel": int(getattr(ds, "SamplesPerPixel", 1)),
        "photometricInterpretation": str(getattr(ds, "PhotometricInterpretation", "MONOCHROME2")),
        "bitsAllocated": int(getattr(ds, "BitsAllocated", 16)),
        "generator": "noise",
    }


def extract_spec(study_uid: str | None = None, path: str | None = None) -> dict:
    if study_uid:
        instance_ids = orthanc_client.list_instance_ids(study_uid)
        if not instance_ids:
            raise SpecError(f"Study '{study_uid}' has no instances in the PACS")
        # extract_spec builds a spec from ONE representative instance (+ a single
        # merged slice geometry) — structurally single-series. A genuinely
        # multi-series source (a multi-series CT/MR, or a US study with several
        # multi-frame instances, each its own series) would silently interleave
        # unrelated series' geometry into one nonsensical range, or collapse a
        # source series count into an unrelated frame count. Refuse loud instead:
        # /modify and generate_prior_study already replicate every series faithfully.
        series_uids = {inst["series_uid"] for inst in orthanc_client.list_series_instances(study_uid)}
        if len(series_uids) > 1:
            raise SpecError(
                f"Study '{study_uid}' has {len(series_uids)} series — extract_spec only "
                "supports single-series sources (it builds a spec from one representative "
                "instance). Use modify_dataset to edit tags, or generate_prior_study for a "
                "prior — both replicate every series of the source study faithfully."
            )
        ds = pydicom.dcmread(io.BytesIO(orthanc_client.fetch_instance_bytes(instance_ids[0])))
        count = len(instance_ids)
        seed = {"type": "pacs", "studyUID": study_uid}
        if count > 1:
            geometry = orthanc_client.list_instance_geometry(study_uid)
            if len(geometry) > 1:
                locations = [g["slice_location"] for g in geometry]
                seed["sliceRange"] = {"start": locations[0], "end": locations[-1], "count": len(locations)}
    elif path:
        ds = pydicom.dcmread(path)
        count = 1
        seed = {"type": "pacs", "path": path}
    else:
        raise SpecError("extract_spec requires study_uid or path")

    sop_class = str(getattr(ds, "SOPClassUID", ""))
    seed["sopClassUID"] = sop_class
    modality = str(getattr(ds, "Modality", "")) or kb.modality_for_sop_class(sop_class)

    return {
        "pixelAtlasSpec": "1.0",
        "request": {"prompt": "extracted from existing study", "modality": modality,
                    "instanceCount": count, "seedSource": seed},
        "attributes": _dataset_to_attributes(ds),
        "pixel": _pixel_directive(ds),
        "provenance": {"grounded": False, "specSource": "pacs-extract", "sopClassSupported": kb.is_supported(sop_class)},
    }
