"""Full-fidelity PACS study replication — the single place a multi-series
study is faithfully cloned end to end, instead of collapsed to one
representative instance.

Used by modify_dataset (edit an existing study) and generate_prior_study
(clone + shift StudyDate) — both need every instance of every series, with
each original series remapped to its own new series UID so the clone's
structure matches the source: N series in, N series out.
"""

import io

import pydicom

import iod_lookup as kb
import orthanc_client
import uid_strategy
from spec_store import SpecError

__all__ = ["fetch_study_series", "remap_uids", "validate_overrides"]


def fetch_study_series(study_uid: str) -> list[list[pydicom.Dataset]]:
    """Every instance of `study_uid`, grouped by its original SeriesInstanceUID
    (each group sorted by InstanceNumber) — one group per source series, in a
    stable order. Raises ValueError if the study has no instances."""
    instance_ids = orthanc_client.list_instance_ids(study_uid)
    if not instance_ids:
        raise ValueError(f"Study '{study_uid}' has no instances in the PACS")
    datasets = [pydicom.dcmread(io.BytesIO(orthanc_client.fetch_instance_bytes(iid))) for iid in instance_ids]

    groups: dict[str, list[pydicom.Dataset]] = {}
    for ds in datasets:
        groups.setdefault(str(getattr(ds, "SeriesInstanceUID", "")), []).append(ds)
    for series in groups.values():
        series.sort(key=lambda ds: int(getattr(ds, "InstanceNumber", 0) or 0))
    return [groups[k] for k in sorted(groups)]


def remap_uids(series_groups: list[list[pydicom.Dataset]], job_id: str, new_study_uid: str | None = None) -> str:
    """Mutate every dataset in place: one new StudyInstanceUID shared across
    the whole clone (or reuse `new_study_uid` if given), one new
    SeriesInstanceUID per original series (consistent within that series, so
    the source's N-series structure survives), and a fresh SOPInstanceUID per
    instance. Returns the StudyInstanceUID actually used."""
    study_uid = new_study_uid or uid_strategy.new_uid(job_id, "study")
    idx = 0
    for group in series_groups:
        old_series = str(group[0].SeriesInstanceUID) if group else ""
        new_series_uid = uid_strategy.new_uid(job_id, f"series-{old_series}")
        for ds in group:
            new_sop = uid_strategy.new_uid(job_id, idx)
            ds.StudyInstanceUID = study_uid
            ds.SeriesInstanceUID = new_series_uid
            ds.SOPInstanceUID = new_sop
            ds.file_meta.MediaStorageSOPInstanceUID = new_sop
            idx += 1
    return study_uid


def validate_overrides(overrides: dict, sop_class_uid: str) -> None:
    valid = kb.valid_keywords(sop_class_uid) if sop_class_uid else set()
    for tag in overrides or {}:
        if tag in kb.PIXEL_MODULE_KEYWORDS:
            raise SpecError(f"Tag '{tag}' is pixel-module (Materializer-owned) and can't be overridden here.")
        if tag in kb.PROTECTED_UID_KEYWORDS:
            raise SpecError(f"Tag '{tag}' is a UID/SOPClass tag managed automatically and can't be overridden.")
        if valid and tag not in valid and kb.describe(tag) is None:
            raise SpecError(f"Tag '{tag}' isn't a recognized DICOM tag for this IOD.")
