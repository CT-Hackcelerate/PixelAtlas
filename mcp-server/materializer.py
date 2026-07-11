"""materialize_dataset — compile a validated Generation Spec into .dcm files.

Replaces generator.py. Takes a `spec_id` (not the whole spec), builds the base
dataset (synthesized pixels on the IOD path, cloned source on the PACS path),
then:
  - probe-first: fully validate ONE instance before expanding to N (decision #5);
  - single-frame images: N files;
  - multi-frame images: one file, count = frames, functional-group skeleton
    injected from the KB (decision #3/#4);
  - PR/KO: reference-based, no pixels (decision #4).

All in-process with pydicom. Reuses uid_strategy, job_registry, orthanc_client,
seed_builder, and validator (for the probe).
"""

import io
import random
import uuid
from datetime import datetime, timedelta

import pydicom

import config
import iod_lookup as kb
import job_registry
import orthanc_client
import seed_builder
import uid_strategy
import validator
from dicom_apply import apply_value_map
from spec_store import SpecError

SYNTHETIC_NAME_POOL = [
    "DOE^JANE", "DOE^JOHN", "SMITH^ALEX", "PATEL^RIYA", "GARCIA^LUIS",
    "MULLER^ANNA", "NGUYEN^MINH", "KOWALSKI^EWA",
]


# --- per-instance rule evaluation ------------------------------------------
def _eval_rule(keyword: str, rule: dict, i: int, ds: pydicom.Dataset):
    kind = rule.get("rule", "")
    if kind in ("uid", "index+1") or kind.startswith("index"):
        if kind == "uid":
            return None  # UID rules are handled by the UID assignment step
        offset = rule.get("offset", 1 if kind == "index+1" else 0)
        return str(i + offset)
    if kind == "linspace":
        return str(round(rule.get("start", 0.0) + i * rule.get("step", 1.0), 3))
    if kind == "derive_from_slice":
        loc = float(getattr(ds, "SliceLocation", 0.0))
        return [-150.0, -150.0, loc]
    if kind == "const":
        return rule.get("value")
    raise SpecError(f"Unknown perInstance rule '{kind}' for tag '{keyword}'")


def _apply_per_instance(ds: pydicom.Dataset, per_instance: dict, i: int):
    for keyword, rule in (per_instance or {}).items():
        if not isinstance(rule, dict):
            continue
        value = _eval_rule(keyword, rule, i, ds)
        if value is not None:
            apply_value_map(ds, {keyword: value})


def _fill_missing_type2(ds: pydicom.Dataset, mandatory: list[dict]):
    """Fill unconditional Type 2 tags (present, empty allowed) that are still empty.
    Missing Type 1 tags are NOT raised here — the probe's full validate_dataset
    (dicom-validator) is the authority, with precise per-tag messages, and avoids
    false positives from macro-include flattening (e.g. SR content-item macros)."""
    for tag in mandatory:
        kw = tag["keyword"]
        if tag["type"] != "2" or kw in kb.PIXEL_MODULE_KEYWORDS:
            continue
        if getattr(ds, kw, None) in (None, "", []):
            setattr(ds, kw, "")


def _synthetic_identity(rng: random.Random) -> dict:
    return {"PatientName": rng.choice(SYNTHETIC_NAME_POOL), "PatientID": f"SYN{rng.randint(100000, 999999)}"}


