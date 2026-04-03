---
name: svg-diagram-tuning
description: Refine SVG diagrams for readability in documents and slides. Use this skill when a user wants text resized, blocks widened, arrows rerouted, overlapping labels fixed, or an existing figure made easier to edit and export without redesigning it from scratch.
---

# SVG Diagram Tuning

## Overview

Use this skill to improve an existing SVG diagram without changing its meaning.
Focus on readability first: text, spacing, arrows, and visual hierarchy.

## When to use

- Text is too small or cropped
- Blocks overlap or feel cramped
- Arrow flow is unclear
- The figure needs to export better into DOCX or PDF

## Workflow

1. Inspect the current structure and identify the source of crowding.
2. Fix geometry before increasing font sizes aggressively.
3. Rebalance titles, body text, and padding.
4. Keep one editable SVG as the source of truth.
5. Re-render only after the SVG itself is clean.

## AGILAB Workflow

1. Edit the canonical SVG under `../thales_agilab/docs/source`.
2. Sync the mirrored SVG under `agilab/docs/source` when the page is public.
3. Validate the edited SVG as XML before rebuilding docs.
4. Check the `.rst` page that references the figure so path changes do not break
   the published page.
5. Validate the rendered HTML page after publish instead of assuming the raw SVG
   source path will exist on GitHub Pages.

## AGILAB Validation

- Parse the SVG locally with Python XML tooling if needed.
- Confirm the figure is referenced from the expected `.rst` page.
- For published docs, verify the embedding page such as `architecture.html` or
  `agi-core-architecture.html`; Sphinx may publish figure assets under `_images/`.

## Priority order

- remove overlap
- clarify hierarchy
- widen crowded blocks
- increase text size
- simplify wording when layout alone is not enough

## References

- Read `references/layout.md` for the tuning checklist.
