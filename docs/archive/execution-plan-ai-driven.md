# Execution Plan — AI-Driven Pixel Atlas

> **Historical record — this migration is complete.** The template system
> (`templates/`, `generator.py`, `templates.py`, `generate_seed.py`) described
> as "to retire" below has been removed; the KB is now committed in-repo
> (`mcp-server/kb/`), not built at runtime. Kept for the design rationale, not
> as a current-state reference — see [architecture.md](../architecture.md) and
> [solution-design.md](../solution-design.md) for what's actually running today.

> **This is one *proposed sequencing* of the full scope.** The complete,
> phase-independent scope lives in
> [ai-driven-comprehensive-plan.md](ai-driven-comprehensive-plan.md) — start there.
> This doc just suggests an order to tackle it in; finalize phasing after reviewing
> the master plan.
>
> Plain-language build plan for the AI-driven redesign. Read the three design docs
> first if you want the detail:
> [simple overview](../ai-driven-simple-overview.md) ·
> [solution design](../solution-design.md) ·
> [architecture](../architecture.md) ·
> [what's changing](design-change-ai-driven.md).

## What we are building (in one paragraph)

Instead of hand-made "templates" that only cover scan types someone prepared in
advance, the assistant (AI) will read the official DICOM rulebook and write a short
**order slip** (a JSON file) for *any* standard scan request. A plain piece of code
called the **Materializer** turns that order slip into real `.dcm` test files,
checks them, and loads them into the test PACS. The AI does the thinking once; the
code does the repetitive work.

## Ground rules

- **No versioning ceremony.** This is the build. The old template code gets
  replaced as we go, not kept running forever beside the new code.
- **Build the simplest thing first, prove it end to end, then add hard cases.**
- **The AI only ever handles text.** Image pixels are made by code, never sent to
  the AI (this is what keeps it cheap).
- **Check before you store.** Nothing reaches the PACS until it passes validation.
- **Test the output, then refine.** Especially for the harder scan types.

## What already exists that we reuse

These files are already built and working (verified by direct script calls) and we
build on them rather than rewrite:

- Talking to the PACS: `orthanc_client.py`, `pacs_store.py`
- Making unique IDs: `uid_strategy.py`
- Checking finished files: `validator.py` (uses `dicom-validator`)
- Job tracking + logging: `job_registry.py`, `audit_log.py`
- The current file-builder `generator.py` and pixel helper `seed_builder.py` —
  we refactor these into the new Materializer rather than starting from scratch.

## The plan, phase by phase

Each phase says **what** we do and **how we know it's done**. Do them in order.

### Phase 0 — Quick feasibility check (de-risk first)

**What:** Before building anything, confirm the rulebook actually gives us what we
need. Read `dicom-validator`'s built-in DICOM standard data for a few scan types
(CT, MR, CR) and check it lists the required tags with their types and rules.
Confirm it loads once and stays fast after the first (~40s) load.

**Done when:** We can print the required-tag list for CT, MR, and CR from the
standard data, and repeated lookups are fast. If a target scan type is missing from
the standard data, we flag it now and adjust — this is the biggest unknown, so we
settle it first.

### Phase 1 — The Knowledge Base (the reusable rulebook)

**What:** Turn `iod_lookup.py` into the Knowledge Base: given a scan type, return
its required tags (name, VR, type, rule). Add a small lookup for "modality → default
scan class" (defaulting to the simple single-picture type unless the user asks for
"enhanced/multi-frame"). Add two tools the AI will call: `get_iod_requirements`
(full tag list) and `describe_attributes` (quick lookups for a few tags).

**Done when:** Both tools return correct answers for several scan types that have no
template today.

### Phase 2 — The order slip + the safety check

**What:** Define the **order-slip format** (the Generation Spec — see solution
design §5). Build `spec_validator.py` with the `validate_spec` tool. It checks the
AI's order slip against the rulebook: are the tags real, right VR, allowed for this
scan type, all required ones present? Plus a short list of "do these tags make sense
together" checks (pixel settings, modality vs scan class, geometry). It also stores
the order slip and hands back a short **ticket number** (`spec_id`) so the slip
doesn't have to be re-sent later (saves tokens).

**Done when:** A good order slip passes; deliberately broken ones fail with clear,
specific messages naming the problem tag.

### Phase 3 — The Materializer (single-picture scans first)

**What:** Build `materializer.py` (the `materialize_dataset` tool) by refactoring
the current `generator.py`. It takes a ticket number, makes the files, and:
- makes **one file first and fully checks it** before making the rest (cheap way to
  catch mistakes),
- makes the picture data itself for the "no PACS study" case (noise/gradient, sized
  from the order slip; the AI never sends pixels),
- reuses the existing ID-making, staging, job-tracking, and safety-net code.
Start with **simple single-picture scan types only** (e.g. CR, MR, CT).

**Done when:** For a scan type with no template, we can go order-slip → check →
make 100 files → validate, with **zero conformance errors**. This one slice proves
the whole idea works.

