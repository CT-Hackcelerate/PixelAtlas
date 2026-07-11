"""Recipe cache — auto-grown store of validated Generation Specs (replaces the
hand-authored template catalog).

A recipe is keyed by the coarse structural signature (decision #7):
  modality + body_part + orientation + SOP Class + a few module-affecting flags
  (contrast, localizer). User overrides are NOT part of the key — they are
  re-applied fresh at materialization. On a matching request the agent loads the
  recipe and skips authoring + grounding entirely.

Recipes are plain JSON files under config.RECIPES_DIR so they stay
human-reviewable and diffable, and are versioned by KB edition.
"""

import json
import re

import config

_FLAG_KEYS = ("contrast", "localizer")


def _norm(v) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(v or "").strip().lower()).strip("-") or "any"


def recipe_key(modality=None, body_part=None, orientation=None, sop_class_uid=None, flags=None) -> str:
    flag_part = "+".join(f for f in _FLAG_KEYS if (flags or {}).get(f)) or "none"
    return "__".join([
        _norm(modality), _norm(body_part), _norm(orientation),
        _norm(sop_class_uid), flag_part,
    ])


def _path(key: str):
    return config.RECIPES_DIR / f"{key}.json"


def save_recipe(spec: dict, *, body_part=None, orientation=None, flags=None) -> str:
    req = spec.get("request") or {}
    sop = (req.get("seedSource") or {}).get("sopClassUID")
    key = recipe_key(req.get("modality"), body_part, orientation, sop, flags)
    config.RECIPES_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "key": key,
        "modality": req.get("modality"),
        "body_part": body_part,
        "orientation": orientation,
        "sop_class_uid": sop,
        "flags": {f: bool((flags or {}).get(f)) for f in _FLAG_KEYS},
        "kb_edition": (spec.get("provenance") or {}).get("kbEdition"),
        "spec": spec,
    }
    with open(_path(key), "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2)
    return key


def get_recipe(key: str) -> dict | None:
    p = _path(key)
    if not p.exists():
        return None
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def find_recipe(modality=None, body_part=None, orientation=None, sop_class_uid=None, flags=None) -> dict | None:
    return get_recipe(recipe_key(modality, body_part, orientation, sop_class_uid, flags))


def list_recipes(modality=None) -> list[dict]:
    if not config.RECIPES_DIR.exists():
        return []
    out = []
    for p in sorted(config.RECIPES_DIR.glob("*.json")):
        try:
            with open(p, "r", encoding="utf-8") as f:
                rec = json.load(f)
        except Exception:
            continue
        if modality and _norm(rec.get("modality")) != _norm(modality):
            continue
        out.append({k: rec.get(k) for k in ("key", "modality", "body_part", "orientation", "sop_class_uid", "flags", "kb_edition")})
    return out
