# Pixel Atlas Documentation

Synthetic DICOM data generation via the Pixel Atlas MCP server.

## 🚀 Getting Started

- **[SETUP.md](SETUP.md)** — Complete one-time installation (Docker, WSL, Orthanc, MCP)

## 📚 Understand the System

- **[solution-design.md](solution-design.md)** — *What* you're building: Knowledge Base, Generation Spec, materialization, token economy. **Read this first to understand the architecture.**
- **[architecture.md](architecture.md)** — Components, data flow, MCP tool reference

## 🎯 How to Use

- **[demo-prompts.md](demo-prompts.md)** — Real prompt examples, from "basic CT" to "prior study with PR"
- **[use-cases.md](use-cases.md)** — Structured scenarios: annotation workflows, multi-modality testing, regression suites
- **[dod-evidence.md](dod-evidence.md)** — Definition of Done: every use case and golden rule mapped to code evidence, code-enforced vs. agent-behavior-only
- **[safety-and-compliance.md](safety-and-compliance.md)** — No real PHI, safe-refusal behavior, domain guardrails, human confirmation gates

## 🗄️ Archive

- **[archive/](archive/)** — superseded planning docs from the original
  design/build effort. Kept for history only — the design they describe has
  since changed; do not treat them as current.

## 🛠️ Troubleshooting

**Problem** → **See**
- Setup failures → [SETUP.md](SETUP.md) (Troubleshooting section)
- MCP won't connect → [SETUP.md Part 6](SETUP.md#part-6-configure-claude-code)
- Orthanc issues → [SETUP.md](SETUP.md) (Troubleshooting)
- "How do I use this?" → [demo-prompts.md](demo-prompts.md)
- "What are the design constraints?" → [solution-design.md](solution-design.md)

---

## Quick Links

| | |
|---|---|
| **Setup** | [SETUP.md](SETUP.md) |
| **Examples** | [demo-prompts.md](demo-prompts.md) |
| **How it works** | [solution-design.md](solution-design.md) |
| **Architecture** | [architecture.md](architecture.md) |
| **Scenarios** | [use-cases.md](use-cases.md) |
| **DoD evidence** | [dod-evidence.md](dod-evidence.md) |
| **Safety & Compliance** | [safety-and-compliance.md](safety-and-compliance.md) |

---

## Golden Rules

- **Check `find_recipe` before authoring** — a cache hit skips straight to `validate_spec`
- **The agent authors the tags; the server only grounds and builds** — via `get_iod_requirements`/`describe_attributes`, never guessed by the server
- **Never loop** — if a tool errors, report and stop (don't retry)
- **Ask before assuming cardinality** — "100 instances" defaults to one series; if unclear, ask
- **Always confirm before store** — show validation results first
- **Use `attachStudyUID` to chain series** — attach series 2 to study 1's UID instead of creating a new study
