# Documentation Updates (Latest Session)

## What Changed

### 1. Consolidated Setup Guides
**New:** `docs/SETUP.md` — Single comprehensive setup guide replacing 3 separate docs
- Covers: WSL, Docker Desktop, Git, VS Code, MCP server, Orthanc
- Includes troubleshooting section
- Replaces duplicated content from:
  - `docs/docker-wsl-setup.md` (kept for reference)
  - `docs/orthanc-setup.md` (kept for reference)
  - `docs/vscode-git-claude-setup.md` (kept for reference)

### 2. New Quick Start Guide
**New:** `docs/QUICKSTART.md` — Minimal examples for common workflows
- Generate single series
- Multi-frame (US cine, Enhanced CT)
- Multi-series studies (new feature)
- Add PR/KO markup
- Key commands reference
- Common issues & fixes

### 3. Simplified Main Documentation
**Updated:** `docs/README.md`
- Reorganized around: Getting started → Understand → Use → Troubleshooting
- Replaced matrix of old docs with clear reading path
- Added "At a Glance" quick reference
- Golden rules summary
- Removed plan/historical docs from main index

**Updated:** Root `README.md`
- Added "Quick Start" section pointing to new guides
- Simplified "How it works" with mermaid diagram
- Added "How to generate (30-second version)" visual
- Consolidated design doc references

### 4. Enhanced Architecture Documentation
**Updated:** `docs/architecture.md`
- Added new tools: `generate_study(..., study_uid)` and `list_series_instances`
- Added visual flow diagram for multi-series workflow (§4.1)
- Clarified study identity reuse mechanism
- Updated MCP tool table with new parameters

### 5. Solution Design Updates
**Updated:** `docs/solution-design.md`
- §18: Multi-series studies & cross-series references (no longer "proposed", now implemented)
- Documents: `study_uid` parameter, `list_series_instances` tool
- Explains identity precedence (prior-study vs attach-to-study vs synthetic)
- Clarified agent-level disambiguation rules (ask before assuming series cardinality)

**Updated:** `CLAUDE.md` (agent instructions)
- §Standard flow: Added `study_uid?` parameter
- §Advanced flow: Updated multi-series instructions (now achievable in one session)
- All golden rules and tools documented

---

## Code Changes (This Session)

### Multi-Series Implementation

#### `mcp-server/orthanc_client.py`
- **`get_study_details()`** — Added `study_description` and `accession_number` to returned identity dict
- **`list_series_instances()`** — NEW. Queries Orthanc for stored instances by study/series, returns instance UIDs (needed for PR/KO references)

#### `mcp-server/defaults.py`
- **`baseline_spec()`** — Added `study_uid` parameter, threads it to `spec["request"]["attachStudyUID"]`

#### `mcp-server/materializer.py`
- **`_resolve_same_study_identity()`** — NEW. Fetches identity from existing study via Orthanc (for attaching series to existing study)
- **`_resolve_identity()`** — NEW. Centralized identity precedence: prior-study → attach-to-study → leave caller's alone → synthetic fallback. Replaces 3 duplicate per-branch checks.
- **`_materialize_single_frame()`, `_materialize_classic_mf()`, `_materialize_enhanced_mf()`** — Updated to use `_resolve_identity()` and respect `spec["request"]["attachStudyUID"]` instead of always minting new StudyInstanceUID

#### `mcp-server/server.py`
- **`generate_study()`** — Added `study_uid` parameter; updated docstring
- **`list_series_instances()`** — NEW MCP tool. Enumerates instances for a study/series (for building PR/KO references)

### Bug Fix

#### `mcp-server/server.py` (line 159)
- **CineRate hardcoding bug fixed**: Was `if kb.multiframe_kind(sop) == "classic" and (cine_rate or count > 1)`, which hardcoded 30 fps when count > 1 even if user passed an override. Now `if kb.multiframe_kind(sop) == "classic" and cine_rate` — only sets the default when explicitly passed, doesn't out-rank user overrides.

---

## No Hardcoding Principle

All changes follow the feedback rule: **Never let an internal hardcoded default silently outrank explicit user input.**

- CineRate: fixed (see above)
- Identity in multi-series: Caller's explicit PatientID always wins
- Precedence chains: One place (`_resolve_identity`), not scattered across branches

---

## File Organization

### Removed Duplication
- 3 setup guides → 1 consolidated `SETUP.md` + QUICKSTART
- Architecture mixed with design → Solution Design + Architecture + Overview
- Scattered multi-series notes → Centralized in CLAUDE.md and §18 of solution-design.md

### Document Structure (Recommended Reading Order)
1. **Root README.md** — Entry point
2. **docs/SETUP.md** — Install everything (one time)
3. **docs/QUICKSTART.md** — Use it (common flows)
4. **docs/solution-design.md** — Understand the design
5. **docs/architecture.md** — Understand components
6. **docs/sample-prompts.md** — See examples

---

## Testing Checklist

- [x] Python files compile (`py_compile`)
- [x] `_resolve_identity()` precedence verified (synthetic, no attach, no override cases)
- [x] `attachStudyUID` error path tested (study not found in Orthanc)
- [x] CineRate precedence verified (explicit arg, override, attribute, default)
- [x] MCP tools registered and documented

---

## Backward Compatibility

- All existing tools unchanged in signature (except new optional `study_uid` on `generate_study`)
- Old setup guides kept for reference (marked as such)
- PACS-seed path behavior unchanged
- Prior-study flow unchanged
