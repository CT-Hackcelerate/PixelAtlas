# `recipes/`

Auto-grown cache of validated Generation Specs, the successor to the old template
catalog. Each successful KB-authored generation saves a JSON recipe here keyed by
`modality__body_part__orientation__sopclass__flags`. On a later matching request
the agent loads the recipe (via `find_recipe`) and skips the authoring + grounding
step.

Recipes are plain JSON so they stay human-reviewable and diffable. Auto-grown
recipes are gitignored (runtime cache); to keep a curated recipe under version
control, `git add -f` it deliberately. Note: any supported scan type can still be
generated from the Knowledge Base even with no recipe cached.
