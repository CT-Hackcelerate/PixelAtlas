"""DICOM Knowledge Base — the reusable rulebook (AI-driven redesign).

Built from the DICOM standard data (DicomInfo) plus pydicom's data dictionary,
covering every standard SOP Class — no per-template YAML, no per-modality
Python. This replaces the old committed `iod_spec.yaml` files.

The KB itself is committed in-repo as plain JSON under `kb/<edition>/`
(dict_info.json/iod_info.json/module_info.json — the same three files
dicom-validator produces from the standard's docbook, pinned to one edition so
every environment sees identical, reproducible data with no network access or
first-run ~40s parse). Rebuild with scripts/build_kb.py if the pinned edition
changes.

DicomInfo shape (confirmed by the KB feasibility spike, dicom-validator 0.8.2):
  - .iods       {sop_class_uid: {title, modules, group_macros}}
  - .modules    {ref: {"(GGGG,EEEE)": {name, type, cond?, enums?, items?}, "include": [{ref}]}}
  - .dictionary {"(GGGG,EEEE)": {name, vr, vm, prop}}

`group_macros` and nested `items` are what let functional-group / macro
sequences (Enhanced CT/MR/PT frame-type + pixel-value-transformation, PR/KO
content trees, ...) be built generically from data — see macro_skeleton() and
mandatory_group_macros() — instead of one hand-written Python function per
modality.
"""

import json
import re

from pydicom.datadict import dictionary_keyword, dictionary_VR, tag_for_keyword

import config

_TAG_RE = re.compile(r"^\([0-9A-Fa-f]{4},[0-9A-Fa-f]{4}\)$")

# VR -> generic placeholder for a mandatory tag left unset (used by the
# functional-group skeleton builder below) — synthetic test data, so a
# structurally-valid placeholder is acceptable; real values always win when
# supplied via spec attributes/overrides.
VR_PLACEHOLDER = {
    "CS": "UNKNOWN", "LO": "UNKNOWN", "SH": "UNKNOWN", "PN": "UNKNOWN", "UC": "UNKNOWN",
    "LT": "UNKNOWN", "ST": "UNKNOWN", "UT": "UNKNOWN", "AE": "UNKNOWN",
    "DA": "20000101", "TM": "120000", "DT": "20000101120000", "AS": "000Y",
    "IS": "0", "DS": "0", "US": 0, "UL": 0, "SS": 0, "SL": 0, "FL": 0.0, "FD": 0.0,
}

_dicom_info = None


class DicomInfo:
    """Local stand-in for dicom_validator.validator.dicom_info.DicomInfo (a plain
    dataclass of the same three dicts) — avoids importing dicom_validator just to
    hold data we load ourselves from the committed JSON."""

    def __init__(self, dictionary: dict, iods: dict, modules: dict):
        self.dictionary = dictionary
        self.iods = iods
        self.modules = modules


def get_dicom_info():
    """Lazily load + cache the committed DICOM standard KB. Shared by validator.py
    (DicomFileValidator takes this same DicomInfo) so it's read from disk once
    per process."""
    global _dicom_info
    if _dicom_info is None:
        kb_path = config.KB_DIR / config.KB_EDITION
        with open(kb_path / "dict_info.json", encoding="utf8") as f:
            dictionary = json.load(f)
        with open(kb_path / "iod_info.json", encoding="utf8") as f:
            iods = json.load(f)
        with open(kb_path / "module_info.json", encoding="utf8") as f:
            modules = json.load(f)
        _dicom_info = DicomInfo(dictionary, iods, modules)
    return _dicom_info


def kb_edition() -> str:
    return config.KB_EDITION


