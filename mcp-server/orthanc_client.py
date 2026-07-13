"""Thin wrapper around the Orthanc REST API.

Used both for the resolve_seed similarity search (later) and direct PACS
browsing via list_pacs_studies (this file, Phase 1).
"""

import requests

import config


def _session() -> requests.Session:
    s = requests.Session()
    s.auth = (config.ORTHANC_USER, config.ORTHANC_PASSWORD)
    return s


def get_system_info(timeout: float = 3.0) -> dict:
    """Raises requests.RequestException if Orthanc is unreachable."""
    resp = _session().get(f"{config.ORTHANC_URL}/system", timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def is_reachable(timeout: float = 3.0) -> tuple[bool, str]:
    try:
        info = get_system_info(timeout=timeout)
        return True, f"Orthanc {info.get('Version', 'unknown')} reachable at {config.ORTHANC_URL}"
    except requests.RequestException as exc:
        return False, f"Orthanc unreachable at {config.ORTHANC_URL}: {exc}"


def find_studies(modality: str | None = None, patient_name: str | None = None, date_range: str | None = None) -> list[dict]:
    """Query studies via Orthanc's /tools/find (uses ExtendedFind's RequestedTags).

    date_range, if given, is a DICOM-style range string, e.g. "20240101-20241231".
    """
    query: dict[str, str] = {}
    if modality:
        query["ModalitiesInStudy"] = modality
    if patient_name:
        query["PatientName"] = f"*{patient_name}*"
    if date_range:
        query["StudyDate"] = date_range

    body = {
        "Level": "Study",
        "Query": query,
        "Expand": True,
        "RequestedTags": ["StudyDate", "StudyDescription", "ModalitiesInStudy", "PatientName"],
    }
    resp = _session().post(f"{config.ORTHANC_URL}/tools/find", json=body, timeout=10)
    resp.raise_for_status()
    results = resp.json()

    studies = []
    for entry in results:
        tags = entry.get("RequestedTags", {})
        main_tags = entry.get("MainDicomTags", {})
        studies.append(
            {
                "study_uid": main_tags.get("StudyInstanceUID") or entry.get("MainDicomTags", {}).get("StudyInstanceUID") or entry.get("ID"),
                "modality": tags.get("ModalitiesInStudy", ""),
                "date": tags.get("StudyDate", ""),
                "description": tags.get("StudyDescription", ""),
            }
        )
    return studies


def _find_orthanc_study_id(study_uid: str, session: requests.Session, timeout: float) -> str:
    find_resp = session.post(
        f"{config.ORTHANC_URL}/tools/find",
        json={"Level": "Study", "Query": {"StudyInstanceUID": study_uid}},
        timeout=timeout,
    )
    find_resp.raise_for_status()
    orthanc_ids = find_resp.json()
    if not orthanc_ids:
        raise ValueError(f"No study found in Orthanc with StudyInstanceUID '{study_uid}'")
    return orthanc_ids[0]


def get_study_details(study_uid: str, timeout: float = 10.0) -> dict:
    """Fetch a study's patient identity + date/description — used by generate_dataset's
    priors support and by attach-to-existing-study series generation to reuse a
    reference study's identity. Raises ValueError if the study isn't in Orthanc."""
    session = _session()
    orthanc_study_id = _find_orthanc_study_id(study_uid, session, timeout)
    resp = session.get(f"{config.ORTHANC_URL}/studies/{orthanc_study_id}", timeout=timeout)
    resp.raise_for_status()
    study = resp.json()
    main_tags = study.get("MainDicomTags", {})
    patient_tags = study.get("PatientMainDicomTags", {})
    return {
        "study_uid": study_uid,
        "patient_id": patient_tags.get("PatientID", ""),
        "patient_name": patient_tags.get("PatientName", ""),
        "study_date": main_tags.get("StudyDate", ""),
        "study_description": main_tags.get("StudyDescription", ""),
        "accession_number": main_tags.get("AccessionNumber", ""),
    }


def list_instance_ids(study_uid: str, timeout: float = 10.0) -> list[str]:
    """All Orthanc instance IDs for a study — used by modify_dataset (needs every
    instance, not just one representative) and standalone validate_dataset(study_uid=)."""
    session = _session()
    orthanc_study_id = _find_orthanc_study_id(study_uid, session, timeout)
    instances_resp = session.get(f"{config.ORTHANC_URL}/studies/{orthanc_study_id}/instances", timeout=timeout)
    instances_resp.raise_for_status()
    return [instance["ID"] for instance in instances_resp.json()]


def list_instance_geometry(study_uid: str, timeout: float = 10.0) -> list[dict]:
    """InstanceNumber/SliceLocation for every instance of a study, in one Instance-level
    /tools/find call (metadata only, no pixel data) — used to resample cross-sectional
    slice spacing to a different instance count on PACS-seeded regeneration, instead of
    freezing every new instance to the single seed instance's SliceLocation."""
    body = {
        "Level": "Instance",
        "Query": {"StudyInstanceUID": study_uid},
        "Expand": True,
        "RequestedTags": ["InstanceNumber", "SliceLocation"],
    }
    resp = _session().post(f"{config.ORTHANC_URL}/tools/find", json=body, timeout=timeout)
    resp.raise_for_status()
    geo = []
    for entry in resp.json():
        tags = entry.get("RequestedTags", {})
        loc = tags.get("SliceLocation")
        if loc in (None, ""):
            continue
        try:
            geo.append((int(tags.get("InstanceNumber") or 0), float(loc)))
        except ValueError:
            continue
    geo.sort(key=lambda pair: pair[0])
    return [{"instance_number": n, "slice_location": s} for n, s in geo]


def get_first_instance_id(study_uid: str, timeout: float = 10.0) -> str:
    """Resolve a study's Orthanc instance ID for its first stored instance."""
    instance_ids = list_instance_ids(study_uid, timeout)
    if not instance_ids:
        raise ValueError(f"Study '{study_uid}' has no instances in Orthanc")
    return instance_ids[0]


def fetch_instance_bytes(instance_id: str, timeout: float = 15.0) -> bytes:
    """Fetch one instance's raw DICOM bytes by its Orthanc instance ID."""
    resp = _session().get(f"{config.ORTHANC_URL}/instances/{instance_id}/file", timeout=timeout)
    resp.raise_for_status()
    return resp.content


def get_instance_tags(instance_id: str, timeout: float = 10.0) -> dict:
    """Fetch one instance's full tag set as pydicom-keyword: value pairs (no pixel data).

    Used by check_pacs_feature for generic tag-presence/value lookups — this
    covers any DICOM tag, not just the ones Orthanc indexes into MainDicomTags.
    """
    resp = _session().get(f"{config.ORTHANC_URL}/instances/{instance_id}/tags", params={"simplify": ""}, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def fetch_first_instance_bytes(study_uid: str, timeout: float = 15.0) -> bytes:
    """Fetch the raw DICOM bytes of one instance from a study, to use as a clone seed."""
    return fetch_instance_bytes(get_first_instance_id(study_uid, timeout), timeout)


def list_series_instances(study_uid: str, series_uid: str | None = None, timeout: float = 10.0) -> list[dict]:
    """Enumerate stored instances for a study (optionally narrowed to one series) —
    the lookup an agent needs to build a PR/KO `references` block against instances
    already in the PACS, without ever reading a .dcm file directly.

    Raises ValueError if nothing matches (study/series not yet stored)."""
    query: dict[str, str] = {"StudyInstanceUID": study_uid}
    if series_uid:
        query["SeriesInstanceUID"] = series_uid
    body = {
        "Level": "Instance",
        "Query": query,
        "Expand": True,
        "RequestedTags": ["SeriesInstanceUID", "SOPClassUID", "SOPInstanceUID", "InstanceNumber"],
    }
    resp = _session().post(f"{config.ORTHANC_URL}/tools/find", json=body, timeout=timeout)
    resp.raise_for_status()
    results = resp.json()
    if not results:
        scope = f"study '{study_uid}'" + (f" series '{series_uid}'" if series_uid else "")
        raise ValueError(f"No stored instances found for {scope}")

    instances = []
    for entry in results:
        tags = entry.get("RequestedTags", {})
        instances.append(
            {
                "series_uid": tags.get("SeriesInstanceUID", ""),
                "sop_class_uid": tags.get("SOPClassUID", ""),
                "sop_instance_uid": tags.get("SOPInstanceUID", ""),
                "instance_number": tags.get("InstanceNumber", ""),
            }
        )
    return instances


def upload_instance(dicom_bytes: bytes, timeout: float = 15.0) -> dict:
    """Upload one DICOM file via Orthanc REST (/instances) — used by store_to_pacs as the
    Orthanc-specific alternative to storescu (solution-design.md §11)."""
    resp = _session().post(f"{config.ORTHANC_URL}/instances", data=dicom_bytes, timeout=timeout)
    resp.raise_for_status()
    return resp.json()
