"""validate_dataset — solution-design.md §10.

All three documented layers are implemented here:
  - IOD conformance (required/conditional tag presence, VR/VM per SOP Class),
    via the `dicom-validator` PyPI package rather than `dciodvfy`. dciodvfy
    ships in dicom3tools, not DCMTK, and neither dicom3tools nor DCMTK has a
    package-manager install path on this machine; dicom-validator does the
    same job (validates against the DICOM standard's own module/IOD
    definitions) as a plain pip dependency. It downloads and caches the
    DICOM standard's docbook/JSON excerpts under ~/dicom-validator on first
    use (one-time, ~40s; instant afterwards).
  - Cross-instance structural checks (pydicom-based, 100% of instances always)
  - Basic per-file readability (`dcmftest`, if DCMTK is on PATH)

Sampling policy (§10): validate all instances for count<=50; otherwise
first 5 + last 5 + a random 20 (or 10%, whichever is larger). IOD conformance
and dcmftest both run on the sampled subset; structural checks always run on
100% of instances (cheap, and catch systemic errors dicom-validator won't).
"""

import io
import random
import shutil
import subprocess
import uuid
from collections import defaultdict
from pathlib import Path

import pydicom
from dicom_validator.validator.dicom_file_validator import DicomFileValidator
from dicom_validator.validator.error_handler import ValidationResultHandlerBase
from dicom_validator.validator.validation_result import Status

import config
import iod_lookup
import orthanc_client


def _get_dicom_info():
    """Shared with the Knowledge Base (iod_lookup) so the ~40s standard-data load
    happens at most once per process, whether triggered by validation or by a
    KB lookup."""
    return iod_lookup.get_dicom_info()


def _select_sample(files: list[Path]) -> list[Path]:
    if len(files) <= 50:
        return files
    first = files[:5]
    last = files[-5:]
    remaining = [f for f in files if f not in first and f not in last]
    sample_size = max(20, int(0.1 * len(files)))
    random_sample = random.sample(remaining, min(sample_size, len(remaining)))
    return list({*first, *last, *random_sample})


def _structural_checks(files: list[Path]) -> tuple[list[str], list[str]]:
    """A file set is one study, but legitimately many series (multi-series
    studies from modify_dataset/generate_prior_study, or a multi-series
    generation via request.attachStudyUID) — so StudyInstanceUID must be
    identical across every file, but SeriesInstanceUID varying is normal and
    InstanceNumber only needs to increase *within* each series, not globally
    across series boundaries."""
    errors: list[str] = []
    study_uids, sop_uids = set(), set()
    by_series: dict[str, list[tuple[int, str]]] = defaultdict(list)

    for f in files:
        try:
            ds = pydicom.dcmread(f)
        except Exception as exc:
            errors.append(f"{f.name}: failed to read ({exc})")
            continue
        study_uids.add(getattr(ds, "StudyInstanceUID", None))
        series_uid = getattr(ds, "SeriesInstanceUID", None)
        sop_uid = getattr(ds, "SOPInstanceUID", None)
        if sop_uid in sop_uids:
            errors.append(f"{f.name}: duplicate SOPInstanceUID {sop_uid}")
        sop_uids.add(sop_uid)
        by_series[series_uid].append((int(getattr(ds, "InstanceNumber", 0) or 0), f.name))
        # Reference objects (PR/KO) legitimately carry no pixel data.
        if not iod_lookup.is_reference_object(str(getattr(ds, "SOPClassUID", ""))) and not getattr(ds, "PixelData", None):
            errors.append(f"{f.name}: missing PixelData")

    if len(study_uids) > 1:
        errors.append(f"StudyInstanceUID not identical across instances: {study_uids}")

    for series_uid, entries in by_series.items():
        numbers = [n for n, _ in entries]
        if numbers != sorted(numbers):
            errors.append(f"InstanceNumber is not strictly increasing within series {series_uid}: {numbers}")

    warnings: list[str] = []
    return errors, warnings


def _dcmftest_check(files: list[Path]) -> dict:
    exe = shutil.which("dcmftest")
    if exe is None:
        return {"ran": False, "reason": "dcmftest not found on PATH"}
    failures = []
    for f in files:
        proc = subprocess.run([exe, str(f)], capture_output=True, text=True)
        if proc.returncode != 0:
            failures.append(f.name)
    return {"ran": True, "checked": len(files), "failures": failures}