# --- modality <-> SOP Class -------------------------------------------------
# Default single-frame ("classic") SOP Class per modality, plus the Enhanced /
# multi-frame variant chosen only when the user explicitly asks for it.
_CLASSIC = {
    "CT": "1.2.840.10008.5.1.4.1.1.2",
    "MR": "1.2.840.10008.5.1.4.1.1.4",
    "US": "1.2.840.10008.5.1.4.1.1.6.1",
    "CR": "1.2.840.10008.5.1.4.1.1.1",
    "DX": "1.2.840.10008.5.1.4.1.1.1.1",
    "XA": "1.2.840.10008.5.1.4.1.1.12.1",
    "MG": "1.2.840.10008.5.1.4.1.1.1.2",
    "NM": "1.2.840.10008.5.1.4.1.1.20",
    "PT": "1.2.840.10008.5.1.4.1.1.128",
    "OCT": "1.2.840.10008.5.1.4.1.1.77.1.5.4",
}
_ENHANCED = {
    "CT": "1.2.840.10008.5.1.4.1.1.2.1",
    "MR": "1.2.840.10008.5.1.4.1.1.4.1",
    "US": "1.2.840.10008.5.1.4.1.1.3.1",   # Ultrasound Multi-frame Image Storage
}
# Markup objects addressed by name.
_NAMED = {
    "PR": "1.2.840.10008.5.1.4.1.1.11.1",   # Grayscale Softcopy Presentation State
    "GSPS": "1.2.840.10008.5.1.4.1.1.11.1",
    "KO": "1.2.840.10008.5.1.4.1.1.88.59",  # Key Object Selection Document
}
_SOP_TO_MODALITY = {uid: mod for mod, uid in {**_CLASSIC}.items()}
_SOP_TO_MODALITY.update({v: k for k, v in _ENHANCED.items()})

_MULTIFRAME_SOP_CLASSES = set(_ENHANCED.values()) | {
    "1.2.840.10008.5.1.4.1.1.6.2",   # Enhanced US Volume
    "1.2.840.10008.5.1.4.1.1.77.1.5.4",  # OCT
    "1.2.840.10008.5.1.4.1.1.130",   # Enhanced PET
}
_REFERENCE_SOP_CLASSES = {_NAMED["PR"], _NAMED["KO"]}

# Image Pixel module — Materializer-owned; the AI must not put these in attributes.
PIXEL_MODULE_KEYWORDS = {
    "SamplesPerPixel", "PhotometricInterpretation", "Rows", "Columns",
    "BitsAllocated", "BitsStored", "HighBit", "PixelRepresentation",
    "PlanarConfiguration", "PixelData", "PixelAspectRatio", "NumberOfFrames",
}
PROTECTED_UID_KEYWORDS = {
    "StudyInstanceUID", "SeriesInstanceUID", "SOPInstanceUID",
    "MediaStorageSOPInstanceUID", "SOPClassUID", "MediaStorageSOPClassUID",
}


def resolve_sop_class(modality: str | None = None, enhanced: bool = False, sop_class_uid: str | None = None) -> str | None:
    if sop_class_uid:
        return sop_class_uid
    if not modality:
        return None
    key = modality.strip().upper()
    if key in _NAMED:
        return _NAMED[key]
    if enhanced and key in _ENHANCED:
        return _ENHANCED[key]
    return _CLASSIC.get(key)


def modality_for_sop_class(sop_class_uid: str) -> str | None:
    return _SOP_TO_MODALITY.get(sop_class_uid)


def is_multiframe(sop_class_uid: str) -> bool:
    return sop_class_uid in _MULTIFRAME_SOP_CLASSES


def multiframe_kind(sop_class_uid: str) -> str | None:
    """'enhanced' (functional-group model, e.g. Enhanced CT/MR), 'classic'
    (NumberOfFrames + Cine module, e.g. US Multi-frame/XA), or None (single-frame).
    Determined from the IOD's modules so it's correct per SOP Class."""
    req = requirements(sop_class_uid)
    if not req:
        return "enhanced" if is_multiframe(sop_class_uid) else None
    mods = {m["module"] for m in req["modules"]}
    if "Multi-frame Functional Groups" in mods:
        return "enhanced"
    if "Multi-frame" in mods or is_multiframe(sop_class_uid):
        return "classic"
    return None


def is_reference_object(sop_class_uid: str) -> bool:
    return sop_class_uid in _REFERENCE_SOP_CLASSES


def is_supported(sop_class_uid: str | None) -> bool:
    """Supported family: any image IOD we can resolve a modality for, plus PR/KO.
    Everything else the KB knows about (SR/RT/SEG/...) is deliberately refused."""
    if not sop_class_uid:
        return False
    if sop_class_uid in _REFERENCE_SOP_CLASSES:
        return True
    if sop_class_uid in _MULTIFRAME_SOP_CLASSES:
        return True
    return sop_class_uid in _SOP_TO_MODALITY


# --- tag / dictionary helpers ----------------------------------------------
def _vr_of(tag_str: str) -> str | None:
    try:
        g, e = tag_str.strip("()").split(",")
        return dictionary_VR((int(g, 16), int(e, 16)))
    except Exception:
        return None


