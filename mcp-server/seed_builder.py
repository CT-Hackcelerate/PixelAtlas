"""Shared, modality-agnostic seed-file builder.

A template's seed/IM0001.dcm has exactly one job now: carry pixel data and be
a loadable, storable DICOM file. It is NOT the source of tag-conformance
truth — that's templates/<MODALITY>/<template_id>/iod_spec.yaml (the
knowledge base) plus each manifest.yaml's tag_rules. Because of that split,
one generic builder covers every modality — nothing modality-specific is
hand-baked here. The seed can be replaced with any other pixel-bearing file
at any time without affecting tag conformance.
"""

from pathlib import Path

import numpy as np
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

OID_ROOT = "1.2.826.0.1.3680043.10.588."


def build_minimal_seed(
    sop_class_uid: str,
    modality: str,
    rows: int = 64,
    cols: int = 64,
    samples_per_pixel: int = 1,
    photometric_interpretation: str = "MONOCHROME2",
    bits_allocated: int = 16,
    include_frame_of_reference: bool = False,
) -> FileDataset:
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = sop_class_uid
    file_meta.MediaStorageSOPInstanceUID = generate_uid(prefix=OID_ROOT)
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds = FileDataset(None, {}, file_meta=file_meta, preamble=b"\0" * 128)
    ds.is_little_endian = True
    ds.is_implicit_VR = False

    ds.SOPClassUID = sop_class_uid
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = generate_uid(prefix=OID_ROOT)
    ds.SeriesInstanceUID = generate_uid(prefix=OID_ROOT)
    if include_frame_of_reference:
        ds.FrameOfReferenceUID = generate_uid(prefix=OID_ROOT)

    ds.Modality = modality

    bits_stored = 12 if bits_allocated == 16 else bits_allocated
    high_bit = bits_stored - 1
    max_value = 2**bits_stored
    dtype = np.uint16 if bits_allocated == 16 else np.uint8

    rng = np.random.default_rng(seed=42)
    if samples_per_pixel == 1:
        pixel_array = rng.integers(0, max_value, size=(rows, cols), dtype=dtype)
    else:
        pixel_array = rng.integers(0, max_value, size=(rows, cols, samples_per_pixel), dtype=dtype)

    ds.Rows = rows
    ds.Columns = cols
    ds.SamplesPerPixel = samples_per_pixel
    ds.PhotometricInterpretation = photometric_interpretation
    ds.BitsAllocated = bits_allocated
    ds.BitsStored = bits_stored
    ds.HighBit = high_bit
    ds.PixelRepresentation = 0
    if samples_per_pixel > 1:
        ds.PlanarConfiguration = 0
    ds.PixelData = pixel_array.tobytes()

    return ds


def write_seed(ds: FileDataset, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "IM0001.dcm"
    ds.save_as(out_path, enforce_file_format=True)
    return out_path
