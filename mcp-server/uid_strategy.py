"""UID generation strategy — solution-design.md §7.

All UIDs are generated under the test OID root (config.TEST_OID_ROOT) and are
derived deterministically from (job_id, index): retrying a failed job with the
same job_id reproduces the same UID set instead of creating duplicates.
"""

from pydicom.uid import generate_uid

import config


def _prefix() -> str:
    root = config.TEST_OID_ROOT
    return root if root.endswith(".") else root + "."


def new_uid(job_id: str, index: str | int) -> str:
    """Deterministic UID for a given job_id + index (e.g. "study", "series", or an instance number)."""
    return generate_uid(prefix=_prefix(), entropy_srcs=[job_id, str(index)])
