"""Generate (or regenerate) a template's pixel-only fallback seed instance.

One generic script for every modality — the seed only needs to carry pixel
data and be a loadable file (see mcp-server/seed_builder.py); everything that
makes it a *conformant* IOD instance comes from the template's manifest.yaml
(tag_rules) and iod_spec.yaml, applied by generator.py at generation time.
Any modality-specific pixel shape (bit depth, samples per pixel, whether a
Frame of Reference UID is needed) is a `seed_params` override in that
template's manifest.yaml, not a modality-specific script.

Usage (from repo root):
    python scripts/generate_seed.py <template_id>

Example:
    python scripts/generate_seed.py ct-image
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "mcp-server"))

import config  # noqa: E402
import templates as template_catalog  # noqa: E402
from seed_builder import build_minimal_seed, write_seed  # noqa: E402


def main() -> None:
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)

    template_id = sys.argv[1]
    manifest = template_catalog.load_manifest(template_id)
    if manifest is None:
        print(f"No template found with id '{template_id}'")
        sys.exit(1)

    entry = template_catalog.find_catalog_entry(template_id)
    seed_params = manifest.get("seed_params") or {}

    ds = build_minimal_seed(
        sop_class_uid=manifest["sop_class_uid"],
        modality=manifest["modality"],
        **seed_params,
    )
    out_dir = config.TEMPLATES_DIR / entry["path"] / "seed"
    out_path = write_seed(ds, out_dir)
    print(f"Wrote synthetic seed instance for '{template_id}' to {out_path}")


if __name__ == "__main__":
    main()
