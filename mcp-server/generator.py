"""generate_dataset execution — solution-design.md §8.

Runs entirely inside the MCP server process as one call: loads the resolved
seed, loops over instance_count applying the template's tag rules plus any
user overrides, and writes new instances (with fresh, deterministic UIDs) to
staging/<job_id>/.

Tag rewriting is done in-process with pydicom rather than by shelling out to
`dcmodify` per instance/tag — same end result (correct tag values on disk),
without the overhead and batch-script complexity of 200+ subprocess calls.
"""

import random
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

import pydicom
import pydicom.config as pydicom_config

import config
import iod_lookup
import job_registry
import orthanc_client
import templates as template_catalog
import uid_strategy
from override_policy import PlanError, validate_overrides  # noqa: F401 — re-exported for existing importers

SYNTHETIC_NAME_POOL = [
    "DOE^JANE", "DOE^JOHN", "SMITH^ALEX", "PATEL^RIYA", "GARCIA^LUIS",
    "MULLER^ANNA", "NGUYEN^MINH", "KOWALSKI^EWA",
]


@contextmanager
def strict_value_validation():
    """By default, pydicom only *warns* on an invalid value for a tag's VR (e.g.
    PatientAge="not-an-age") and stores it anyway — silently accepting a
    deliberately-broken override instead of rejecting it. Scoped strictly to
    where user-supplied override values are applied (not dataset loading, which
    should stay tolerant of real-world data), this makes that same case raise
    ValueError instead, which callers turn into a PlanError with a clear message.
    """
    previous = pydicom_config.settings.reading_validation_mode
    pydicom_config.settings.reading_validation_mode = pydicom_config.RAISE
    try:
        yield
    finally:
        pydicom_config.settings.reading_validation_mode = previous


def apply_overrides(ds: pydicom.Dataset, overrides: dict) -> None:
    """Apply a validated overrides dict to a dataset, rejecting bad VR values
    with a specific message instead of pydicom's default silent-accept-with-warning."""
    for tag, value in overrides.items():
        try:
            with strict_value_validation():
                setattr(ds, tag, value)
        except ValueError as exc:
            raise PlanError(f"Invalid value for override tag '{tag}': {value!r} — {exc}") from exc


def _load_seed_dataset(seed_source: dict) -> pydicom.Dataset:
    source_type = seed_source.get("type")
    if source_type == "template":
        template_id = seed_source.get("template_id")
        entry = template_catalog.find_catalog_entry(template_id)
        if entry is None:
            raise PlanError(f"No template found with id '{template_id}'")
        seed_path = config.TEMPLATES_DIR / entry["path"] / "seed" / "IM0001.dcm"
        if not seed_path.exists():
            raise PlanError(f"Template '{template_id}' has no seed data at {seed_path}")
        return pydicom.dcmread(seed_path)
    elif source_type == "pacs":
        study_uid = seed_source.get("study_uid")
        if not study_uid:
            raise PlanError("seed_source.type == 'pacs' requires a study_uid")
        raw_bytes = orthanc_client.fetch_first_instance_bytes(study_uid)
        import io

        return pydicom.dcmread(io.BytesIO(raw_bytes))
    else:
        raise PlanError(f"seed_source.type must be 'pacs' or 'template', got '{source_type}'")


def _eval_sequence_formula(formula: str, i: int) -> object:
    formula = formula.strip()
    if formula.startswith("start="):
        # e.g. "start=-120.0, step=1.5"
        parts = dict(p.strip().split("=") for p in formula.split(","))
        start = float(parts["start"])
        step = float(parts["step"])
        return round(start + i * step, 3)
    if formula.startswith("derive_from("):
        return None  # handled specially by caller (needs other tag values)
    # simple arithmetic on i, e.g. "i + 1"
    return eval(formula, {"__builtins__": {}}, {"i": i})  # noqa: S307 — fixed, template-authored formulas only


def _coerce_fixed_value(value: object) -> object:
    """A manifest's tag_rules.fixed is plain YAML, so a sequence-VR tag's value
    arrives as a list of plain dicts (e.g. AnatomicRegionSequence's code item)
    rather than a pydicom Sequence of Dataset — pydicom rejects raw dicts
    directly. Recursively convert list-of-dict values (including an empty
    list, i.e. an empty-but-present sequence) into a real Sequence; anything
    else (scalars, lists of scalars) passes through unchanged."""
    if isinstance(value, list) and all(isinstance(v, dict) for v in value):
        items = []
        for d in value:
            item = pydicom.Dataset()
            for k, v in d.items():
                setattr(item, k, _coerce_fixed_value(v))
            items.append(item)
        return pydicom.Sequence(items)
    return value


