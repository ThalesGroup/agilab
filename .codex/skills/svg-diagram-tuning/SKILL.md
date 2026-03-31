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

## Priority order

- remove overlap
- clarify hierarchy
- widen crowded blocks
- increase text size
- simplify wording when layout alone is not enough

## References

- Read `references/layout.md` for the tuning checklist.
