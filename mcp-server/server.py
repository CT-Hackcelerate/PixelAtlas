"""Pixel Atlas MCP server — entry point (AI-driven redesign).

The agent authors (or extracts) a Generation Spec grounded on the Knowledge Base,
validates it (validate_spec -> spec_id), then materializes it. See
docs/ai-driven-comprehensive-plan.md for the full design.
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
    `full=True` if you truly need every tag's VR/enum detail for manual authoring;
    it is ~9k tokens, so avoid it. **For normal generation, prefer `generate_study`
    — you usually don't need this tool at all.** Covers image IODs + PR/KO; other
    IODs are reported unsupported.
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
def generate_study(modality: str, count: int = 1, body_part: str | None = None,
                   orientation: str | None = None, enhanced: bool = False,
                   overrides: dict | None = None, cine_rate: int | None = None,
                   study_uid: str | None = None) -> dict:
    """ONE-SHOT generation — the preferred path. Build a conformant synthetic study
    for `modality` (CT, MR, US, CR, DX, MG, NM, PT, XA, ...) and stage it, in a
    single call. The server builds a conformant baseline from defaults + fills any
    required tags itself — you do NOT need get_iod_requirements or to author a spec.

    - `enhanced=True` selects the multi-frame variant (e.g. US Multi-frame, Enhanced
      CT/MR); `count` then means number of frames. `cine_rate` sets the cine rate
      for classic multi-frame (e.g. US) — e.g. cine_rate=60.
    - `overrides` is an optional {Keyword: value} map for any tag you want to pin
      (e.g. {"PatientAge": "034Y", "BodyPartExamined": "LIVER"}).
    - `study_uid`: attach this new series to an existing PACS study instead of
      starting a new one — for a multi-series study (same or different modality
      per series). The study must already be stored (generate + store its first
      series first); the new series reuses that study's PatientID/PatientName/
      StudyDate automatically. Use `list_series_instances` afterwards if you then
      need this series' instance UIDs (e.g. to build a PR/KO referencing it).

    Returns {job_id, study_uid, count, frames?, output_path, validation, approx_tokens}.
    Does NOT store — call store_to_pacs after confirming with the user. On a failure
    it returns a precise error (missing tags), never a retry loop. For PR/KO or
    editing an existing study, use the spec/extract_spec flow instead.
    """
    import defaults
    try:
        sop = kb.resolve_sop_class(modality=modality, enhanced=enhanced)
        if not sop or not kb.is_supported(sop):
            return {"error": f"Modality '{modality}' has no supported image IOD. Supported: image IODs + PR/KO (PR/KO via the spec flow)."}
        if kb.is_reference_object(sop):
            return {"error": "PR/KO objects reference existing instances — use validate_spec/materialize_dataset with a `references` block, not generate_study."}

        spec = defaults.baseline_spec(modality, count, body_part, orientation, enhanced, overrides, study_uid)
        if kb.multiframe_kind(sop) == "classic" and cine_rate:
            spec["cine"] = {"cineRate": cine_rate}
        unfilled = defaults.autofill_required(spec)

        v = spec_validator.validate_spec(spec)
        if not v["grounded"]:
            audit_log.log_call("generate_study", {"modality": modality}, f"spec errors: {len(v['errors'])}")
            return {"error": "Could not build a valid spec — check overrides.", "errors": v["errors"]}

        # Probe-guided auto-repair: read exactly what the validator wants, fill it,
        # retry. Bounded (<=3 rounds) and stops the moment a round makes no progress
        # — deterministic, never an unbounded loop.
        result = materializer.materialize_dataset(v["spec_id"], instance_count=count)
        missing = []
        for _round in range(3):
            if "error" not in result:
                break
            job = result.get("job_id")
            missing = validator.iod_missing_tags(str(config.STAGING_DIR / job)) if job else []
            if not defaults.fill_missing_tags(spec, missing):
                break  # nothing top-level left to fill → stop, report precisely
            v = spec_validator.validate_spec(spec)
            if not v["grounded"]:
                break
            result = materializer.materialize_dataset(v["spec_id"], instance_count=count)
        if "error" in result:
            audit_log.log_call("generate_study", {"modality": modality}, "probe_failed")
            nested = sorted({t for _m, t, _c in missing if "/" in t})
            hint = (" This IOD needs nested sequence content this one-shot builder can't"
                    " auto-fill: " + ", ".join(nested) + ". Use the spec/validate_spec flow"
                    " to author it.") if nested else ""
            return {"error": result["error"] + hint, "probe_validation": result.get("probe_validation")}

        audit_log.log_call("generate_study", {"modality": modality, "count": count, "enhanced": enhanced}, f"job_id={result['job_id']}")
        return {
            "job_id": result["job_id"], "study_uid": result["study_uid"],
            "count": result.get("count"), "frames": result.get("frames"),
            "output_path": result["output_path"], "validation": "passed",
            "approx_tokens": result.get("approx_tokens"),
            "next_step": "Show the user this summary and, on confirmation, call store_to_pacs(output_path, confirm_store=True).",
        }
    except SpecError as exc:
        audit_log.log_call("generate_study", {"modality": modality}, f"error: {exc}")
        return {"error": str(exc)}


@mcp.tool()
def modify_dataset(study_uid: str, overrides: dict | None = None, regenerate_uids: bool = True,
                   confirm_destructive: bool = False, job_id: str | None = None) -> dict:
    """Edit an existing PACS study's tags. Default (regenerate_uids=True) writes a
    new derived study (non-destructive). regenerate_uids=False keeps the original
    UIDs (destructive in-place overwrite) and requires confirm_destructive=True."""
    if not regenerate_uids and not confirm_destructive:
        return {"error": "regenerate_uids=False is a destructive in-place overwrite. Confirm with the user, then retry with confirm_destructive=True."}
    try:
        result = modify.modify_dataset(study_uid, overrides, regenerate_uids, job_id)
        audit_log.log_call("modify_dataset", {"study_uid": study_uid, "regenerate_uids": regenerate_uids, "count": result["count"]}, f"job_id={result['job_id']}")
        return result
    except SpecError as exc:
        audit_log.log_call("modify_dataset", {"study_uid": study_uid}, f"rejected: {exc}")
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