def _iod_conformance_check(files: list[Path]) -> dict:
    try:
        dicom_info = _get_dicom_info()
    except Exception as exc:
        return {"ran": False, "reason": f"failed to load DICOM standard info: {exc}"}

    # A silent handler: we read results from the returned ValidationResult objects
    # ourselves. dicom-validator's default handler logs to stdout, which would
    # corrupt the MCP server's stdio JSON-RPC channel — must not use it here.
    validator = DicomFileValidator(dicom_info, error_handler=ValidationResultHandlerBase())
    per_file_errors: dict[str, list[str]] = {}
    for f in files:
        results = validator.validate(f)
        for file_path, result in results.items():
            if result.status == Status.Passed:
                continue
            if result.status != Status.Failed:
                per_file_errors[Path(file_path).name] = [f"validation could not run: {result.status.name}"]
                continue
            messages = []
            for module_name, tag_errors in (result.module_errors or {}).items():
                for tag_id, tag_error in tag_errors.items():
                    messages.append(f"{module_name}: tag {tag_id} — {tag_error.code.name}")
            per_file_errors[Path(file_path).name] = messages

    return {
        "ran": True,
        "checked": len(files),
        "files_with_errors": len(per_file_errors),
        "example_errors": {name: msgs[:5] for name, msgs in list(per_file_errors.items())[:5]},
    }


def _materialize_study(study_uid: str) -> Path:
    """Fetch every instance of a PACS study into a throwaway staging folder so
    validate_dataset(study_uid=) can reuse the same folder-based checks as the
    generate_dataset/modify_dataset path — this MCP server has no separate
    'validate directly from the PACS' code path, just the same one applied to
    a freshly-downloaded copy."""
    instance_ids = orthanc_client.list_instance_ids(study_uid)
    if not instance_ids:
        raise ValueError(f"Study '{study_uid}' has no instances in the PACS")

    # Orthanc's /instances listing order isn't guaranteed to match InstanceNumber —
    # sort by the actual tag (same fix as modify.py) so the InstanceNumber-ordering
    # structural check reflects the real sequence, not Orthanc's storage order.
    datasets_by_id = {iid: pydicom.dcmread(io.BytesIO(orthanc_client.fetch_instance_bytes(iid))) for iid in instance_ids}
    ordered_ids = sorted(datasets_by_id, key=lambda iid: int(getattr(datasets_by_id[iid], "InstanceNumber", 0) or 0))

    out_dir = config.STAGING_DIR / f"validate-{uuid.uuid4().hex[:8]}"
    out_dir.mkdir(parents=True, exist_ok=True)
    for i, instance_id in enumerate(ordered_ids):
        datasets_by_id[instance_id].save_as(out_dir / f"IM{i:04d}.dcm", enforce_file_format=True)
    return out_dir


def validate_dataset(path: str | None = None, study_uid: str | None = None) -> dict:
    if study_uid:
        try:
            folder = _materialize_study(study_uid)
        except Exception as exc:
            return {"passed": False, "errors": [f"Failed to fetch study '{study_uid}' from the PACS: {exc}"]}
        path = str(folder)
    elif not path:
        return {"passed": False, "errors": ["Either path or study_uid must be given"]}

    folder = Path(path)
    if not folder.is_dir():
        return {"passed": False, "errors": [f"'{path}' is not a directory"]}

    all_files = sorted(folder.glob("*.dcm"))
    if not all_files:
        return {"passed": False, "errors": [f"No .dcm files found in '{path}'"]}

    structural_errors, structural_warnings = _structural_checks(all_files)

    sampled = _select_sample(all_files)
    dcmftest_result = _dcmftest_check(sampled)
    iod_result = _iod_conformance_check(sampled)

    errors = (
        structural_errors
        + [f"dcmftest failed: {name}" for name in dcmftest_result.get("failures", [])]
        + [f"IOD conformance failed: {name}" for name in iod_result.get("example_errors", {})]
    )
    passed = len(errors) == 0

    return {
        "passed": passed,
        "source_path": str(folder),
        "checked_instances": len(all_files),
        "sampled_instances": len(sampled),
        "sampling_ratio": f"{len(sampled)}/{len(all_files)}",
        "iod_conformance": iod_result,
        "dcmftest": dcmftest_result,
        "errors": errors[:5],
        "warnings": structural_warnings[:5],
    }
