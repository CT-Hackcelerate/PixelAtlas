"""Pixel Atlas MCP server — entry point.

The agent authors (or extracts) a Generation Spec grounded on the Knowledge Base,
validates it (validate_spec -> spec_id), then materializes it. See
docs/architecture.md and docs/solution-design.md for the full design.
"""

import logging
import shutil
import sys
from pathlib import Path

# dicom_validator attaches a StreamHandler(sys.stdout) to the root logger on first
# use if none exists — which would corrupt the MCP stdio JSON-RPC channel. Attach a
# stderr handler first so that check is satisfied.
logging.getLogger().addHandler(logging.StreamHandler(sys.stderr))

from mcp.server.fastmcp import FastMCP

import audit_log
import config
import feature_lookup
import iod_lookup as kb
import job_registry
import materializer
import modify
import orthanc_client
import pacs_store
import priors
import recipe_store
import seed_resolver
import spec_extractor
import spec_validator
import validator
from spec_store import SpecError

mcp = FastMCP("pixel-atlas")

DCMTK_BINARIES = ["storescu", "dcmftest"]


# --- Knowledge Base ---------------------------------------------------------
@mcp.tool()
def get_iod_requirements(sop_class_uid: str | None = None, modality: str | None = None,
                         enhanced: bool = False, full: bool = False) -> dict:
    """DICOM Knowledge Base lookup for a SOP Class (or modality).

    Returns a COMPACT summary by default (module names + usage + counts + the
    mandatory Type-1 tag keywords) — small enough to keep in context. Only pass
    `full=True` if you truly need every tag's VR/enum detail for authoring; it is
    ~9k tokens, so avoid it. Check `find_recipe` first — a cache hit skips this
    call entirely. Covers image IODs + PR/KO; other IODs are reported unsupported.
    """
    resolved = kb.resolve_sop_class(modality=modality, enhanced=enhanced, sop_class_uid=sop_class_uid)
    if not resolved:
        return {"error": f"Could not resolve a SOP Class from modality={modality!r} sop_class_uid={sop_class_uid!r}"}
    if not kb.is_supported(resolved):
        return {"error": f"SOP Class {resolved} is outside the supported family (image IODs + PR/KO). Refuse this request.", "sop_class_uid": resolved}
    req = kb.requirements(resolved) if full else kb.requirements_summary(resolved)
    if req is None:
        return {"error": f"No knowledge base entry for SOP Class {resolved}"}
    audit_log.log_call("get_iod_requirements", {"sop_class_uid": resolved, "full": full}, f"{len(req['modules'])} modules")
    return req


@mcp.tool()
def describe_attributes(names: list[str]) -> list[dict]:
    """Look up VR/keyword/tag for a list of DICOM keywords or 'GGGG,EEEE' tags —
    a fast grounding check while authoring or editing a Generation Spec."""
    result = kb.describe_many(names)
    audit_log.log_call("describe_attributes", {"count": len(names)}, f"{sum('error' not in r for r in result)} resolved")
    return result


# --- seed resolution / extraction ------------------------------------------
@mcp.tool()
def resolve_seed(modality: str, body_part: str | None = None, orientation: str | None = None, enhanced: bool = False) -> dict:
    """PACS-first seed resolution. Returns source_type 'pacs' (extract_spec from a
    candidate) or 'iod' (author a spec from the KB). Matching is lightweight
    (modality + StudyDescription substring)."""
    result = seed_resolver.resolve_seed(modality, body_part, orientation, enhanced)
    audit_log.log_call("resolve_seed", {"modality": modality, "body_part": body_part, "orientation": orientation}, result["source_type"])
    return result


