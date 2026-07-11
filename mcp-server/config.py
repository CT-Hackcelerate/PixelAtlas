"""Environment-driven configuration for the Pixel Atlas MCP server."""

import os
from pathlib import Path

STAGING_DIR = Path(os.environ.get("PIXEL_ATLAS_STAGING", Path(__file__).parent.parent / "staging"))
RECIPES_DIR = Path(os.environ.get("PIXEL_ATLAS_RECIPES", Path(__file__).parent.parent / "recipes"))
LOG_DIR = Path(os.environ.get("PIXEL_ATLAS_LOG_DIR", Path(__file__).parent.parent / ".pixel-atlas" / "logs"))

ORTHANC_URL = os.environ.get("ORTHANC_URL", "http://localhost:8042")
ORTHANC_USER = os.environ.get("ORTHANC_USER", "orthanc")
ORTHANC_PASSWORD = os.environ.get("ORTHANC_PASSWORD", "orthanc")
ORTHANC_DICOM_HOST = os.environ.get("ORTHANC_DICOM_HOST", "localhost")
ORTHANC_DICOM_PORT = int(os.environ.get("ORTHANC_DICOM_PORT", "4242"))

TEST_OID_ROOT = os.environ.get("PIXEL_ATLAS_OID_ROOT", "1.2.826.0.1.3680043.10.588")

# The DICOM Knowledge Base is committed in-repo (mcp-server/kb/<edition>/) rather
# than fetched over the network at runtime — pinned, reproducible, and available
# offline. Rebuild it with scripts/build_kb.py if the pinned edition changes.
KB_EDITION = os.environ.get("PIXEL_ATLAS_KB_EDITION", "2026c")
KB_DIR = Path(os.environ.get("PIXEL_ATLAS_KB_DIR", str(Path(__file__).parent / "kb")))
