"""store_to_pacs — solution-design.md §11.

Default path: `storescu` batch C-STORE against the configured PACS AE.
Falls back to the Orthanc REST upload (documented as the Orthanc-specific
alternative in §11) if storescu isn't on PATH.
"""

import shutil
import subprocess
from pathlib import Path

import config
import orthanc_client


def _storescu_path() -> str | None:
    return shutil.which("storescu")


def _store_via_storescu(files: list[Path]) -> tuple[int, list[str]]:
    exe = _storescu_path()
    failed: list[str] = []
    stored = 0
    for f in files:
        proc = subprocess.run(
            [exe, "-aet", "PIXELATLAS", "-aec", "ORTHANC", config.ORTHANC_DICOM_HOST, str(config.ORTHANC_DICOM_PORT), str(f)],
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0:
            stored += 1
        else:
            failed.append(f.name)
    return stored, failed


def _store_via_rest(files: list[Path]) -> tuple[int, list[str]]:
    stored = 0
    failed: list[str] = []
    for f in files:
        try:
            orthanc_client.upload_instance(f.read_bytes())
            stored += 1
        except Exception:
            failed.append(f.name)
    return stored, failed


def store_to_pacs(path: str) -> dict:
    folder = Path(path)
    files = sorted(folder.glob("*.dcm"))
    if not files:
        return {"stored_count": 0, "failed_count": 0, "failed_files": [], "method": "none", "error": f"No .dcm files found in '{path}'"}

    if _storescu_path() is not None:
        stored, failed = _store_via_storescu(files)
        method = "storescu"
    else:
        stored, failed = _store_via_rest(files)
        method = "orthanc_rest"

    return {
        "stored_count": stored,
        "failed_count": len(failed),
        "failed_files": failed,
        "method": method,
    }
