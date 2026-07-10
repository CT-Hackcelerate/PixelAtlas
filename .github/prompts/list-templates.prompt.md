---
description: List available DICOM tag templates
mode: agent
tools: ["pixel-atlas/list_templates"]
---

# /list-templates [modality=] [body_part=] [orientation=]

Call `list_templates` with any given filters and present the results as a
compact table: template_id, modality, body_part, orientation, whether
fallback seed data is bundled (`has_seed_data`). Paginate rather than
dumping a long list in full.
