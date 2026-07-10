"""Environment-driven configuration for the Pixel Atlas MCP server."""

import os
from pathlib import Path

TEMPLATES_DIR = Path(os.environ.get("PIXEL_ATLAS_TEMPLATES", Path(__file__).parent.parent / "templates"))
STAGING_DIR = Path(os.environ.get("PIXEL_ATLAS_STAGING", Path(__file__).parent.parent / "staging"))
LOG_DIR = Path(os.environ.get("PIXEL_ATLAS_LOG_DIR", Path(__file__).parent.parent / ".pixel-atlas" / "logs"))

ORTHANC_URL = os.environ.get("ORTHANC_URL", "http://localhost:8042")
ORTHANC_USER = os.environ.get("ORTHANC_USER", "orthanc")
ORTHANC_PASSWORD = os.environ.get("ORTHANC_PASSWORD", "orthanc")
ORTHANC_DICOM_HOST = os.environ.get("ORTHANC_DICOM_HOST", "localhost")
ORTHANC_DICOM_PORT = int(os.environ.get("ORTHANC_DICOM_PORT", "4242"))

TEST_OID_ROOT = os.environ.get("PIXEL_ATLAS_OID_ROOT", "1.2.826.0.1.3680043.10.588")

# dicom-validator caches the downloaded DICOM standard docbook/JSON here (its own
# default is the same path) — kept as an explicit config value so it's overridable
# like everything else in this file, not left to dicom-validator's internal default.
DICOM_VALIDATOR_STANDARD_PATH = Path(os.environ.get("DICOM_VALIDATOR_STANDARD_PATH", str(Path.home() / "dicom-validator")))