def _apply_viewer_safety(ds: pydicom.Dataset, sop_class: str, job_id: str, pixel: dict | None):
    """Set FrameOfReferenceUID (if the IOD needs it) and Rescale/Window defaults so
    synthesized noise renders in a viewer — only for tags valid for this IOD and
    not already set by the AI. Structural/viewer-safety only, not clinical realism."""
    valid = kb.valid_keywords(sop_class)
    if "FrameOfReferenceUID" in valid and not getattr(ds, "FrameOfReferenceUID", None):
        ds.FrameOfReferenceUID = uid_strategy.new_uid(job_id, "for")
    bits_stored = int((pixel or {}).get("bitsStored", 12 if int((pixel or {}).get("bitsAllocated", 16)) == 16 else 8))
    mid = 2 ** (bits_stored - 1)
    defaults = {"RescaleIntercept": "0", "RescaleSlope": "1",
                "WindowCenter": str(mid), "WindowWidth": str(2 ** bits_stored),
                "BurnedInAnnotation": "NO", "LossyImageCompression": "00",
                "PatientPosition": "HFS"}
    for kw, val in defaults.items():
        if kw in valid and getattr(ds, kw, None) in (None, "", []):
            apply_value_map(ds, {kw: val})


def _resolve_same_study_identity(study_uid: str, attributes: dict, overrides: dict) -> dict:
    """Reuse an existing study's identity when a new series is being attached to it
    (spec.request.attachStudyUID) — so both series are unambiguously the same
    patient/study, not just sharing a UID by coincidence. A caller-set PatientID
    (in attributes/overrides) always wins; this never overrides explicit input."""
    if "PatientID" in attributes or "PatientID" in overrides:
        return {}
    try:
        ref = orthanc_client.get_study_details(study_uid)
    except ValueError as exc:
        raise SpecError(
            f"attachStudyUID '{study_uid}' was not found in the PACS — store its "
            "first series before attaching another series to it"
        ) from exc
    if not ref.get("patient_id"):
        raise SpecError(f"Study '{study_uid}' has no PatientID on record — cannot attach a new series to it")
    identity = {"PatientID": ref["patient_id"], "PatientName": ref["patient_name"]}
    for src_key, keyword in (("study_date", "StudyDate"), ("study_description", "StudyDescription"),
                             ("accession_number", "AccessionNumber")):
        if ref.get(src_key):
            identity[keyword] = ref[src_key]
    return identity


def _resolve_identity(spec: dict, attributes: dict, overrides: dict, rng: random.Random) -> dict:
    """Single place that decides where an instance's identity comes from: a prior
    study, an existing study being attached to, the caller's own attributes/
    overrides (left alone), or a fresh synthetic pool. Centralized so no branch
    re-derives or hardcodes this precedence on its own."""
    req = spec.get("request") or {}
    if req.get("priorOfStudyUID"):
        return _resolve_prior_identity(req["priorOfStudyUID"], req.get("daysBefore"))
    if req.get("attachStudyUID"):
        return _resolve_same_study_identity(req["attachStudyUID"], attributes, overrides)
    if "PatientID" not in attributes and "PatientID" not in overrides:
        return _synthetic_identity(rng)
    return {}


def _resolve_prior_identity(prior_of_study_uid: str, days_before: int | None) -> dict:
    if not days_before or days_before <= 0:
        raise SpecError("daysBefore must be a positive integer when priorOfStudyUID is given")
    ref = orthanc_client.get_study_details(prior_of_study_uid)
    if not ref.get("study_date") or not ref.get("patient_id"):
        raise SpecError(f"Reference study '{prior_of_study_uid}' lacks StudyDate/PatientID — cannot make a prior")
    try:
        ref_date = datetime.strptime(ref["study_date"], "%Y%m%d")
    except ValueError as exc:
        raise SpecError(f"Reference study '{prior_of_study_uid}' has an unparseable StudyDate '{ref['study_date']}'") from exc
    return {
        "PatientID": ref["patient_id"],
        "PatientName": ref["patient_name"],
        "StudyDate": (ref_date - timedelta(days=days_before)).strftime("%Y%m%d"),
    }


def _code_item(value, scheme, meaning) -> pydicom.Dataset:
    it = pydicom.Dataset()
    it.CodeValue = value
    it.CodingSchemeDesignator = scheme
    it.CodeMeaning = meaning
    return it


