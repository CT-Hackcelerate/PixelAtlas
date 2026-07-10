"""Shared override-tag validation for generate_dataset and modify_dataset.

A tag is safe to accept as a user override if it isn't one this codebase
computes automatically per-instance/per-job — anything else valid for the
target IOD is fair game. Deliberately dependency-free (no imports of
generator/modify/templates/iod_lookup) so both generator.py and modify.py can
depend on it without a cycle; callers build `valid_keywords` themselves via
iod_lookup.all_tags() and pass it in.
"""

PROTECTED_IDENTITY_TAGS = {
    "StudyInstanceUID",
    "SeriesInstanceUID",
    "SOPInstanceUID",
    "MediaStorageSOPInstanceUID",
    # SOPClassUID/MediaStorageSOPClassUID are baked in at template-authoring
    # time (seed_builder.py) and identify which IOD this data even is —
    # letting an override change them would produce a dataset whose actual
    # class disagrees with the tag_rules/iod_spec it was built from.
    "SOPClassUID",
    "MediaStorageSOPClassUID",
}


class PlanError(ValueError):
    """Raised when a generation/modification plan fails validation (unknown
    tag, protected tag, bad seed_source, etc.).

    job_id is set (by the caller's except block) whenever the failure happened
    after a job was registered, so callers can still look up the failed job
    via get_job_status instead of losing track of it.
    """

    def __init__(self, message: str, job_id: str | None = None):
        super().__init__(message)
        self.job_id = job_id


def sequence_tag_keywords(tag_rules: dict) -> set[str]:
    """Tags a template computes per-instance via tag_rules.sequence formulas
    (e.g. CT's InstanceNumber/SliceLocation/ImagePositionPatient) — a single
    scalar override would apply the same value to every instance, destroying
    the per-instance progression these formulas exist to produce."""
    return set((tag_rules or {}).get("sequence", {}).keys())


def protected_tags_for(tag_rules: dict) -> set[str]:
    """Tags that can never be safely overridden with a single value: UIDs the
    generator regenerates unconditionally after tag_rules are applied, plus
    this template's own sequence-derived tags."""
    return PROTECTED_IDENTITY_TAGS | sequence_tag_keywords(tag_rules)


def validate_overrides(overrides: dict, tag_rules: dict, valid_keywords: set[str] | None) -> None:
    """valid_keywords is the set of real DICOM keywords for the target IOD
    (from iod_lookup.all_tags), or None if no IOD spec is available — in
    which case that check is skipped (same graceful degradation as before)."""
    protected = protected_tags_for(tag_rules)
    for tag in overrides:
        if tag in protected:
            raise PlanError(
                f"Tag '{tag}' can't be overridden with a single value — it's either "
                "computed per-instance by this template's sequence rules, or a UID "
                "the generator manages itself."
            )
        if valid_keywords is not None and tag not in valid_keywords:
            raise PlanError(f"Tag '{tag}' isn't a recognized tag for this IOD.")
