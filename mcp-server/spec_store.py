"""In-memory store for validated Generation Specs (the "order slips").

The AI authors a spec once; validate_spec stores it here and returns a short
`spec_id`. materialize_dataset then references that id instead of the whole spec
being re-sent as a tool argument — the token-economy "handle" pattern.

In-memory only (like job_registry) — lost on server restart, acceptable for the
local dev tool. The Generation Spec shape is documented in
docs/solution-design.md §5.
"""

import uuid

_SPECS: dict[str, dict] = {}


class SpecError(ValueError):
    """A Generation Spec failed validation or could not be materialized.

    job_id is attached (by the caller) once a job has been registered, so a
    failed job stays traceable via get_job_status.
    """

    def __init__(self, message: str, job_id: str | None = None):
        super().__init__(message)
        self.job_id = job_id


def store(spec: dict) -> str:
    spec_id = f"spec-{uuid.uuid4().hex[:8]}"
    _SPECS[spec_id] = spec
    return spec_id


def get(spec_id: str) -> dict | None:
    return _SPECS.get(spec_id)


def apply_diff(spec_id: str, diff: dict) -> str | None:
    """Shallow-merge a repair diff onto a stored spec and store the result as a
    new spec_id (so repairs don't resend the whole slip). Nested dicts
    (attributes/overrides/etc.) are merged key-by-key; None means the base spec
    is unknown."""
    base = _SPECS.get(spec_id)
    if base is None:
        return None
    merged = {**base}
    for key, val in diff.items():
        if isinstance(val, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **val}
        else:
            merged[key] = val
    return store(merged)