def _keyword_of(tag_str: str) -> str | None:
    try:
        g, e = tag_str.strip("()").split(",")
        kw = dictionary_keyword((int(g, 16), int(e, 16)))
        return kw or None
    except Exception:
        return None


def describe(tag_or_keyword: str) -> dict | None:
    """Look up VR/VM/keyword for a DICOM keyword or a 'GGGG,EEEE' tag."""
    s = tag_or_keyword.strip()
    if "," in s:
        cleaned = s.replace("(", "").replace(")", "")
        try:
            g, e = cleaned.split(",")
            tag = (int(g, 16) << 16) | int(e, 16)   # int, not tuple (used in >> below)
        except ValueError:
            return None
    else:
        tag = tag_for_keyword(s)
        if tag is None:
            return None
    try:
        return {
            "keyword": dictionary_keyword(tag) or None,
            "tag": f"({tag >> 16:04X},{tag & 0xFFFF:04X})",
            "vr": dictionary_VR(tag),
        }
    except Exception:
        return None


def describe_many(names: list[str]) -> list[dict]:
    out = []
    for n in names:
        d = describe(n)
        out.append(d or {"keyword": n, "error": "unknown DICOM tag/keyword"})
    return out


def _iter_module_tags(ref: str, modules: dict, visited: set):
    """Yield (tag_str, meta) for a module ref, expanding macro `include`s once."""
    if ref in visited or ref not in modules:
        return
    visited.add(ref)
    for key, val in modules[ref].items():
        if key == "include" and isinstance(val, list):
            for inc in val:
                if isinstance(inc, dict) and inc.get("ref"):
                    yield from _iter_module_tags(inc["ref"], modules, visited)
        elif _TAG_RE.match(key):
            yield key, val


def requirements(sop_class_uid: str) -> dict | None:
    """Structured IOD requirements for a SOP Class: modules (usage M/C/U) and, for
    each, its tags with keyword/VR/Type/enums. None if the SOP Class is unknown."""
    info = get_dicom_info()
    entry = info.iods.get(sop_class_uid)
    if entry is None:
        return None
    modules = info.modules
    out_modules = []
    for mod_name, mod_meta in entry.get("modules", {}).items():
        ref = mod_meta.get("ref")
        tags = []
        for tag_str, meta in _iter_module_tags(ref, modules, set()):
            tags.append({
                "tag": tag_str,
                "keyword": _keyword_of(tag_str),
                "vr": _vr_of(tag_str),
                "type": meta.get("type", ""),
                **({"enums": [e.get("val") for e in meta["enums"]]} if meta.get("enums") else {}),
                # The raw cond dict (not just a flag) so callers can resolve it
                # via _cond_holds when they have enough context (mandatory_tags).
                **({"cond": meta["cond"]} if meta.get("cond") else {}),
            })
        out_modules.append({
            "module": mod_name,
            "ref": ref,
            "usage": mod_meta.get("use", ""),
            **({"cond": True} if mod_meta.get("cond") else {}),
            "tags": tags,
        })
    return {
        "sop_class_uid": sop_class_uid,
        "title": entry.get("title", ""),
        "modality": modality_for_sop_class(sop_class_uid),
        "is_multiframe": is_multiframe(sop_class_uid),
        "is_reference_object": is_reference_object(sop_class_uid),
        "modules": out_modules,
    }


def requirements_summary(sop_class_uid: str) -> dict | None:
    """Compact view of an IOD for the agent: module names + usage + counts, and only
    the mandatory Type-1 tag *keywords* (not the full VR/enum dump). ~1-2k tokens
    vs ~9k for the full `requirements`, so it won't blow up the chat context. Use
    the full form only when authoring by hand."""
    req = requirements(sop_class_uid)
    if req is None:
        return None
    modules = []
    for m in req["modules"]:
        t1 = [t["keyword"] for t in m["tags"] if t["type"] == "1" and t["keyword"] and t["keyword"] not in PIXEL_MODULE_KEYWORDS]
        modules.append({
            "module": m["module"], "usage": m["usage"],
            **({"conditional": True} if m.get("cond") else {}),
            "tag_count": len(m["tags"]),
            "type1_tags": t1,
        })
    return {
        "sop_class_uid": sop_class_uid, "title": req["title"], "modality": req["modality"],
        "is_multiframe": req["is_multiframe"], "multiframe_kind": multiframe_kind(sop_class_uid),
        "is_reference_object": req["is_reference_object"],
        "modules": modules,
        "note": "Compact summary. Check find_recipe first — a cache hit skips authoring entirely.",
    }


