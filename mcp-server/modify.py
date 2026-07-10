"""modify_dataset execution — solution-design.md §9.

Fetches every instance of an existing PACS study, applies tag overrides, and
either:
  - regenerate_uids=True (default, non-destructive): writes a new derived
    study with fresh Study/Series/SOPInstanceUIDs. The original study in the
    PACS is untouched — this is a completely independent set of instances,
    same as generate_dataset's output.
  - regenerate_uids=False (destructive): keeps the original UIDs, so storing
    the result is intended to overwrite the existing PACS copy in place. The
    calling tool (server.py) is responsible for gating this behind explicit
    user confirmation before calling here — this function does not prompt.

PatientID/PatientName and other identity tags are NOT changed by
regenerate_uids alone — a derived study is still the same (synthetic)
patient's data unless the caller explicitly overrides those tags too.
"""

import io
import uuid
from pathlib import Path

import pydicom

import config
import iod_lookup
import job_registry
import orthanc_client
import templates as template_catalog
import uid_strategy
from generator import apply_overrides
from override_policy import PlanError, validate_overrides

__all__ = ["PlanError", "modify_dataset"]


def _tag_rules_for_modality(modality: str) -> dict:
    """Best-effort sequence-tag protection: existing PACS data has no
    template_id of its own, so look one up by modality to find its
    tag_rules.sequence keywords. Returns {} (no sequence tags to protect
    beyond the generic UID set) if no template matches — overrides are still
    checked against the actual IOD's tag list regardless."""
    matches = template_catalog.list_templates(modality=modality)
    if not matches:
        return {}
    manifest = template_catalog.load_manifest(matches[0]["template_id"])
    return manifest.get("tag_rules", {}) if manifest else {}


def modify_dataset(
    study_uid: str,
    overrides: dict | None = None,
    regenerate_uids: bool = True,
    job_id: str | None = None,
) -> dict:
    overrides = overrides or {}
    job_id = job_id or f"modjob-{uuid.uuid4().hex[:8]}"
    job_registry.create_job(job_id, message="fetching source study")
    job_registry.update_job(job_id, state="running", message="fetching source study")

    try:
        instance_ids = orthanc_client.list_instance_ids(study_uid)
        if not instance_ids:
            raise PlanError(f"Study '{study_uid}' has no instances in the PACS")
        datasets = [pydicom.dcmread(io.BytesIO(orthanc_client.fetch_instance_bytes(iid))) for iid in instance_ids]
        # Orthanc's /instances listing order isn't guaranteed to match InstanceNumber —
        # sort explicitly so output filenames (and validate_dataset's ordering check)
        # reflect the original sequence, not Orthanc's internal storage order.
        datasets.sort(key=lambda ds: int(getattr(ds, "InstanceNumber", 0)))
    except Exception as exc:
        job_registry.update_job(job_id, state="failed", message=str(exc))
        if isinstance(exc, PlanError):
            exc.job_id = job_id
            raise
        raise PlanError(f"Failed to fetch study '{study_uid}' from the PACS: {exc}", job_id=job_id) from exc

    modality = str(getattr(datasets[0], "Modality", "")).upper()
    sop_class_uid = str(getattr(datasets[0], "SOPClassUID", ""))
    tag_rules = _tag_rules_for_modality(modality)
    iod_spec = iod_lookup.load_iod_spec(sop_class_uid=sop_class_uid)
    valid_keywords = (
        {tag["keyword"] for tag in iod_lookup.all_tags(iod_spec) if tag.get("keyword")} if iod_spec else None
    )
    try:
        validate_overrides(overrides, tag_rules, valid_keywords)
    except PlanError as exc:
        job_registry.update_job(job_id, state="failed", message=str(exc))
        exc.job_id = job_id
        raise

    original_study_uid = study_uid
    new_study_uid = study_uid
    series_uid_map: dict[str, str] = {}
    if regenerate_uids:
        new_study_uid = uid_strategy.new_uid(job_id, "study")

    staging_dir = config.STAGING_DIR / job_id
    staging_dir.mkdir(parents=True, exist_ok=True)

    try:
        for i, ds in enumerate(datasets):
            if regenerate_uids:
                old_series_uid = str(ds.SeriesInstanceUID)
                if old_series_uid not in series_uid_map:
                    series_uid_map[old_series_uid] = uid_strategy.new_uid(job_id, f"series-{old_series_uid}")
                new_sop_uid = uid_strategy.new_uid(job_id, i)
                ds.StudyInstanceUID = new_study_uid
                ds.SeriesInstanceUID = series_uid_map[old_series_uid]
                ds.SOPInstanceUID = new_sop_uid
                ds.file_meta.MediaStorageSOPInstanceUID = new_sop_uid

            apply_overrides(ds, overrides)

            out_path = staging_dir / f"IM{i:04d}.dcm"
            ds.save_as(out_path, enforce_file_format=True)

            if len(datasets) >= 20 and i % max(1, len(datasets) // 10) == 0:
                job_registry.update_job(job_id, progress_pct=int(100 * i / len(datasets)), message=f"modified {i}/{len(datasets)}")
    except Exception as exc:
        job_registry.update_job(job_id, state="failed", message=str(exc))
        if isinstance(exc, PlanError):
            exc.job_id = job_id
            raise
        raise PlanError(str(exc), job_id=job_id) from exc

    result = {
        "job_id": job_id,
        "original_study_uid": original_study_uid,
        "study_uid": new_study_uid,
        "output_path": str(staging_dir),
        "count": len(datasets),
        "regenerate_uids": regenerate_uids,
        "overrides_applied": overrides,
    }
    if not regenerate_uids:
        result["destructive_overwrite"] = True
        result["note"] = (
            "regenerate_uids=False: instances were written with their ORIGINAL UIDs. "
            "Whether store_to_pacs actually replaces the existing copy in the PACS "
            "depends on the PACS's own overwrite policy (e.g. Orthanc's "
            "OverwriteInstances setting) — this codebase does not control that "
            "configuration. Verify in the PACS after storing."
        )
    job_registry.update_job(job_id, state="modified", progress_pct=100, message="modification complete", result=result)
    return result
