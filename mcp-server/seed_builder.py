"""Pixel synthesis + base-dataset builder for the IOD (no-PACS-seed) path.

The Materializer owns the whole Image Pixel module (decision #2): it builds a
minimal base dataset from a SOP Class + the spec's `pixel` directive, synthesizing
pixel bytes in-process (never through the LLM). Modality-agnostic — the pixel shape
comes entirely from the directive.
"""

import numpy as np
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

OID_ROOT = "1.2.826.0.1.3680043.10.588."

PIXEL_DEFAULTS = {
    "rows": 64, "columns": 64, "samplesPerPixel": 1,
    "photometricInterpretation": "MONOCHROME2", "bitsAllocated": 16,
    "generator": "noise",
}


def _synth_frame(rows, cols, spp, max_value, dtype, generator, frame_idx=0):
    if generator == "gradient":
        ramp = np.linspace(0, max_value - 1, cols, dtype=dtype)
        arr = np.tile(ramp, (rows, 1))
    elif generator == "phantom":
        yy, xx = np.ogrid[:rows, :cols]
        cy, cx = rows / 2, cols / 2
        mask = (xx - cx) ** 2 + (yy - cy) ** 2 <= (min(rows, cols) / 3) ** 2
        arr = np.where(mask, int(max_value * 0.7), int(max_value * 0.1)).astype(dtype)
    else:  # noise
        rng = np.random.default_rng(seed=42 + frame_idx)
        arr = rng.integers(0, max_value, size=(rows, cols), dtype=dtype)
    if spp > 1:
        arr = np.stack([arr] * spp, axis=-1)
    return arr


def synth_pixels(pixel: dict, frames: int = 1) -> tuple[np.ndarray, dict]:
    """Return (pixel_array, pixel_module_tags). pixel_array is (rows,cols[,spp]) for
    one frame or (frames,rows,cols[,spp]) for many."""
    p = {**PIXEL_DEFAULTS, **(pixel or {})}
    rows, cols, spp = int(p["rows"]), int(p["columns"]), int(p["samplesPerPixel"])
    ba = int(p["bitsAllocated"])
    bs = int(p.get("bitsStored", 12 if ba == 16 else ba))
    dtype = np.uint16 if ba == 16 else np.uint8
    max_value = 2 ** bs

    if frames > 1:
        stacked = np.stack([_synth_frame(rows, cols, spp, max_value, dtype, p["generator"], i) for i in range(frames)])
        pixel_array = stacked
    else:
        pixel_array = _synth_frame(rows, cols, spp, max_value, dtype, p["generator"])

    tags = {
        "Rows": rows, "Columns": cols, "SamplesPerPixel": spp,
        "PhotometricInterpretation": p["photometricInterpretation"],
        "BitsAllocated": ba, "BitsStored": bs, "HighBit": bs - 1,
        "PixelRepresentation": 0,
    }
    if spp > 1:
        tags["PlanarConfiguration"] = 0
    return pixel_array, tags


def build_base(sop_class_uid: str, modality: str | None, pixel: dict | None,
               frames: int = 1, with_pixels: bool = True,
               include_frame_of_reference: bool = False) -> FileDataset:
    """Minimal base dataset: file_meta + core UIDs + Modality (+ pixel module if
    with_pixels). Reference objects (PR/KO) pass with_pixels=False."""
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = sop_class_uid
    file_meta.MediaStorageSOPInstanceUID = generate_uid(prefix=OID_ROOT)
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds = FileDataset(None, {}, file_meta=file_meta, preamble=b"\0" * 128)
    ds.SOPClassUID = sop_class_uid
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = generate_uid(prefix=OID_ROOT)
    ds.SeriesInstanceUID = generate_uid(prefix=OID_ROOT)
    if include_frame_of_reference:
        ds.FrameOfReferenceUID = generate_uid(prefix=OID_ROOT)
    if modality:
        ds.Modality = modality

    if with_pixels:
        pixel_array, tags = synth_pixels(pixel or {}, frames=frames)
        for k, v in tags.items():
            setattr(ds, k, v)
        if frames > 1:
            ds.NumberOfFrames = frames
        ds.PixelData = pixel_array.tobytes()

    return ds
