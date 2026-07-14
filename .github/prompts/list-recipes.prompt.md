---
description: List cached recipes (previously-generated scan types)
mode: agent
tools: ["pixel-atlas/list_recipes"]
---

# /list-recipes [modality=]

Call `list_recipes` with any given modality filter and present the results as a
compact table: modality, body_part, orientation, sop_class_uid, flags, kb_edition.
Recipes are auto-grown from successful generations (not a hand-authored catalog) —
a hit lets `/generate` skip the authoring step via `find_recipe`. Note that even
with no recipes, any supported scan type can still be generated from the Knowledge
Base.
