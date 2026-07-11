"""modify_dataset — edit an existing PACS study's tags (AI-driven redesign).

Fetches every instance of a study, applies overrides, and either writes a new
derived study (regenerate_uids=True, default, non-destructive) or keeps the
original UIDs (regenerate_uids=False, destructive in-place overwrite — gated by
the caller). Override validation now uses the Knowledge Base (the study's actual
SOP Class), not a template. Pixel-module and UID tags are rejected as overrides.
"""

import io
import uuid

import pydicom

import config
import iod_lookup as kb
import job_registry
import orthanc_client
import uid_strategy
from dicom_apply import apply_value_map
from spec_store import SpecError

__all__ = ["SpecError", "modify_dataset"]


def _validate_overrides(overrides: dict, sop_class_uid: str) -> None:
    valid = kb.valid_keywords(sop_class_uid) if sop_class_uid else set()
    for tag in overrides:
        if tag in kb.PIXEL_MODULE_KEYWORDS:
            raise SpecError(f"Tag '{tag}' is pixel-module (Materializer-owned) and can't be overridden here.")
        if tag in kb.PROTECTED_UID_KEYWORDS:
            raise SpecError(f"Tag '{tag}' is a UID/SOPClass tag managed automatically and can't be overridden.")
        if valid and tag not in valid and kb.describe(tag) is None:
            raise SpecError(f"Tag '{tag}' isn't a recognized DICOM tag for this IOD.")


def modify_dataset(study_uid: str, overrides: dict | None = None,
                   regenerate_uids: bool = True, job_id: str | None = None) -> dict:
    overrides = overrides or {}
    job_id = job_id or f"modjob-{uuid.uuid4().hex[:8]}"
    job_registry.create_job(job_id, message="fetching source study")
    job_registry.update_job(job_id, state="running", message="fetching source study")

    try:
        instance_ids = orthanc_client.list_instance_ids(study_uid)
        if not instance_ids:
            raise SpecError(f"Study '{study_uid}' has no instances in the PACS")
        datasets = [pydicom.dcmread(io.BytesIO(orthanc_client.fetch_instance_bytes(iid))) for iid in instance_ids]
        datasets.sort(key=lambda ds: int(getattr(ds, "InstanceNumber", 0)))
    except Exception as exc:
        job_registry.update_job(job_id, state="failed", message=str(exc))
        if isinstance(exc, SpecError):
            exc.job_id = job_id
            raise
        raise SpecError(f"Failed to fetch study '{study_uid}' from the PACS: {exc}", job_id=job_id) from exc

    sop_class_uid = str(getattr(datasets[0], "SOPClassUID", ""))
    try:
        _validate_overrides(overrides, sop_class_uid)
    except SpecError as exc:
        job_registry.update_job(job_id, state="failed", message=str(exc))
        exc.job_id = job_id
        raise

    new_study_uid = uid_strategy.new_uid(job_id, "study") if regenerate_uids else study_uid
    series_uid_map: dict[str, str] = {}
    staging_dir = config.STAGING_DIR / job_id
    staging_dir.mkdir(parents=True, exist_ok=True)

    try:
        for i, ds in enumerate(datasets):
            if regenerate_uids:
                old_series = str(ds.SeriesInstanceUID)
                series_uid_map.setdefault(old_series, uid_strategy.new_uid(job_id, f"series-{old_series}"))
                new_sop = uid_strategy.new_uid(job_id, i)
                ds.StudyInstanceUID = new_study_uid
                ds.SeriesInstanceUID = series_uid_map[old_series]
                ds.SOPInstanceUID = new_sop
                ds.file_meta.MediaStorageSOPInstanceUID = new_sop
            apply_value_map(ds, overrides)
            ds.save_as(staging_dir / f"IM{i:04d}.dcm", enforce_file_format=True)
    except Exception as exc:
        job_registry.update_job(job_id, state="failed", message=str(exc))
        if isinstance(exc, SpecError):
            exc.job_id = job_id
            raise
        raise SpecError(str(exc), job_id=job_id) from exc

    result = {
        "job_id": job_id,
        "original_study_uid": study_uid,
        "study_uid": new_study_uid,
        "output_path": str(staging_dir),
        "count": len(datasets),
        "regenerate_uids": regenerate_uids,
        "overrides_applied": overrides,
    }
    if not regenerate_uids:
        result["destructive_overwrite"] = True
        result["note"] = (
            "regenerate_uids=False: instances kept their ORIGINAL UIDs. Whether store_to_pacs "
            "actually replaces the existing copy depends on the PACS's overwrite policy "
            "(e.g. Orthanc's OverwriteInstances) — verify in the PACS after storing."
        )
    job_registry.update_job(job_id, state="modified", progress_pct=100, message="modification complete", result=result)
    return result
