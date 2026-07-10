"""Pixel Atlas MCP server — entry point.

Phase 1: read-only tools (list_templates, get_template_info, list_pacs_studies,
get_job_status, health_check). Phase 2 adds the generation pipeline
(resolve_seed, generate_dataset, validate_dataset, store_to_pacs).
modify_dataset lands on Phase 3. See docs/execution-plan-phases1-3.md.
"""

import logging
import shutil
import sys
from pathlib import Path

# dicom_validator.spec_reader.edition_reader attaches a StreamHandler(sys.stdout)
# to the ROOT logger the first time it runs, *if* the root logger has no
# handlers yet — which would leak its log messages onto stdout and corrupt the
# MCP server's stdio JSON-RPC channel. Attaching a stderr handler here first
# means that check finds a handler already present and skips adding its own.
logging.getLogger().addHandler(logging.StreamHandler(sys.stderr))

from mcp.server.fastmcp import FastMCP

import audit_log
import config
import feature_lookup
import generator
import iod_lookup
import job_registry
import modify
import orthanc_client
import pacs_store
import seed_resolver
import templates as template_catalog
import validator

mcp = FastMCP("pixel-atlas")


# Reported by health_check for visibility, but only storescu/dcmftest are
# actually invoked by this codebase (pacs_store.py / validator.py). dcmodify's
# job is done in-process by pydicom (generator.py); findscu is unneeded since
# orthanc_client.py talks to Orthanc's REST API for all PACS queries;
# dciodvfy ships in dicom3tools, not DCMTK, and isn't installed here.
DCMTK_BINARIES = ["dcmodify", "dciodvfy", "storescu", "findscu", "dcmftest"]


@mcp.tool()
def list_templates(modality: str | None = None, body_part: str | None = None, orientation: str | None = None) -> list[dict]:
    """List tag templates from the catalog, optionally filtered by modality/body_part/orientation."""
    results = template_catalog.list_templates(modality, body_part, orientation)[:20]
    audit_log.log_call("list_templates", {"modality": modality, "body_part": body_part, "orientation": orientation}, f"{len(results)} results")
    return results


@mcp.tool()
def get_template_info(template_id: str) -> dict:
    """Get tag rules and protected_tags for one template (no seed/pixel data).

    protected_tags are the only tags NOT safe to pass to generate_dataset's/
    modify_dataset's `overrides` — tags this generator computes itself
    per-instance (e.g. InstanceNumber, and template-dependent sequence tags
    like SliceLocation/ImagePositionPatient) or UIDs it always regenerates
    (StudyInstanceUID/SeriesInstanceUID/SOPInstanceUID). Any other tag valid
    for this template's IOD (see get_iod_requirements) may be overridden.
    """
    info = template_catalog.get_template_info(template_id)
    if info is None:
        audit_log.log_call("get_template_info", {"template_id": template_id}, "not_found")
        return {"error": f"No template found with id '{template_id}'"}
    audit_log.log_call("get_template_info", {"template_id": template_id}, "found")
    return info


@mcp.tool()
def get_iod_requirements(template_id: str | None = None, sop_class_uid: str | None = None) -> dict:
    """Look up the DICOM IOD knowledge base for a template or a SOP Class UID:
    every module the IOD requires (M), conditionally requires (C), or allows (U),
    and for M/C modules, every tag in that module with its Type (1/1C/2/2C/3),
    VR, and any machine-checkable condition.

    Pass either template_id (e.g. "ct-image") or sop_class_uid directly — the
    latter is how modify_dataset-style checks work against an arbitrary PACS
    study's actual SOP Class, not just a catalog template. Use this before
    proposing a tag addition/edit (is the tag legitimate for this IOD? what's
    its type?) or before generating (what's mandatory beyond tag_rules?).
    """
    spec = iod_lookup.load_iod_spec(template_id=template_id, sop_class_uid=sop_class_uid)
    if spec is None:
        audit_log.log_call("get_iod_requirements", {"template_id": template_id, "sop_class_uid": sop_class_uid}, "not_found")
        return {"error": f"No IOD knowledge base entry for template_id={template_id!r} sop_class_uid={sop_class_uid!r}"}
    audit_log.log_call("get_iod_requirements", {"template_id": template_id, "sop_class_uid": sop_class_uid}, "found")
    return spec


@mcp.tool()
def list_pacs_studies(modality: str | None = None, patient_name: str | None = None, date_range: str | None = None) -> list[dict]:
    """List studies in the configured PACS (Orthanc), optionally filtered."""
    try:
        results = orthanc_client.find_studies(modality, patient_name, date_range)
        audit_log.log_call("list_pacs_studies", {"modality": modality, "patient_name": bool(patient_name), "date_range": date_range}, f"{len(results)} results")
        return results
    except Exception as exc:
        audit_log.log_call("list_pacs_studies", {"modality": modality}, f"error: {exc}")
        return [{"error": str(exc)}]