### Phase 4 — Reuse existing PACS scans + modify

**What:** Build `spec_extractor.py` (`extract_spec`): turn an existing PACS study
into an order slip so the AI can tweak it. Point `modify_dataset` at this same path.
Simplify `resolve_seed` so it returns just two outcomes: "found in PACS" or "build
from the rulebook." (No PHI scrubbing for now — this is a test tool on test data;
see the note in Issues.)

**Done when:** We can copy an existing PACS study's structure, change a few things,
and produce a new valid study; and `/modify` works through the same code.

### Phase 5 — Recipe reuse (skip the thinking next time)

**What:** Build `recipe_store.py`: when an order slip works, save it, keyed by the
broad scan type (modality + body part + orientation + scan class + a few flags like
"with contrast"). Next time the same kind of request comes in, load the saved recipe
and skip the AI thinking step. Add `list_recipes` / `get_recipe`; retire the old
`list_templates` / `get_template_info`.

**Done when:** A repeat request reuses a saved recipe and costs about the same as the
old template approach.

### Phase 6 — Multi-picture scans (test-first)

**What:** Add support for multi-frame scan types, where one file holds many pictures
(count = pictures inside one file, not many files). The AI writes the per-picture
settings; the code builds the file. This is harder because of nested structures.

**Done when:** We can make a valid multi-frame file and look at the output. If a
specific type keeps failing, we hand-build that one part instead of relying on the
AI. **We inspect real output before polishing.**

### Phase 7 — Markup objects PR / KO (test-first)

**What:** Add Presentation States (saved viewing settings) and Key Object Selection
(flagged key images). These don't hold pictures — they *point at* existing scans, so
those scans must already be in the PACS. The order slip carries a "references" list.

**Done when:** We can make a valid PR and KO that correctly point at existing scans,
and look at the output. **Inspect first, refine after.**

### Phase 8 — Wire it into Copilot Chat + clean up

**What:** Update the chat instructions and slash commands so the assistant follows
the new flow (write order slip → check → make files), uses the ticket-number trick,
and offers `/list-recipes`. Then run everything through Copilot Chat for real (this
has never been done end-to-end — see Issues). Remove the old template files and code
(`templates/`, `generator.py`, `templates.py`, `generate_seed.py`).

**Done when:** A real Copilot Chat session can generate, modify, validate, and store
scans through the new flow without needing a code fix.

### Phase 9 — Documentation cleanup

**What:** Fold the AI-driven design docs into the main docs and update the reading
order so the template-based docs are clearly marked as replaced.

**Done when:** The main README points at the AI-driven docs as the current design.

## How we will test

- **Automated (small set):** fixed order slips run through `validate_spec`,
  `materialize_dataset`, and `extract_spec`. These are the code parts and are
  predictable, so they get real tests.
- **By hand (the rest):** because the AI's writing is not identical every time, we
  don't try to auto-test what the AI produces. Instead the user runs a handful of
  real requests and eyeballs the output — especially for multi-frame and PR/KO.

## Issues / things that could bite us (flagged, as asked)

1. **The rulebook must cover the scan types we want.** The Knowledge Base is only as
   good as `dicom-validator`'s standard data. If a target scan type isn't in there,
   that phase's approach needs a rethink. **This is why Phase 0 exists — settle it
   before building.**
2. **Never run through Copilot Chat yet.** Every check so far (in the existing code)
   has been a direct script call, never a live Copilot session. Phase 8 is the first
   real end-to-end chat test and historically that's where surprises appear. Budget
   time for follow-up fixes there.
3. **Multi-frame and PR/KO are genuinely hard.** They use deeply nested structures
   that the AI may get wrong, causing extra back-and-forth. That's why they are last
   and explicitly test-first. Fallback: hand-build the tricky nested part for any
   type that keeps failing.
4. **PR/KO need targets to already exist.** You can't make "saved viewing settings"
   for a scan that isn't in the PACS. The flow must generate or find the target scans
   first. Handle this when we reach Phase 7.
5. **Synthetic pictures are noise, not real anatomy.** Files will be valid and will
   open in a viewer (we set sensible brightness/contrast defaults), but they won't
   look like real body parts. This is expected and out of scope.
6. **No PHI scrubbing right now.** Because this is a test tool on a test PACS, when
   we copy an existing scan we keep its details as-is. **Do not point this at a PACS
   with real patient data until a scrubbing step is added.** This must be built
   before any real-world use.
7. **Saved state is in memory.** Ticket numbers (`spec_id`) and job status live in
   memory and are lost if the server restarts mid-job. Fine for now; note it.
8. **AI values are correct-but-not-always-sensible.** The checks guarantee the file
   is valid and opens cleanly, not that every value is clinically realistic. Accepted
   for test data.

## Suggested first move

Do **Phase 0 then Phases 1–3** as one focused push and stop to look at the result:
a real scan type, with no template, generated purely from the rulebook + AI order
slip, passing validation. That single result proves the whole approach is sound
before we spend effort on the harder scan types.