@mcp.tool()
def extract_spec(study_uid: str | None = None, path: str | None = None) -> dict:
    """Turn an existing PACS study (or local .dcm path) into a Generation Spec you
    can edit (apply overrides, set count) and then validate_spec + materialize.
    No PHI scrubbing — test data only."""
    try:
        spec = spec_extractor.extract_spec(study_uid=study_uid, path=path)
        audit_log.log_call("extract_spec", {"study_uid": study_uid, "path": bool(path)}, f"{len(spec.get('attributes', {}))} attributes")
        return spec
    except SpecError as exc:
        audit_log.log_call("extract_spec", {"study_uid": study_uid}, f"error: {exc}")
        return {"error": str(exc)}


# --- validate + materialize -------------------------------------------------
@mcp.tool()
def validate_spec(spec: dict) -> dict:
    """Ground a Generation Spec against the KB before building: tag existence, VR
    correctness, IOD validity, pixel-module/UID placement, and cross-tag
    consistency (pixel group, Modality<->SOPClass, geometry). On success stores
    the spec and returns a `spec_id` to pass to materialize_dataset (so the spec
    isn't re-sent). On failure returns specific errors to repair."""
    result = spec_validator.validate_spec(spec)
    audit_log.log_call("validate_spec", {"modality": (spec.get("request") or {}).get("modality")},
                       "grounded" if result["grounded"] else f"{len(result['errors'])} errors")
    return result


@mcp.tool()
def materialize_dataset(spec_id: str, instance_count: int | None = None, job_id: str | None = None) -> dict:
    """Build .dcm files from a validated spec (referenced by spec_id). Validates one
    probe instance fully before expanding to N (single-frame), or builds one
    multi-frame / PR / KO file. Returns UIDs, count, output_path, and an
    approx_tokens summary. If the probe fails, returns the errors to repair."""
    try:
        result = materializer.materialize_dataset(spec_id, instance_count, job_id)
        outcome = f"job_id={result['job_id']}" if "error" not in result else "probe_failed"
        audit_log.log_call("materialize_dataset", {"spec_id": spec_id, "instance_count": instance_count}, outcome)
        return result
    except SpecError as exc:
        audit_log.log_call("materialize_dataset", {"spec_id": spec_id}, f"rejected: {exc}")
        return {"error": str(exc), **({"job_id": exc.job_id} if exc.job_id else {})}


@mcp.tool()
def modify_dataset(study_uid: str, overrides: dict | None = None, per_instance: dict | None = None,
                   regenerate_uids: bool = True, confirm_destructive: bool = False,
                   job_id: str | None = None) -> dict:
    """Edit an existing PACS study's tags. Fetches EVERY instance across EVERY
    series of the study and preserves that structure in the result (each source
    series maps to its own new series) — a multi-series CT/MR study or a
    multi-instance US cine study comes out with the same series layout it went
    in with. Default (regenerate_uids=True) writes a new derived study
    (non-destructive). regenerate_uids=False keeps the original UIDs
    (destructive in-place overwrite) and requires confirm_destructive=True.

    - `overrides`: {Keyword: value} applied identically to every instance
      (e.g. {"PatientAge": "045Y"}).
    - `per_instance`: {Keyword: rule} applied per instance, indexed from 0
      *within each original series* (not across the whole study) — e.g. to
      progressively shift a position tag: {"ImagePositionPatient":
      {"rule": "increment", "delta": [0, 0, 0.5]}} adds 0.5mm to the Z
      component of each instance's *own existing* position, instance 0
      unchanged, instance 1 +0.5, instance 2 +1.0, etc. Other rule kinds:
      "linspace" (start/step from scratch), "const" (fixed value), "index+1".
    """
    if not regenerate_uids and not confirm_destructive:
        return {"error": "regenerate_uids=False is a destructive in-place overwrite. Confirm with the user, then retry with confirm_destructive=True."}
    try:
        result = modify.modify_dataset(study_uid, overrides, per_instance, regenerate_uids, job_id)
        audit_log.log_call("modify_dataset", {"study_uid": study_uid, "regenerate_uids": regenerate_uids, "count": result["count"]}, f"job_id={result['job_id']}")
        return result
    except SpecError as exc:
        audit_log.log_call("modify_dataset", {"study_uid": study_uid}, f"rejected: {exc}")
        return {"error": str(exc), **({"job_id": exc.job_id} if exc.job_id else {})}


