"""generate_prior_study — clone an existing PACS study's full structure (every
series, every instance) into a new study dated `days_before` days earlier for
the same patient. A prior is a full replica plus a date shift, not a
regenerated approximation from one representative instance — reuses
study_clone the same way modify_dataset does, so a multi-series source study
(e.g. a CT with several series, or a US study with several cine instances)
stays multi-series in the prior.
"""

import uuid
from datetime import datetime, timedelta

import config
import job_registry
import study_clone
from dicom_apply import apply_value_map
from spec_store import SpecError

__all__ = ["SpecError", "generate_prior_study"]


def generate_prior_study(study_uid: str, days_before: int, overrides: dict | None = None,
                         job_id: str | None = None) -> dict:
    if not days_before or days_before <= 0:
        raise SpecError("daysBefore must be a positive integer")
    overrides = overrides or {}
    job_id = job_id or f"priorjob-{uuid.uuid4().hex[:8]}"
    job_registry.create_job(job_id, message="fetching reference study")
    job_registry.update_job(job_id, state="running", message="fetching reference study")

    try:
        series_groups = study_clone.fetch_study_series(study_uid)
    except Exception as exc:
        job_registry.update_job(job_id, state="failed", message=str(exc))
        if isinstance(exc, SpecError):
            exc.job_id = job_id
            raise
        raise SpecError(f"Failed to fetch study '{study_uid}' from the PACS: {exc}", job_id=job_id) from exc

    ref_ds = series_groups[0][0]
    ref_date_str = str(getattr(ref_ds, "StudyDate", "") or "")
    if not ref_date_str or not getattr(ref_ds, "PatientID", None):
        exc = SpecError(f"Reference study '{study_uid}' lacks StudyDate/PatientID — cannot make a prior", job_id=job_id)
        job_registry.update_job(job_id, state="failed", message=str(exc))
        raise exc
    try:
        ref_date = datetime.strptime(ref_date_str, "%Y%m%d")
    except ValueError as exc:
        wrapped = SpecError(f"Reference study '{study_uid}' has an unparseable StudyDate '{ref_date_str}'", job_id=job_id)
        job_registry.update_job(job_id, state="failed", message=str(wrapped))
        raise wrapped from exc
    new_date = (ref_date - timedelta(days=days_before)).strftime("%Y%m%d")

    sop_class_uid = str(getattr(ref_ds, "SOPClassUID", ""))
    try:
        study_clone.validate_overrides(overrides, sop_class_uid)
    except SpecError as exc:
        job_registry.update_job(job_id, state="failed", message=str(exc))
        exc.job_id = job_id
        raise

    staging_dir = config.STAGING_DIR / job_id
    staging_dir.mkdir(parents=True, exist_ok=True)

    try:
        new_study_uid = study_clone.remap_uids(series_groups, job_id)  # a prior is always a new derived study
        idx = 0
        for group in series_groups:
            for ds in group:
                ds.StudyDate = new_date
                apply_value_map(ds, overrides)
                ds.save_as(staging_dir / f"IM{idx:04d}.dcm", enforce_file_format=True)
                idx += 1
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
        "count": idx,
        "series_count": len(series_groups),
        "study_date": new_date,
        "days_before": days_before,
        "overrides_applied": overrides,
    }
    job_registry.update_job(job_id, state="generated", progress_pct=100, message="prior generation complete", result=result)
    return result