def _apply_tag_rules(
    ds: pydicom.Dataset,
    tag_rules: dict,
    i: int,
    randomized_values: dict,
    overrides: dict,
    identity_overrides: dict | None = None,
) -> None:
    for tag, value in (tag_rules.get("fixed") or {}).items():
        setattr(ds, tag, _coerce_fixed_value(value))

    for tag, formula in (tag_rules.get("sequence") or {}).items():
        if formula.strip().startswith("derive_from(SliceLocation)"):
            slice_location = float(getattr(ds, "SliceLocation", 0.0))
            ds.ImagePositionPatient = [-150.0, -150.0, slice_location]
            continue
        value = _eval_sequence_formula(formula, i)
        setattr(ds, tag, str(value) if isinstance(value, (int, float)) else value)

    for tag, value in randomized_values.items():
        setattr(ds, tag, value)

    # Priors: reuse the reference study's identity/date instead of the randomized
    # draw above, so a prior links to the same (synthetic) patient. Applied before
    # user overrides so an explicit override still wins over the priors mechanism.
    for tag, value in (identity_overrides or {}).items():
        setattr(ds, tag, value)

    apply_overrides(ds, overrides)


def _fill_missing_iod_tags(ds: pydicom.Dataset, iod_spec: dict | None) -> None:
    """Safety net, not the primary mechanism: after tag_rules/overrides are
    applied, check the dataset against the committed IOD knowledge base
    (templates/<MODALITY>/<template_id>/iod_spec.yaml) for unconditional
    Type 1/Type 2 tags. Type 2 (must be present, empty allowed) gets filled
    with an empty value. Type 1 (must have a real value) with nothing set
    raises a clear PlanError naming exactly which tags are missing, instead of
    silently shipping a non-conformant instance — this is what should catch a
    template author forgetting a mandatory tag in tag_rules.fixed, not
    something callers are expected to trigger routinely. Type 1C/2C tags are
    conditional and are not evaluated here (see get_iod_requirements to
    inspect them) — their applicability depends on dataset state in ways not
    worth guessing generically.
    """
    if iod_spec is None:
        return

    missing_type1 = []
    for tag in iod_lookup.mandatory_tags(iod_spec):
        keyword = tag.get("keyword")
        if not keyword:
            continue  # retired/private tag with no pydicom keyword — nothing to set generically
        value = getattr(ds, keyword, None)
        if value not in (None, "", []):
            continue
        if tag["type"] == "2":
            setattr(ds, keyword, "")
        else:
            missing_type1.append(f"{keyword} {tag['tag']}")

    if missing_type1:
        raise PlanError(
            "This template is missing values for IOD-mandatory (Type 1) tags: "
            + ", ".join(missing_type1)
            + " — add them to the template's tag_rules.fixed before generating."
        )


def _draw_randomized_values(tag_rules: dict, rng: random.Random) -> dict:
    values = {}
    for tag, pool_name in (tag_rules.get("randomized") or {}).items():
        if pool_name == "synthetic_name_pool":
            values[tag] = rng.choice(SYNTHETIC_NAME_POOL)
        elif pool_name == "generate_synthetic_id":
            values[tag] = f"SYN{rng.randint(100000, 999999)}"
        else:
            raise PlanError(f"Unknown randomized value pool '{pool_name}' for tag '{tag}'")
    return values


