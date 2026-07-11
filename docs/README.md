# Pixel Atlas Documentation

Synthetic DICOM data generation via the Pixel Atlas MCP server.

## 🚀 Getting Started

1. **[SETUP.md](SETUP.md)** — Complete one-time installation (Docker, WSL, Orthanc, MCP)
2. **[QUICKSTART.md](QUICKSTART.md)** — Minimal examples: basic generation, multi-series, PR markup

## 📚 Understand the System

- **[solution-design.md](solution-design.md)** — *What* you're building: Knowledge Base, Generation Spec, materialization, token economy. **Read this first to understand the architecture.**
- **[architecture.md](architecture.md)** — Components, data flow, MCP tool reference
- **[ai-driven-simple-overview.md](ai-driven-simple-overview.md)** — Plain-English 10-minute overview

## 🎯 How to Use

- **[sample-prompts.md](sample-prompts.md)** — Real prompt examples, from "basic CT" to "prior study with PR"
- **[use-cases.md](use-cases.md)** — Structured scenarios: annotation workflows, multi-modality testing, regression suites

## 🏗️ Design & Implementation

- **[design-change-ai-driven.md](design-change-ai-driven.md)** — How the current design replaced the old template system (per-file delta)
- **[ai-driven-comprehensive-plan.md](ai-driven-comprehensive-plan.md)** — Full build spec: decisions ledger, component scope (reference, not required reading)
- **[execution-plan-ai-driven.md](execution-plan-ai-driven.md)** — Historical build plan (complete)

## 🛠️ Troubleshooting

**Problem** → **See**
- Setup failures → [SETUP.md](SETUP.md) (Troubleshooting section)
- MCP won't connect → [SETUP.md Part 6](SETUP.md#part-6-configure-claude-code)
- Orthanc issues → [SETUP.md](SETUP.md) (Troubleshooting)
- "How do I use this?" → [QUICKSTART.md](QUICKSTART.md)
- "What are the design constraints?" → [solution-design.md](solution-design.md)

---

## Quick Links

| | |
|---|---|
| **Setup** | [SETUP.md](SETUP.md) |
| **Use it** | [QUICKSTART.md](QUICKSTART.md) |
| **Examples** | [sample-prompts.md](sample-prompts.md) |
| **How it works** | [solution-design.md](solution-design.md) |
| **Architecture** | [architecture.md](architecture.md) |
| **Scenarios** | [use-cases.md](use-cases.md) |

---

## Key Concepts

**Generation Spec** — A JSON document you author (or Claude authors) that describes what DICOM instances to build: modality, count, attributes, per-instance rules, pixel directive, identity policy. The spec is deterministic and O(1) in instance count — never embeds per-instance data.

**Knowledge Base (KB)** — Standard-derived DICOM schema: every IOD, module, tag requirement, VR, type. Derived once from `dicom-validator`, reusable for all requests.

**Materializer** — Library that builds `.dcm` files from a spec: expands N instances, synthesizes pixels, assigns UIDs, validates conformance before store.

**Recipe** — A validated Generation Spec cached by request signature (modality + body part + orientation + flags). Repeat requests skip planning; straight to materialize.

---

## Supported

✓ All standard image IODs (single-frame & multi-frame)  
✓ Enhanced CT/MR (functional groups)  
✓ Classic multi-frame US/XA (cine)  
✓ Presentation State (PR) & Key Object Selection (KO)  
✗ Structured Reports, RT, Segmentation, encapsulated docs

---

## At a Glance

```
User: "100 axial CT instances"
         ↓
    Claude Code
         ↓
    MCP Server (Python)
         ↓
  ┌─────────────────┐
  │ Knowledge Base  │  (standard-derived schema)
  │ Generation Spec │  (user's request → JSON)
  │ Materializer    │  (spec → .dcm files)
  └─────────────────┘
         ↓
    Staging (local disk)
         ↓
  validate_dataset (IOD conformance check)
         ↓
    store_to_pacs (C-STORE or Orthanc REST)
         ↓
    Orthanc PACS
         ↓
    ✓ Study stored
```

---

## Golden Rules

- **One call generates a study** — `generate_study()` does all the DICOM work for you
- **Never loop** — if a tool errors, report and stop (don't retry)
- **Ask before assuming cardinality** — "100 instances" defaults to one series; if unclear, ask
- **Always confirm before store** — show validation results first
- **Use `study_uid` to chain series** — attach series 2 to study 1's UID instead of creating a new study
