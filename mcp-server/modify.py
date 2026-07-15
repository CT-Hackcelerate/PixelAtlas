"""modify_dataset — edit an existing PACS study's tags (AI-driven redesign).

Fetches every instance of a study (all series, via study_clone), applies
uniform overrides and/or per-instance rules, and either writes a new derived
study (regenerate_uids=True, default, non-destructive) or keeps the original
UIDs (regenerate_uids=False, destructive in-place overwrite — gated by the
caller). Override validation uses the Knowledge Base (the study's actual SOP
Class), not a template. Pixel-module and UID tags are rejected as overrides.
"""

import uuid

import config
import job_registry
import study_clone
from dicom_apply import apply_per_instance, apply_value_map
from spec_store import SpecError

__all__ = ["SpecError", "modify_dataset"]


def modify_dataset(study_uid: str, overrides: dict | None = None, per_instance: dict | None = None,
                   regenerate_uids: bool = True, job_id: str | None = None) -> dict:
    overrides = overrides or {}
    job_id = job_id or f"modjob-{uuid.uuid4().hex[:8]}"
    job_registry.create_job(job_id, message="fetching source study")
    job_registry.update_job(job_id, state="running", message="fetching source study")

    try:
        series_groups = study_clone.fetch_study_series(study_uid)
    except Exception as exc:
        job_registry.update_job(job_id, state="failed", message=str(exc))
        if isinstance(exc, SpecError):
            exc.job_id = job_id
            raise
        raise SpecError(f"Failed to fetch study '{study_uid}' from the PACS: {exc}", job_id=job_id) from exc

    sop_class_uid = str(getattr(series_groups[0][0], "SOPClassUID", ""))
    try:
        study_clone.validate_overrides(overrides, sop_class_uid)
        study_clone.validate_overrides(per_instance or {}, sop_class_uid)
    except SpecError as exc:
        job_registry.update_job(job_id, state="failed", message=str(exc))
        exc.job_id = job_id
        raise

    staging_dir = config.STAGING_DIR / job_id
    staging_dir.mkdir(parents=True, exist_ok=True)

    try:
        new_study_uid = study_clone.remap_uids(series_groups, job_id) if regenerate_uids else study_uid
        idx = 0
        for group in series_groups:
            # Per-instance rules (e.g. progressively shifting ImagePositionPatient)
            # index from 0 *within its own original series*, mirroring how the
            # source study itself indexed instances — not across the whole study.
            for local_i, ds in enumerate(group):
                apply_value_map(ds, overrides)
                if per_instance:
                    apply_per_instance(ds, per_instance, local_i)
                ds.save_as(staging_dir / f"{ds.SOPInstanceUID}.dcm", enforce_file_format=True)
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
        "regenerate_uids": regenerate_uids,
        "overrides_applied": overrides,
        "per_instance_applied": per_instance or {},
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