def _resolve_prior_identity(prior_of_study_uid: str, days_before: int | None) -> dict:
    """Priors support (Phase 3, new scope beyond solution-design.md): resolve the
    reference study's patient identity + date, so the generated study can reuse
    them and be offset earlier in time — a "prior" for that patient, not an
    unrelated new patient. Each prior still gets its own independent
    StudyInstanceUID/SeriesInstanceUID/SOPInstanceUIDs (non-destructive by
    default, solution-design.md §1.4); only PatientID/PatientName/StudyDate are
    shared/derived.
    """
    if not days_before or days_before <= 0:
        raise PlanError("days_before must be a positive integer when prior_of_study_uid is given")

    ref = orthanc_client.get_study_details(prior_of_study_uid)
    if not ref.get("study_date"):
        raise PlanError(f"Reference study '{prior_of_study_uid}' has no StudyDate — cannot compute a prior date")
    if not ref.get("patient_id"):
        raise PlanError(f"Reference study '{prior_of_study_uid}' has no PatientID — cannot link a prior to it")

    try:
        ref_date = datetime.strptime(ref["study_date"], "%Y%m%d")
    except ValueError as exc:
        raise PlanError(f"Reference study '{prior_of_study_uid}' has an unparseable StudyDate '{ref['study_date']}'") from exc
    prior_date = ref_date - timedelta(days=days_before)

    return {
        "PatientID": ref["patient_id"],
        "PatientName": ref["patient_name"],
        "StudyDate": prior_date.strftime("%Y%m%d"),
    }


def generate_dataset(
    template_id: str,
    seed_source: dict,
    instance_count: int,
    overrides: dict | None = None,
    job_id: str | None = None,
    prior_of_study_uid: str | None = None,
    days_before: int | None = None,
) -> dict:
    if instance_count <= 0:
        raise PlanError("instance_count must be a positive integer")

    manifest = template_catalog.load_manifest(template_id)
    if manifest is None:
        raise PlanError(f"No template found with id '{template_id}'")

    overrides = overrides or {}
    tag_rules = manifest.get("tag_rules", {})
    iod_spec = iod_lookup.load_iod_spec(sop_class_uid=manifest.get("sop_class_uid"))
    valid_keywords = (
        {tag["keyword"] for tag in iod_lookup.all_tags(iod_spec) if tag.get("keyword")} if iod_spec else None
    )
    validate_overrides(overrides, tag_rules, valid_keywords)

    identity_overrides = {}
    if prior_of_study_uid:
        identity_overrides = _resolve_prior_identity(prior_of_study_uid, days_before)

    job_id = job_id or f"job-{uuid.uuid4().hex[:8]}"
    job_registry.create_job(job_id, message="resolving seed")
    job_registry.update_job(job_id, state="running", message="loading seed")

    try:
        seed_ds = _load_seed_dataset(seed_source)
    except Exception as exc:
        job_registry.update_job(job_id, state="failed", message=str(exc))
        if isinstance(exc, PlanError):
            exc.job_id = job_id
            raise
        raise PlanError(str(exc), job_id=job_id) from exc

    rng = random.Random(job_id)
    randomized_values = _draw_randomized_values(tag_rules, rng)

    new_study_uid = uid_strategy.new_uid(job_id, "study")
    new_series_uid = uid_strategy.new_uid(job_id, "series")

    staging_dir = config.STAGING_DIR / job_id
    staging_dir.mkdir(parents=True, exist_ok=True)

    try:
        for i in range(instance_count):
            ds = seed_ds.copy()
            new_sop_uid = uid_strategy.new_uid(job_id, i)

            _apply_tag_rules(ds, tag_rules, i, randomized_values, overrides, identity_overrides)
            _fill_missing_iod_tags(ds, iod_spec)

            ds.StudyInstanceUID = new_study_uid
            ds.SeriesInstanceUID = new_series_uid
            ds.SOPInstanceUID = new_sop_uid
            ds.file_meta.MediaStorageSOPInstanceUID = new_sop_uid

            out_path = staging_dir / f"IM{i:04d}.dcm"
            ds.save_as(out_path, enforce_file_format=True)

            if instance_count >= 20 and i % max(1, instance_count // 10) == 0:
                job_registry.update_job(job_id, progress_pct=int(100 * i / instance_count), message=f"generated {i}/{instance_count}")
    except Exception as exc:
        job_registry.update_job(job_id, state="failed", message=str(exc))
        if isinstance(exc, PlanError):
            exc.job_id = job_id
            raise
        raise PlanError(str(exc), job_id=job_id) from exc

    result = {
        "job_id": job_id,
        "study_uid": new_study_uid,
        "series_uid": new_series_uid,
        "output_path": str(staging_dir),
        "count": instance_count,
        "seed_source": seed_source,
    }
    if identity_overrides:
        result["prior_of_study_uid"] = prior_of_study_uid
        result["patient_id"] = identity_overrides["PatientID"]
        result["study_date"] = identity_overrides["StudyDate"]
    job_registry.update_job(job_id, state="generated", progress_pct=100, message="generation complete", result=result)
    return result