def valid_keywords(sop_class_uid: str) -> set[str]:
    """All DICOM keywords valid anywhere in this IOD (module-level + expanded
    macro includes). Used by spec_validator's not-in-IOD check."""
    req = requirements(sop_class_uid)
    if not req:
        return set()
    kws = {t["keyword"] for m in req["modules"] for t in m["tags"] if t["keyword"]}
    return kws


# Content-tree modules whose macro-included tags must not be treated as
# document-root mandatory (they belong inside content items).
_CONTENT_MODULES = {"SR Document Content", "Key Object Document"}


def mandatory_tags(sop_class_uid: str, exclude_content: bool = False,
                   context: dict | None = None) -> list[dict]:
    """Type 1/2 tags from unconditionally-mandatory (usage M) modules — the
    fill-in-the-blanks safety net in the Materializer. Set exclude_content=True
    for SR-family objects (PR/KO) to skip content-item macro tags that would
    otherwise appear as bogus document-root requirements. When `context`
    (e.g. {"SOPClassUID": ..., "PhotometricInterpretation": ...}) is given,
    Type-1C/2C tags whose `cond` resolves True against it are included too —
    e.g. Enhanced MR's Complex Image Component/Acquisition Contrast, which
    condition only on SOPClassUID and are effectively always required for a
    non-legacy-converted instance (see _cond_holds)."""
    req = requirements(sop_class_uid)
    if not req:
        return []
    ctx = {"SOPClassUID": sop_class_uid, **(context or {})}
    out = []
    for m in req["modules"]:
        if m["usage"] != "M" or m.get("cond"):
            continue
        if exclude_content and m["module"] in _CONTENT_MODULES:
            continue
        for t in m["tags"]:
            if not t["keyword"]:
                continue
            if t["type"] in ("1", "2"):
                out.append(t)
            elif t["type"] in ("1C", "2C") and t.get("cond") and _cond_holds(t["cond"], ctx):
                out.append(t)
    return out


# Sentinel for a mandatory UI (UID) leaf the KB can't give a fixed placeholder
# (would create duplicate UIDs across instances/items) — the Materializer
# recognizes this and calls uid_strategy.new_uid() instead. Generic across any
# modality/macro; not modality-specific code.
NEEDS_UID = object()


# --- generic macro/functional-group skeleton --------------------------------
# The pieces below let the Materializer build ANY macro/functional-group nested
# sequence (Enhanced CT/MR/PT frame-type + pixel-value-transformation, future
# modalities, ...) straight from KB data, instead of one hand-written Python
# function per modality (decision #3/#4, solution-design.md §9).

# Any DICOM "coded concept" (Code Sequence Macro, PS3.3 Table 8.8-1) needs one
# real identifier alongside CodeMeaning (CodeValue, LongCodeValue or
# URNCodeValue) — those are all individually Type-1C so the strict Type-1/2
# walk below leaves only CodeMeaning. Reuses the same private-scheme
# placeholder convention already established in defaults.fill_missing_tags.
_CODE_IDENTIFIER_KEYWORDS = {"CodeValue", "LongCodeValue", "URNCodeValue"}


def _complete_code_item(item: dict) -> dict:
    if item.get("CodeMeaning") and not (_CODE_IDENTIFIER_KEYWORDS & item.keys()):
        item.setdefault("CodeValue", "UNKNOWN")
        item.setdefault("CodingSchemeDesignator", "99PXA")
    return item