def _referenced_series_sequence(references: dict) -> pydicom.Sequence:
    items = []
    for series in references.get("series", []):
        s = pydicom.Dataset()
        s.SeriesInstanceUID = series["seriesUID"]
        ref_images = []
        for inst in series.get("instances", []):
            ri = pydicom.Dataset()
            ri.ReferencedSOPClassUID = inst["sopClassUID"]
            ri.ReferencedSOPInstanceUID = inst["sopInstanceUID"]
            ref_images.append(ri)
        s.ReferencedImageSequence = pydicom.Sequence(ref_images)
        items.append(s)
    return pydicom.Sequence(items)


# --- branch: single-frame / pacs-seed --------------------------------------
def _materialize_single_frame(spec, sop_class, modality, count, job_id, staging_dir):
    seed = (spec.get("request") or {}).get("seedSource") or {}
    attributes = spec.get("attributes") or {}
    overrides = spec.get("overrides") or {}
    per_instance = spec.get("perInstance") or {}
    rng = random.Random(job_id)

    # identity: synthetic on IOD path unless the AI set it; priors/attach override
    req = spec.get("request") or {}
    identity = _resolve_identity(spec, attributes, overrides, rng)

    # base dataset
    if seed.get("type") == "pacs":
        study_uid = seed.get("studyUID")
        if not study_uid:
            raise SpecError("seedSource.type == 'pacs' requires a studyUID")
        base = pydicom.dcmread(io.BytesIO(orthanc_client.fetch_first_instance_bytes(study_uid)))
    else:
        base = seed_builder.build_base(sop_class, modality, spec.get("pixel"))

    apply_value_map(base, attributes)
    apply_value_map(base, identity)
    apply_value_map(base, overrides)
    if seed.get("type") != "pacs":
        _apply_viewer_safety(base, sop_class, job_id, spec.get("pixel"))

    mandatory = kb.mandatory_tags(sop_class)
    new_study_uid = req.get("attachStudyUID") or uid_strategy.new_uid(job_id, "study")
    new_series_uid = uid_strategy.new_uid(job_id, "series")

    for i in range(count):
        ds = base.copy()
        _apply_per_instance(ds, per_instance, i)
        if "InstanceNumber" not in per_instance:
            ds.InstanceNumber = str(i + 1)
        _fill_missing_type2(ds, mandatory)
        new_sop_uid = uid_strategy.new_uid(job_id, i)
        ds.StudyInstanceUID = new_study_uid
        ds.SeriesInstanceUID = new_series_uid
        ds.SOPInstanceUID = new_sop_uid
        ds.file_meta.MediaStorageSOPInstanceUID = new_sop_uid
        ds.save_as(staging_dir / f"IM{i:04d}.dcm", enforce_file_format=True)

        if i == 0:
            probe = _probe(staging_dir, job_id)
            if probe is not None:
                return probe
        if count >= 20 and i % max(1, count // 10) == 0:
            job_registry.update_job(job_id, progress_pct=int(100 * i / count), message=f"generated {i}/{count}")

    return {"study_uid": new_study_uid, "series_uid": new_series_uid, "count": count}


# --- branch: classic multi-frame (US Multi-frame / XA — Cine + NumberOfFrames) ---
def _materialize_classic_mf(spec, sop_class, modality, frames, job_id, staging_dir):
    attributes = spec.get("attributes") or {}
    overrides = spec.get("overrides") or {}
    cine = spec.get("cine") or {}
    rng = random.Random(job_id)

    ds = seed_builder.build_base(sop_class, modality, spec.get("pixel"), frames=frames)
    apply_value_map(ds, attributes)
    apply_value_map(ds, _resolve_identity(spec, attributes, overrides, rng))
    apply_value_map(ds, overrides)
    _apply_viewer_safety(ds, sop_class, job_id, spec.get("pixel"))

    # Cine + Multi-frame modules (NOT functional groups)
    cine_rate = cine.get("cineRate") or overrides.get("CineRate") or attributes.get("CineRate")
    frame_time = cine.get("frameTime")
    if cine_rate and not frame_time:
        frame_time = round(1000.0 / float(cine_rate), 3)
    ds.FrameTime = str(frame_time if frame_time is not None else 33.3)
    if cine_rate:
        ds.CineRate = str(cine_rate)
    ds.FrameIncrementPointer = 0x00181063  # -> FrameTime
    ds.NumberOfFrames = frames
    ds.InstanceNumber = "1"
    _fill_missing_type2(ds, kb.mandatory_tags(sop_class))

    new_study_uid = (spec.get("request") or {}).get("attachStudyUID") or uid_strategy.new_uid(job_id, "study")
    new_series_uid = uid_strategy.new_uid(job_id, "series")
    new_sop_uid = uid_strategy.new_uid(job_id, 0)
    ds.StudyInstanceUID = new_study_uid
    ds.SeriesInstanceUID = new_series_uid
    ds.SOPInstanceUID = new_sop_uid
    ds.file_meta.MediaStorageSOPInstanceUID = new_sop_uid
    ds.save_as(staging_dir / "IM0000.dcm", enforce_file_format=True)

    probe = _probe(staging_dir, job_id)
    if probe is not None:
        return probe
    return {"study_uid": new_study_uid, "series_uid": new_series_uid, "count": 1, "frames": frames}


# --- branch: enhanced multi-frame (functional groups: Enhanced CT/MR) ---------
def _materialize_enhanced_mf(spec, sop_class, modality, frames, job_id, staging_dir):
    attributes = spec.get("attributes") or {}
    overrides = spec.get("overrides") or {}
    mf = spec.get("multiFrame") or {}
    rng = random.Random(job_id)

    ds = seed_builder.build_base(sop_class, modality, spec.get("pixel"),
                                 frames=frames, include_frame_of_reference=True)
    apply_value_map(ds, attributes)
    apply_value_map(ds, _resolve_identity(spec, attributes, overrides, rng))
    apply_value_map(ds, overrides)
    _apply_viewer_safety(ds, sop_class, job_id, spec.get("pixel"))

    # Shared Functional Groups
    shared_item = pydicom.Dataset()
    shared = mf.get("shared", {})
    pm = shared.get("PixelMeasures", {"PixelSpacing": ["0.7", "0.7"], "SliceThickness": "1.0"})
    pm_ds = pydicom.Dataset(); apply_value_map(pm_ds, pm)
    shared_item.PixelMeasuresSequence = pydicom.Sequence([pm_ds])
    po = shared.get("PlaneOrientation", {"ImageOrientationPatient": ["1", "0", "0", "0", "1", "0"]})
    po_ds = pydicom.Dataset(); apply_value_map(po_ds, po)
    shared_item.PlaneOrientationSequence = pydicom.Sequence([po_ds])
    # CT multi-frame requires two mandatory functional-group macros (the
    # conditional CT Acquisition* macros are skipped by using a DERIVED ImageType).
    if modality == "CT":
        _add_ct_functional_groups(shared_item, ds)
    ds.SharedFunctionalGroupsSequence = pydicom.Sequence([shared_item])

    # Per-Frame Functional Groups
    per_frame_items = []
    for f in range(frames):
        item = pydicom.Dataset()
        pos = pydicom.Dataset()
        pos.ImagePositionPatient = [-150.0, -150.0, round(f * 1.0, 3)]
        item.PlanePositionSequence = pydicom.Sequence([pos])
        fc = pydicom.Dataset()
        fc.DimensionIndexValues = [f + 1]
        item.FrameContentSequence = pydicom.Sequence([fc])
        per_frame_items.append(item)
    ds.PerFrameFunctionalGroupsSequence = pydicom.Sequence(per_frame_items)

    # Minimal Multi-frame Dimension
    dim_org_uid = uid_strategy.new_uid(job_id, "dimorg")
    org = pydicom.Dataset(); org.DimensionOrganizationUID = dim_org_uid
    ds.DimensionOrganizationSequence = pydicom.Sequence([org])
    dim = pydicom.Dataset()
    dim.DimensionOrganizationUID = dim_org_uid
    dim.DimensionIndexPointer = 0x00209157
    dim.FunctionalGroupPointer = 0x00209111
    ds.DimensionIndexSequence = pydicom.Sequence([dim])

    ds.InstanceNumber = "1"
    ds.ContentDate = "20000101"
    ds.ContentTime = "120000"
    _fill_missing_type2(ds, kb.mandatory_tags(sop_class))

    new_study_uid = (spec.get("request") or {}).get("attachStudyUID") or uid_strategy.new_uid(job_id, "study")
    new_series_uid = uid_strategy.new_uid(job_id, "series")
    new_sop_uid = uid_strategy.new_uid(job_id, 0)
    ds.StudyInstanceUID = new_study_uid
    ds.SeriesInstanceUID = new_series_uid
    ds.SOPInstanceUID = new_sop_uid
    ds.file_meta.MediaStorageSOPInstanceUID = new_sop_uid
    ds.save_as(staging_dir / "IM0000.dcm", enforce_file_format=True)

    probe = _probe(staging_dir, job_id)
    if probe is not None:
        return probe
    return {"study_uid": new_study_uid, "series_uid": new_series_uid, "count": 1, "frames": frames}


# --- branch: PR / KO (reference objects) -----------------------------------
def _materialize_reference(spec, sop_class, job_id, staging_dir):
    attributes = spec.get("attributes") or {}
    overrides = spec.get("overrides") or {}
    references = spec.get("references") or {}
    rng = random.Random(job_id)
    if not references.get("series"):
        raise SpecError("PR/KO requires a `references` block naming the studies/series/instances it points at")

    modality = "PR" if sop_class == kb.resolve_sop_class("PR") else "KO"
    ds = seed_builder.build_base(sop_class, modality, None, with_pixels=False)
    apply_value_map(ds, attributes)
    if "PatientID" not in attributes and "PatientID" not in overrides:
        apply_value_map(ds, _synthetic_identity(rng))
    ds.InstanceNumber = "1"
    ds.SeriesNumber = "1"
    ds.ContentDate = "20000101"
    ds.ContentTime = "120000"

    if kb.is_reference_object(sop_class) and modality == "PR":
        ds.ReferencedSeriesSequence = _referenced_series_sequence(references)
        ds.PresentationCreationDate = "20000101"
        ds.PresentationCreationTime = "120000"
        ds.ContentLabel = "PIXELATLAS_PR"
        ds.ContentDescription = "Synthetic presentation state"
        ds.PresentationLUTShape = "IDENTITY"
        # Softcopy VOI LUT (window/level)
        win = (references.get("presentation") or {}).get("window", {"center": 40, "width": 400})
        voi = pydicom.Dataset()
        voi.ReferencedImageSequence = _flat_referenced_images(references)
        voi.WindowCenter = str(win.get("center", 40))
        voi.WindowWidth = str(win.get("width", 400))
        ds.SoftcopyVOILUTSequence = pydicom.Sequence([voi])
        # Displayed area (full)
        da = pydicom.Dataset()
        da.ReferencedImageSequence = _flat_referenced_images(references)
        da.DisplayedAreaTopLeftHandCorner = [1, 1]
        da.DisplayedAreaBottomRightHandCorner = [512, 512]
        da.PresentationSizeMode = "SCALE TO FIT"
        da.PresentationPixelAspectRatio = [1, 1]
        ds.DisplayedAreaSelectionSequence = pydicom.Sequence([da])
    else:  # KO
        ko = (references.get("keyObject") or {})
        title = ko.get("titleCode", {"value": "113000", "scheme": "DCM", "meaning": "Of Interest"})
        ds.ValueType = "CONTAINER"
        ds.ConceptNameCodeSequence = pydicom.Sequence([_code_item(title["value"], title["scheme"], title["meaning"])])
        ds.ContinuityOfContent = "SEPARATE"
        ds.CompletionFlag = "COMPLETE"
        ds.VerificationFlag = "UNVERIFIED"
        evid = pydicom.Dataset()
        evid.StudyInstanceUID = references.get("studyUID", "")
        evid.ReferencedSeriesSequence = _ko_evidence_series(references)
        ds.CurrentRequestedProcedureEvidenceSequence = pydicom.Sequence([evid])
        ds.ContentSequence = _ko_content_sequence(references, ko.get("description", "Key images"))

    apply_value_map(ds, overrides)
    # Fill Type-2 tags from the non-content modules only (General Study/Series/
    # Equipment/Patient) — excluding SR content-item macro tags that would be
    # bogus at the document root.
    _fill_missing_type2(ds, kb.mandatory_tags(sop_class, exclude_content=True))

    new_study_uid = references.get("studyUID") or uid_strategy.new_uid(job_id, "study")
    new_series_uid = uid_strategy.new_uid(job_id, "series")
    new_sop_uid = uid_strategy.new_uid(job_id, 0)
    ds.StudyInstanceUID = new_study_uid
    ds.SeriesInstanceUID = new_series_uid
    ds.SOPInstanceUID = new_sop_uid
    ds.file_meta.MediaStorageSOPInstanceUID = new_sop_uid
    ds.save_as(staging_dir / "IM0000.dcm", enforce_file_format=True)

    probe = _probe(staging_dir, job_id)
    if probe is not None:
        return probe
    return {"study_uid": new_study_uid, "series_uid": new_series_uid, "count": 1}


def _add_ct_functional_groups(shared_item: pydicom.Dataset, ds: pydicom.Dataset):
    """Enhanced CT's two mandatory shared functional-group macros:
    CT Image Frame Type + Pixel Value Transformation."""
    frame_type = pydicom.Dataset()
    frame_type.FrameType = list(getattr(ds, "ImageType", ["DERIVED", "PRIMARY", "VOLUME", "NONE"]))
    frame_type.PixelPresentation = getattr(ds, "PixelPresentation", "MONOCHROME")
    frame_type.VolumetricProperties = getattr(ds, "VolumetricProperties", "VOLUME")
    frame_type.VolumeBasedCalculationTechnique = getattr(ds, "VolumeBasedCalculationTechnique", "NONE")
    shared_item.CTImageFrameTypeSequence = pydicom.Sequence([frame_type])

    pvt = pydicom.Dataset()
    pvt.RescaleIntercept = "0"
    pvt.RescaleSlope = "1"
    pvt.RescaleType = "HU"
    shared_item.PixelValueTransformationSequence = pydicom.Sequence([pvt])


def _flat_referenced_images(references: dict) -> pydicom.Sequence:
    items = []
    for series in references.get("series", []):
        for inst in series.get("instances", []):
            ri = pydicom.Dataset()
            ri.ReferencedSOPClassUID = inst["sopClassUID"]
            ri.ReferencedSOPInstanceUID = inst["sopInstanceUID"]
            items.append(ri)
    return pydicom.Sequence(items)


def _ko_evidence_series(references: dict) -> pydicom.Sequence:
    items = []
    for series in references.get("series", []):
        s = pydicom.Dataset()
        s.SeriesInstanceUID = series["seriesUID"]
        refs = []
        for inst in series.get("instances", []):
            r = pydicom.Dataset()
            r.ReferencedSOPClassUID = inst["sopClassUID"]
            r.ReferencedSOPInstanceUID = inst["sopInstanceUID"]
            refs.append(r)
        s.ReferencedSOPSequence = pydicom.Sequence(refs)
        items.append(s)
    return pydicom.Sequence(items)


def _ko_content_sequence(references: dict, description: str) -> pydicom.Sequence:
    items = []
    for series in references.get("series", []):
        for inst in series.get("instances", []):
            c = pydicom.Dataset()
            c.RelationshipType = "CONTAINS"
            c.ValueType = "IMAGE"
            r = pydicom.Dataset()
            r.ReferencedSOPClassUID = inst["sopClassUID"]
            r.ReferencedSOPInstanceUID = inst["sopInstanceUID"]
            c.ReferencedSOPSequence = pydicom.Sequence([r])
            items.append(c)
    return pydicom.Sequence(items)


# --- probe -----------------------------------------------------------------
def _probe(staging_dir, job_id):
    """Validate the first materialized file fully. Returns None if it passes, or an
    error dict (and marks the job failed) if not — so the AI can repair before we
    generate the rest (decision #5)."""
    result = validator.validate_dataset(path=str(staging_dir))
    if result.get("passed"):
        return None
    job_registry.update_job(job_id, state="failed", message="probe validation failed")
    return {
        "error": "Probe instance failed validation — fix the spec and retry before generating the full set.",
        "probe_validation": {"errors": result.get("errors", []), "iod_conformance": result.get("iod_conformance", {})},
        "job_id": job_id,
    }


# --- entry point -----------------------------------------------------------
def materialize_dataset(spec_id: str, instance_count: int | None = None, job_id: str | None = None) -> dict:
    from spec_store import get as get_spec

    spec = get_spec(spec_id)
    if spec is None:
        raise SpecError(f"No stored spec with id '{spec_id}' — call validate_spec first")

    req = spec.get("request") or {}
    sop_class = (req.get("seedSource") or {}).get("sopClassUID")
    if not sop_class:
        raise SpecError("spec has no resolved SOP Class (should be set by validate_spec)")
    if not kb.is_supported(sop_class):
        raise SpecError(f"SOP Class {sop_class} is outside the supported family")
    modality = kb.modality_for_sop_class(sop_class) or req.get("modality")

    count = instance_count or req.get("instanceCount") or 1
    if count <= 0:
        raise SpecError("instance_count must be a positive integer")

    job_id = job_id or f"job-{uuid.uuid4().hex[:8]}"
    job_registry.create_job(job_id, message="materializing")
    job_registry.update_job(job_id, state="running", message="materializing")
    staging_dir = config.STAGING_DIR / job_id
    staging_dir.mkdir(parents=True, exist_ok=True)

    try:
        if kb.is_reference_object(sop_class):
            core = _materialize_reference(spec, sop_class, job_id, staging_dir)
        elif kb.multiframe_kind(sop_class) == "classic":
            core = _materialize_classic_mf(spec, sop_class, modality, count, job_id, staging_dir)
        elif kb.multiframe_kind(sop_class) == "enhanced":
            core = _materialize_enhanced_mf(spec, sop_class, modality, count, job_id, staging_dir)
        else:
            core = _materialize_single_frame(spec, sop_class, modality, count, job_id, staging_dir)
    except SpecError as exc:
        job_registry.update_job(job_id, state="failed", message=str(exc))
        exc.job_id = job_id
        raise
    except Exception as exc:
        job_registry.update_job(job_id, state="failed", message=str(exc))
        raise SpecError(str(exc), job_id=job_id) from exc

    if "error" in core:  # probe failed
        return core

    result = {
        "job_id": job_id,
        "output_path": str(staging_dir),
        "spec_id": spec_id,
        **core,
    }
    # Approx token summary (tool-boundary estimate only; excludes chat overhead).
    import audit_log
    import token_util
    result["approx_tokens"] = {
        "spec": token_util.estimate(spec),
        "result": token_util.estimate(result),
        "note": "tool-boundary estimate; excludes Copilot chat/system-prompt overhead",
    }
    # Auto-save a reusable recipe for KB-authored (iod) specs (decision #7).
    if (req.get("seedSource") or {}).get("type") == "iod":
        try:
            import recipe_store
            recipe_store.save_recipe(spec, body_part=req.get("bodyPart"),
                                     orientation=req.get("orientation"), flags=req.get("flags"))
        except Exception:
            pass  # recipe caching is best-effort, never blocks a good result
    audit_log.log_job(job_id, spec, result)
    job_registry.update_job(job_id, state="generated", progress_pct=100, message="materialization complete", result=result)
    return result
