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


# --- per-instance rule evaluation --------------------------------------------
# Shared by fresh IOD-authored generation (materializer.py) and PACS-sourced
# edits (modify.py) — same rule language either way: a keyword->rule map,
# evaluated per instance index `i` against that instance's own dataset `ds`.
# A rule is always a dict with a "rule" key naming one of KNOWN_RULE_KINDS —
# spec_validator checks this shape at validate_spec time so a malformed rule
# is caught with a clear message instead of surfacing later as a silently
# no-op tag (or, worse, a cryptic crash once a downstream consumer assumes
# the tag was actually set).
KNOWN_RULE_KINDS = {"uid", "index+1", "linspace", "derive_from_slice", "const", "increment"}


def eval_rule(keyword: str, rule: dict, i: int, ds: pydicom.Dataset):
    kind = rule.get("rule", "")
    if kind in ("uid", "index+1") or kind.startswith("index"):
        if kind == "uid":
            return None  # UID rules are handled by the UID assignment step
        offset = rule.get("offset", 1 if kind == "index+1" else 0)
        return str(i + offset)
    if kind == "linspace":
        return str(round(rule.get("start", 0.0) + i * rule.get("step", 1.0), 3))
    if kind == "derive_from_slice":
        loc = float(getattr(ds, "SliceLocation", 0.0))
        return [-150.0, -150.0, loc]
    if kind == "const":
        return rule.get("value")
    if kind == "increment":
        # Progressive shift *relative to this instance's own current value* —
        # e.g. nudge ImagePositionPatient by 0.5mm per instance on an existing
        # (possibly PACS-sourced) dataset, rather than computing from scratch.
        current = getattr(ds, keyword, None)
        delta = rule.get("delta", 0)
        if isinstance(current, (list, pydicom.multival.MultiValue)):
            deltas = delta if isinstance(delta, list) else [delta] * len(current)
            if len(deltas) != len(current):
                raise SpecError(f"'increment' delta length {len(deltas)} doesn't match "
                                 f"'{keyword}' current length {len(current)}")
            return [round(float(v) + i * float(d), 6) for v, d in zip(current, deltas)]
        base = float(current) if current not in (None, "", []) else 0.0
        return str(round(base + i * float(delta), 6))
    raise SpecError(f"Unknown perInstance rule '{kind}' for tag '{keyword}'")


def apply_per_instance(ds: pydicom.Dataset, per_instance: dict, i: int) -> None:
    for keyword, rule in (per_instance or {}).items():
        if not isinstance(rule, dict):
            raise SpecError(
                f"perInstance['{keyword}'] must be a rule object like {{'rule': 'index+1'}}, "
                f"got {rule!r}"
            )
        value = eval_rule(keyword, rule, i, ds)
        if value is not None:
            apply_value_map(ds, {keyword: value})