@mcp.tool()
def generate_prior_study(study_uid: str, days_before: int, overrides: dict | None = None,
                         job_id: str | None = None) -> dict:
    """Generate a prior study for the same patient as `study_uid`, dated
    `days_before` days earlier. A full replica of the reference study's
    structure — EVERY series and instance is cloned (each source series maps
    to its own new series in the prior), not a single representative instance
    reconstructed from scratch — so a multi-series CT/MR study or a
    multi-instance US cine study gets a prior with the same series layout.
    PatientID/PatientName are reused as-is; the prior gets its own fresh
    StudyInstanceUID/SeriesInstanceUIDs/SOPInstanceUIDs, never edits the
    original. `overrides` (optional) is applied identically to every instance
    on top of the date shift, same as modify_dataset's `overrides`.

    Does NOT store — call store_to_pacs after confirming with the user, same
    as modify_dataset/materialize_dataset."""
    try:
        result = priors.generate_prior_study(study_uid, days_before, overrides, job_id)
        audit_log.log_call("generate_prior_study", {"study_uid": study_uid, "days_before": days_before, "count": result["count"]}, f"job_id={result['job_id']}")
        return result
    except SpecError as exc:
        audit_log.log_call("generate_prior_study", {"study_uid": study_uid}, f"rejected: {exc}")
        return {"error": str(exc), **({"job_id": exc.job_id} if exc.job_id else {})}


# --- recipes ----------------------------------------------------------------
@mcp.tool()
def find_recipe(modality: str, body_part: str | None = None, orientation: str | None = None,
                enhanced: bool = False, contrast: bool = False, localizer: bool = False) -> dict:
    """Look up a cached recipe (a previously-validated Generation Spec) for this
    kind of request. On a hit, pass the returned `spec` to validate_spec then
    materialize_dataset — skipping the authoring step. Returns {found: false} on
    a miss (then author from the KB)."""
    sop = kb.resolve_sop_class(modality=modality, enhanced=enhanced)
    rec = recipe_store.find_recipe(modality, body_part, orientation, sop, {"contrast": contrast, "localizer": localizer})
    audit_log.log_call("find_recipe", {"modality": modality, "body_part": body_part}, "hit" if rec else "miss")
    if not rec:
        return {"found": False}
    return {"found": True, "key": rec["key"], "spec": rec["spec"]}


@mcp.tool()
def list_recipes(modality: str | None = None) -> list[dict]:
    """List cached recipes (auto-grown from successful generations), optionally
    filtered by modality. Replaces the old template catalog browse."""
    results = recipe_store.list_recipes(modality)
    audit_log.log_call("list_recipes", {"modality": modality}, f"{len(results)} results")
    return results


# --- validate / store / query / status -------------------------------------
def _job_id_from_path(path: str) -> str | None:
    candidate = Path(path).name
    return candidate if job_registry.get_job(candidate) is not None else None


@mcp.tool()
def validate_dataset(path: str | None = None, study_uid: str | None = None) -> dict:
    """Validate a folder of generated instances (path=) or a PACS study (study_uid=):
    IOD conformance (dicom-validator), cross-instance structural checks, and
    file readability."""
    result = validator.validate_dataset(path, study_uid)
    outcome = "passed" if result.get("passed") else "failed"
    audit_log.log_call("validate_dataset", {"path": path, "study_uid": study_uid}, outcome)
    if path:
        job_id = _job_id_from_path(path)
        if job_id:
            job_registry.update_job(job_id, message=f"validation {outcome}")
    return result


