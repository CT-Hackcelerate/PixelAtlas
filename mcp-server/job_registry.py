"""In-memory job registry (v1 — no persistence across server restarts).

Populated by generate_dataset/modify_dataset (Phase 2+). Phase 1 only exposes
read access via get_job_status so /status has something real to call.
"""

_JOBS: dict[str, dict] = {}


def create_job(job_id: str, message: str = "") -> None:
    _JOBS[job_id] = {"state": "queued", "progress_pct": 0, "message": message}


def update_job(job_id: str, **fields) -> None:
    _JOBS.setdefault(job_id, {"state": "queued", "progress_pct": 0, "message": ""})
    _JOBS[job_id].update(fields)


def get_job(job_id: str) -> dict | None:
    return _JOBS.get(job_id)
