"""Shared helpers for applying a keyword->value map onto a pydicom Dataset.

Used by both spec_validator (to VR-check values on a scratch dataset) and the
materializer (to actually write them). A Generation Spec's `attributes`/
`overrides`/`identity` are plain keyword->value maps; sequence-VR tags carry a
list of plain dicts, which we convert to a real pydicom Sequence.
"""

from contextlib import contextmanager

import pydicom
import pydicom.config as pydicom_config

from spec_store import SpecError


@contextmanager
def strict_value_validation():
    """pydicom only *warns* on an invalid value for a tag's VR by default and
    stores it anyway. Scoped to value application (not dataset loading), this
    makes that case raise instead, so a bad AI/user value is rejected loudly."""
    previous = pydicom_config.settings.reading_validation_mode
    pydicom_config.settings.reading_validation_mode = pydicom_config.RAISE
    try:
        yield
    finally:
        pydicom_config.settings.reading_validation_mode = previous


def coerce_value(value):
    """Convert a list-of-dict (a sequence-VR value expressed in JSON) into a real
    pydicom Sequence, recursively. Scalars and lists of scalars pass through."""
    if isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
        items = []
        for d in value:
            item = pydicom.Dataset()
            for k, v in d.items():
                setattr(item, k, coerce_value(v))
            items.append(item)
        return pydicom.Sequence(items)
    return value


def apply_value_map(ds: pydicom.Dataset, mapping: dict) -> None:
    """Apply keyword->value pairs with strict VR validation, raising SpecError
    (naming the tag) on a bad value instead of silently writing garbage."""
    for keyword, value in (mapping or {}).items():
        try:
            with strict_value_validation():
                setattr(ds, keyword, coerce_value(value))
        except (ValueError, TypeError) as exc:
            raise SpecError(f"Invalid value for tag '{keyword}': {value!r} — {exc}") from exc
