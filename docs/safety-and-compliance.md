# Pixel Atlas — Safety & Compliance

What keeps this tool safe to point at a local test PACS: no real patient
data, no fabricated/unsafe output, refusal instead of substitution outside
its supported domain, and a human in the loop before anything irreversible.
Companion to [dod-evidence.md](dod-evidence.md), which has the underlying
`file:line` proof for every claim below — this document is the "what and
why," that one is the "prove it."

## 1. No real PHI, ever

- **Policy:** Pixel Atlas is a synthetic-data tool for dev/test/QA. It must
  never be pointed at, seeded from, or asked to reproduce real patient data.
  All generated identity (`PatientID`, `PatientName`, dates) is synthetic by
  default (`identity.mode = "synthetic"` in every authored spec).
- **PACS-seed path is the one exception to watch:** when a spec is extracted
  from an existing PACS study (`extract_spec`) or a study is cloned
  (`modify_dataset`, `generate_prior_study`), the source's identity and pixel
  data are carried over **as-is** — by design, so priors/edits stay linked to
  their reference study. This only stays safe if the source PACS itself only
  ever holds synthetic or already-anonymized data.
- **Enforcement level: agent-behavior-only.** There is no code-level PHI
  filter or scrubbing layer — `spec_extractor.py` says so explicitly. This is
  a documented convention, not a technical control. **Do not point this tool
  at a PACS holding real patient data** without adding a scrubbing layer
  first; nothing in the code will stop you.

## 2. Safe responses — refuse, never substitute

- **Unsupported object types are refused loud, not faked.** Structured
  Reports (SR), RT objects, Segmentation (SEG), encapsulated documents,
  waveforms, and anything else outside the supported IOD family are rejected
  with a clear reason at every entry point (`get_iod_requirements`,
  `resolve_seed`, `validate_spec`, `materialize_dataset`) — the agent is
  instructed to report this and stop, never to generate the closest
  supported thing instead.
- **Never loop on failure.** A `validate_spec` failure gets at most a couple
  of targeted repair attempts (fixing exactly the reported tags); if that
  doesn't resolve it, the agent reports the error and stops rather than
  retrying blindly. This bound is enforced by agent instruction (CLAUDE.md),
  not a server-side retry counter — see [dod-evidence.md §2](dod-evidence.md#2-golden-rules--nfr-coverage-claudemd-use-casesmd-5) item 3.
- **Out-of-scope or ambiguous asks get a stop-and-ask, not a guess.** If a
  request isn't a valid DICOM concept, or implies something the tool can't
  do, the agent says so rather than approximating.

## 3. Domain guardrails

- **The server never guesses a tag value on the agent's behalf.** Every
  attribute the agent authors is checked mechanically against the DICOM
  Knowledge Base — tag exists, VR correct, valid for this IOD — before
  anything is built (`validate_spec` → `spec_validator.py`, grounded on
  `iod_lookup.py`). Ungrounded/hallucinated tags are rejected with a specific
  reason, never silently written.
- **Pixel-module and UID tags cannot be hand-set.** `validate_spec` rejects
  any pixel-module or UID keyword if it appears in `attributes` — those are
  exclusively Materializer-owned, closing off an entire class of
  malformed/inconsistent files.
- **Supported domain is a hard allowlist, not a denylist.** `iod_lookup.py`'s
  `is_supported()` defines the in-scope family (standard image IODs,
  single- and multi-frame, plus PR/KO) and everything else is refused by
  default — new SOP Classes don't silently "just work" outside that family.
- **Conformance is checked twice before store.** Every materialized study
  passes both `validate_spec` (pre-build grounding) and `validate_dataset`
  (post-build `dicom-validator` IOD conformance + structural checks +
  `dcmftest`) — nothing reaches the PACS unvalidated.

## 4. Human confirmation gates

| Action | Confirmation required | Enforcement |
|---|---|---|
| Store to PACS (any study) | `store_to_pacs(confirm_store=True)` — a hard no-op without it | ✅ Code-enforced (`server.py`) |
| In-place destructive overwrite (`modify_dataset`) | `regenerate_uids=False` **and** `confirm_destructive=True`, both required | ✅ Code-enforced (`server.py`, `modify.py`) |
| Creating/overwriting > 50 instances | Agent must ask before proceeding | ⚠️ Agent-behavior-only (CLAUDE.md) — no numeric gate in code |
| Ambiguous series cardinality ("N instances" vs. "N series") | Agent must ask which the user means before generating anything | ⚠️ Agent-behavior-only |
| Choosing a seed source (real PACS data vs. fresh synthetic) | Agent must present the PACS candidate and let the user choose before authoring further | ⚠️ Agent-behavior-only |
| Requested count exceeds a real PACS seed's actual instance/frame count | Agent stops and asks the user to lower the count or drop the PACS seed | ⚠️ Agent-behavior-only |

The right-hand column is the load-bearing distinction: **code-enforced**
gates hold even if the agent misbehaves; **agent-behavior-only** gates rely
on the agent (and whatever is driving it) actually following `CLAUDE.md`.
Today that's always a CLAUDE.md-reading coding agent — but if this tool is
ever driven by anything else, the agent-behavior-only gates would need an
equivalent server-side check added first.

## 5. Data boundary

Only two kinds of data ever cross from this repo to an LLM's cloud backend:
the user's natural-language prompt, and the Generation Spec (small JSON —
tag keywords and synthetic values, never pixel bytes or full DICOM files).
Pixel data, `.dcm` files, and PACS contents are never inlined into chat
context — the Materializer synthesizes/clones pixels entirely in-process on
the local machine.

## 6. Audit trail

Every tool call and every generated job (full spec, provenance, KB edition)
is logged locally to `.pixel-atlas/logs/` (`agent.log`, `jobs.log`) via
`audit_log.py`, wired into every registered MCP tool — at zero token cost.
This is a record of what happened, not a preventive control; it supports
after-the-fact review, not real-time blocking.

## 7. Residual risks

- No code-level PHI scrubbing (§1) — the single biggest risk if this tool is
  ever pointed at a non-synthetic PACS.
- Several confirmation gates are agent-behavior-only (§4) — they depend on
  CLAUDE.md being loaded and followed; there's no fallback if it isn't.
- Job/spec state is in-memory (`job_registry`, `spec_store`) — lost on
  server restart, so an in-flight confirmation flow doesn't survive a crash
  mid-way; this is an availability/UX gap, not a data-safety one.