def _cond_holds(cond: dict, context: dict) -> bool | None:
    """Evaluate a KB `cond` (a comparison, or an and/or of them) against a
    context of already-known root-level tag values (e.g. SOPClassUID). Many
    Type-1C tags condition solely on SOPClassUID != <legacy-converted variant>
    — always true for the SOP classes we ever build — so resolving this
    generically (instead of leaving every 1C tag unfilled) closes real gaps
    like Enhanced CT's Content Qualification or Enhanced MR's Complex Image
    Component. Returns None when the referenced tag isn't in `context` —
    callers must treat that as "can't tell, leave it alone" (conservative;
    the probe's full validator remains the authority for anything else)."""
    if "and" in cond:
        results = [_cond_holds(c, context) for c in cond["and"]]
        if any(r is False for r in results):
            return False
        return None if any(r is None for r in results) else True
    if "or" in cond:
        results = [_cond_holds(c, context) for c in cond["or"]]
        if any(r is True for r in results):
            return True
        return None if any(r is None for r in results) else False
    tag = cond.get("tag")
    kw = _keyword_of(tag) if tag else None
    if not kw or kw not in context:
        return None
    actual = context[kw]
    idx = cond.get("index")
    if idx is not None and isinstance(actual, (list, tuple)):
        actual = actual[idx] if idx < len(actual) else None
    op, values = cond.get("op"), cond.get("values")
    if op == "=":
        return actual in (values or [])
    if op == "!=":
        return actual not in (values or [])
    if op == "+":
        return actual not in (None, "", [])
    if op == "-":
        return actual in (None, "", [])
    return None


def _walk_tags(tags: dict, modules: dict, visited: set, context: dict) -> dict:
    """Recursively turn a module/macro's tag dict (or a nested SQ's `items`) into
    a plain keyword->placeholder skeleton. Nested SQ tags become a one-item list
    of dicts (the shape dicom_apply.coerce_value expects); `include` refs and
    nested `items` are both walked. A tag is included if it's unconditionally
    mandatory (Type 1/2), or conditional (1C/2C) with a `cond` that resolves
    True against `context` (see _cond_holds) — anything else is left out for
    the caller to fill/override, or for the probe to catch. Leaf values use
    enums (first allowed value), NEEDS_UID for a mandatory UI leaf, or the
    generic VR_PLACEHOLDER."""
    out = {}
    for key, val in tags.items():
        if key == "include" and isinstance(val, list):
            for inc in val:
                ref = inc.get("ref") if isinstance(inc, dict) else None
                if ref and ref not in visited and ref in modules:
                    visited.add(ref)
                    out.update(_walk_tags(modules[ref], modules, visited, context))
            continue
        if not _TAG_RE.match(key):
            continue
        vtype = val.get("type")
        if vtype not in ("1", "2") and not (
            vtype in ("1C", "2C") and val.get("cond") and _cond_holds(val["cond"], context)
        ):
            continue
        kw = _keyword_of(key)
        if not kw:
            continue
        if "items" in val:
            nested = _walk_tags(val["items"], modules, visited, context)
            nested = _complete_code_item(nested)
            out[kw] = [nested] if nested else []
        elif val.get("enums"):
            first = val["enums"][0].get("val")
            out[kw] = first[0] if isinstance(first, list) and first else first
        else:
            vr = _vr_of(key)
            if vr == "UI":
                out[kw] = NEEDS_UID
            elif vr in VR_PLACEHOLDER:
                out[kw] = VR_PLACEHOLDER[vr]
    return out


def macro_skeleton(ref: str, context: dict | None = None) -> dict:
    """Generic keyword->placeholder skeleton for a KB module/macro ref (walks
    `include`s and nested SQ `items` recursively). Feed straight into
    dicom_apply.apply_value_map — no per-modality Python needed to build a
    functional-group / macro sequence. `context` (e.g. {"SOPClassUID": ...})
    lets Type-1C/2C tags with a resolvable condition be included too."""
    info = get_dicom_info()
    if ref not in info.modules:
        return {}
    return _walk_tags(info.modules[ref], info.modules, {ref}, context or {})


def mandatory_group_macros(sop_class_uid: str) -> list[dict]:
    """Multi-frame functional-group macros this IOD unconditionally requires
    (group_macros with use=='M', no cond) — e.g. CT's 'CT Image Frame Type' /
    'CT Pixel Value Transformation', MR's 'MR Image Frame Type' / 'Frame
    Anatomy'. Generic across every modality straight from the KB; the
    Materializer no longer needs an `if modality == "CT"` branch per IOD."""
    info = get_dicom_info()
    entry = info.iods.get(sop_class_uid)
    if not entry:
        return []
    context = {"SOPClassUID": sop_class_uid}
    out = []
    for macro_name, meta in (entry.get("group_macros") or {}).items():
        if meta.get("use") != "M" or meta.get("cond"):
            continue
        ref = meta.get("ref")
        out.append({"macro": macro_name, "ref": ref, "skeleton": macro_skeleton(ref, context)})
    return out