@mcp.tool()
def get_job_status(job_id: str) -> dict:
    """Look up the state/progress of a generation/modify job by job_id."""
    job = job_registry.get_job(job_id)
    if job is None:
        audit_log.log_call("get_job_status", {"job_id": job_id}, "not_found")
        return {"error": f"No job found with id '{job_id}'"}
    audit_log.log_call("get_job_status", {"job_id": job_id}, job["state"])
    return job


@mcp.tool()
def health_check() -> dict:
    """Environment health check for /status with no job id: MCP server, DCMTK binaries, PACS reachability."""
    orthanc_ok, orthanc_message = orthanc_client.is_reachable()
    dcmtk_status = {name: (shutil.which(name) is not None) for name in DCMTK_BINARIES}
    result = {
        "mcp_server": "ok",
        "templates_dir": str(config.TEMPLATES_DIR),
        "template_count": len(template_catalog.load_catalog()),
        "orthanc_reachable": orthanc_ok,
        "orthanc_message": orthanc_message,
        "dcmtk_binaries_on_path": dcmtk_status,
    }
    audit_log.log_call("health_check", {}, f"orthanc_reachable={orthanc_ok}")
    return result


@mcp.tool()
def resolve_seed(modality: str, body_part: str | None = None, orientation: str | None = None) -> dict:
    """PACS-first, template-fallback seed resolution (solution-design.md §3). Call before generate_dataset."""
    result = seed_resolver.resolve_seed(modality, body_part, orientation)
    audit_log.log_call("resolve_seed", {"modality": modality, "body_part": body_part, "orientation": orientation}, result["source_type"])
    return result


@mcp.tool()
def generate_dataset(
    template_id: str,
    seed_source: dict,
    instance_count: int,
    overrides: dict | None = None,
    job_id: str | None = None,
    prior_of_study_uid: str | None = None,
    days_before: int | None = None,
) -> dict:
    """Generate instance_count new DICOM instances from a resolved seed, writing them to a staging folder.

    seed_source must come from a prior resolve_seed call, e.g.
    {"type": "template", "template_id": "ct-image"} or {"type": "pacs", "study_uid": "..."}.

    To generate a *prior* study for an existing patient (e.g. "generate a prior
    CT from 90 days before this study, for comparison"), pass prior_of_study_uid
    (the reference study's StudyInstanceUID) and days_before (a positive
    integer). The reference study's PatientID/PatientName/StudyDate are reused
    (offset earlier by days_before) instead of drawing a new synthetic patient;
    the generated study still gets its own independent
    StudyInstanceUID/SeriesInstanceUID/SOPInstanceUIDs.

    overrides may set any tag valid for the template's IOD except its
    protected_tags (see get_template_info). Note: pixel-data-derived tags
    (e.g. PixelSpacing, RescaleSlope) can be overridden at the tag level, but
    the actual pixel array is not recomputed to match — a known gap, not
    something this call catches.
    """
    try:
        result = generator.generate_dataset(
            template_id, seed_source, instance_count, overrides, job_id, prior_of_study_uid, days_before
        )
        audit_log.log_call(
            "generate_dataset",
            {
                "template_id": template_id,
                "seed_source_type": seed_source.get("type"),
                "instance_count": instance_count,
                "prior_of_study_uid": prior_of_study_uid,
            },
            f"job_id={result['job_id']}",
        )
        return result
    except generator.PlanError as exc:
        audit_log.log_call("generate_dataset", {"template_id": template_id, "instance_count": instance_count}, f"rejected: {exc}")
        error_result = {"error": str(exc)}
        if exc.job_id:
            error_result["job_id"] = exc.job_id
        return error_result


def _job_id_from_path(path: str) -> str | None:
    """Staging folders are always named after the job that produced them
    (staging/<job_id>/) — infer job_id from the folder name so store_to_pacs/
    validate_dataset can update that job's registry entry without needing an
    explicit job_id parameter on every call. Returns None if the folder name
    isn't a known job (e.g. a study_uid-backed validate_dataset temp folder)."""
    candidate = Path(path).name
    return candidate if job_registry.get_job(candidate) is not None else None