@mcp.tool()
def store_to_pacs(path: str, confirm_store: bool = False) -> dict:
    """Store a folder of validated instances to the PACS (storescu, Orthanc REST
    fallback). Requires confirm_store=True — show the user the validation result
    and what's about to be stored first."""
    if not confirm_store:
        return {"error": "store_to_pacs requires confirm_store=True. Show the validation result and get explicit confirmation, then retry."}
    result = pacs_store.store_to_pacs(path)
    audit_log.log_call("store_to_pacs", {"path": path}, f"stored={result['stored_count']} failed={result['failed_count']}")
    job_id = _job_id_from_path(path)
    if job_id:
        if result["failed_count"] > 0 or result.get("error"):
            job_registry.update_job(job_id, state="failed", message=result.get("error") or f"store failed for {result['failed_count']} instance(s)")
        else:
            job_registry.update_job(job_id, state="completed", message=f"stored {result['stored_count']} instance(s)")
    return result


@mcp.tool()
def list_pacs_studies(modality: str | None = None, patient_name: str | None = None, date_range: str | None = None) -> list[dict]:
    """List studies in the configured PACS (Orthanc), optionally filtered."""
    try:
        results = orthanc_client.find_studies(modality, patient_name, date_range)
        audit_log.log_call("list_pacs_studies", {"modality": modality, "date_range": date_range}, f"{len(results)} results")
        return results
    except Exception as exc:
        audit_log.log_call("list_pacs_studies", {"modality": modality}, f"error: {exc}")
        return [{"error": str(exc)}]


@mcp.tool()
def list_series_instances(study_uid: str, series_uid: str | None = None) -> dict:
    """Enumerate stored instances of a PACS study (optionally one series) — returns
    each instance's series_uid/sop_class_uid/sop_instance_uid/instance_number. Use
    this to get the concrete instance UIDs a PR/KO `references` block needs to
    point at, or to find a specific series's first image — never read a .dcm file
    directly for this. Errors if the study/series isn't in the PACS yet (store it
    first)."""
    try:
        results = orthanc_client.list_series_instances(study_uid, series_uid)
        audit_log.log_call("list_series_instances", {"study_uid": study_uid, "series_uid": series_uid}, f"{len(results)} instances")
        return {"instances": results}
    except ValueError as exc:
        audit_log.log_call("list_series_instances", {"study_uid": study_uid, "series_uid": series_uid}, f"error: {exc}")
        return {"error": str(exc)}


@mcp.tool()
def check_pacs_feature(tag: str, value: str | None = None, modality: str | None = None, date_range: str | None = None) -> dict:
    """Check whether any PACS study has a given DICOM tag (optionally a value).
    Resolve the user's phrase to the correct DICOM keyword yourself first. Narrow
    with modality/date_range on a large PACS."""
    try:
        result = feature_lookup.check_pacs_feature(tag, value, modality, date_range)
        audit_log.log_call("check_pacs_feature", {"tag": tag, "value": value, "modality": modality}, f"match_count={result['match_count']}")
        return result
    except feature_lookup.FeatureLookupError as exc:
        audit_log.log_call("check_pacs_feature", {"tag": tag}, f"rejected: {exc}")
        return {"error": str(exc)}


@mcp.tool()
def get_job_status(job_id: str) -> dict:
    """Look up the state/progress of a materialize/modify job by job_id."""
    job = job_registry.get_job(job_id)
    if job is None:
        return {"error": f"No job found with id '{job_id}'"}
    audit_log.log_call("get_job_status", {"job_id": job_id}, job["state"])
    return job


@mcp.tool()
def health_check() -> dict:
    """Environment health check: MCP server, DCMTK binaries, PACS reachability, KB edition."""
    orthanc_ok, orthanc_message = orthanc_client.is_reachable()
    result = {
        "mcp_server": "ok",
        "kb_edition": kb.kb_edition(),
        "recipes_dir": str(config.RECIPES_DIR),
        "orthanc_reachable": orthanc_ok,
        "orthanc_message": orthanc_message,
        "dcmtk_binaries_on_path": {name: (shutil.which(name) is not None) for name in DCMTK_BINARIES},
    }
    audit_log.log_call("health_check", {}, f"orthanc_reachable={orthanc_ok}")
    return result


if __name__ == "__main__":
    mcp.run()