@mcp.tool()
def validate_dataset(path: str | None = None, study_uid: str | None = None) -> dict:
    """Validate a folder of generated/modified DICOM instances, or a study already in the PACS.

    Give exactly one of path (a job's staging output folder) or study_uid (an
    existing PACS study — instances are fetched into a throwaway folder first).
    Checks IOD conformance (dicom-validator), cross-instance structural
    consistency, and basic file readability (dcmftest) — see validator.py for
    full scope.
    """
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
    """Store a folder of validated DICOM instances to the configured PACS (storescu, or Orthanc REST fallback).

    Requires confirm_store=True. Storing is the one step in any /generate or
    /modify flow that actually reaches the shared PACS — always show the user
    the validation result and a summary of what's about to be stored (target
    study, instance count, seed/override source), and get their explicit go-ahead
    before calling this. The call is rejected without confirm_store=True, so
    this can't happen by accident even if that confirmation step gets skipped
    upstream.
    """
    if not confirm_store:
        return {
            "error": (
                "store_to_pacs requires confirm_store=True. Show the user the validation "
                "result and what's about to be stored, get explicit confirmation, then retry "
                "with confirm_store=True."
            )
        }
    result = pacs_store.store_to_pacs(path)
    audit_log.log_call("store_to_pacs", {"path": path}, f"stored={result['stored_count']} failed={result['failed_count']}")

    job_id = _job_id_from_path(path)
    if job_id:
        if result["failed_count"] > 0 or result.get("error"):
            job_registry.update_job(
                job_id, state="failed", message=result.get("error") or f"store failed for {result['failed_count']} instance(s)"
            )
        else:
            job_registry.update_job(job_id, state="completed", message=f"stored {result['stored_count']} instance(s)")
    return result


@mcp.tool()
def modify_dataset(
    study_uid: str,
    overrides: dict | None = None,
    regenerate_uids: bool = True,
    confirm_destructive: bool = False,
    job_id: str | None = None,
) -> dict:
    """Modify an existing PACS study's tags (solution-design.md §9).

    Default (regenerate_uids=True): fetches the study, applies overrides, and
    writes a new, independent derived study — non-destructive, the original
    is untouched in the PACS.

    regenerate_uids=False keeps the original UIDs, so storing the result is
    intended to overwrite the existing PACS copy in place. This is
    DESTRUCTIVE. Only call it this way after the user has explicitly
    confirmed the overwrite in conversation — and you must also pass
    confirm_destructive=True; the call is rejected otherwise, so this can't
    happen by accident even if the confirmation step gets skipped upstream.

    overrides may set any tag valid for the study's actual IOD except tags
    this generator always manages itself (UIDs, and — if a matching template
    is authored — that template's sequence-derived tags; see
    get_template_info's protected_tags for the closest matching template).
    """
    if not regenerate_uids and not confirm_destructive:
        return {
            "error": (
                "regenerate_uids=False is a destructive in-place PACS overwrite. "
                "Confirm explicitly with the user first, then retry with confirm_destructive=True."
            )
        }
    try:
        result = modify.modify_dataset(study_uid, overrides, regenerate_uids, job_id)
        audit_log.log_call(
            "modify_dataset",
            {"study_uid": study_uid, "regenerate_uids": regenerate_uids, "instance_count": result["count"]},
            f"job_id={result['job_id']}",
        )
        return result
    except modify.PlanError as exc:
        audit_log.log_call("modify_dataset", {"study_uid": study_uid, "regenerate_uids": regenerate_uids}, f"rejected: {exc}")
        error_result = {"error": str(exc)}
        if exc.job_id:
            error_result["job_id"] = exc.job_id
        return error_result


@mcp.tool()
def check_pacs_feature(
    tag: str,
    value: str | None = None,
    modality: str | None = None,
    date_range: str | None = None,
) -> dict:
    """Check whether any study already in the PACS has a given DICOM tag (optionally with a specific value).

    Generic lookup, not limited to any specific tag — e.g. "does any CT study
    have a Modality LUT Sequence" (tag="ModalityLUTSequence") or "is there a
    study with RescaleSlope=2" (tag="RescaleSlope", value="2"). Resolve the
    user's natural-language phrase to the correct DICOM keyword yourself
    before calling this — the tag can be given as that keyword (e.g.
    "RescaleSlope") or as "GGGG,EEEE" (e.g. "0028,3000" for Modality LUT
    Sequence). Checks one representative instance per candidate study; narrow
    with modality/date_range first on a large PACS, since this can't use
    Orthanc's fast tag index the way modality/date lookups can. Sequence tags
    are supported for presence only (e.g. "is ModalityLUTSequence present"),
    not for matching a value inside the sequence's items.
    """
    try:
        result = feature_lookup.check_pacs_feature(tag, value, modality, date_range)
        audit_log.log_call(
            "check_pacs_feature",
            {"tag": tag, "value": value, "modality": modality},
            f"match_count={result['match_count']}",
        )
        return result
    except feature_lookup.FeatureLookupError as exc:
        audit_log.log_call("check_pacs_feature", {"tag": tag}, f"rejected: {exc}")
        return {"error": str(exc)}


if __name__ == "__main__":
    mcp.run()
