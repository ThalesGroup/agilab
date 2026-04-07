---
name: advanced-svg-system-design
description: Design SVG systems for advanced external projects. Use this skill when the user needs a reusable SVG visual language, multi-diagram consistency, export-safe assets for web/slides/docs, or an editable source-of-truth beyond simple cleanup of one existing figure.
license: BSD-3-Clause (see repo LICENSE)
---

# Advanced SVG System Design

## Overview

Use this skill when a project needs more than SVG cleanup.
Focus on building a durable diagram system: layout rules, reusable components,
editability, export behavior, and review checkpoints across many figures.

## When to use

- A single SVG is turning into a family of diagrams
- The user wants a visual language, not only a one-off figure
- The project must work on web, GitHub, docs, slides, and reports
- The same figure must survive multiple edits by different people
- The user needs structure for advanced SVG work in an external project

## Not the right skill

- For quick readability fixes on one existing SVG, use `svg-diagram-tuning`
- For bitmap-heavy mockups or photo-like assets, use raster/image tooling instead
- For HTML/canvas apps, use frontend work directly unless SVG remains the source of truth

## Workflow

1. Identify the delivery surfaces first: browser, GitHub, Sphinx, slides, DOCX, PDF, or print.
2. Decide what stays invariant across diagrams:
   - grid
   - font stack
   - stroke widths
   - card shapes
   - connector rules
   - color semantics
3. Keep one editable SVG source of truth per figure family.
4. Prefer reusable groups and consistent naming over manual geometry drift.
5. Separate semantic layers when useful:
   - structure
   - connectors
   - annotations
   - highlights
6. Validate at the actual publication size, not only zoomed-in in an editor.
7. Record the export and review contract so the next editor does not improvise it.

## Design rules

- Optimize for comprehension before ornament.
- Use whitespace and alignment before shrinking text.
- Keep text on a predictable baseline rhythm.
- Reserve explicit lanes for connectors; do not weave arrows through text.
- Keep colors semantic and limited; use shape or position for redundancy.
- If a diagram family grows, standardize component geometry instead of nudging boxes one by one.
- Prefer browser-safe font stacks unless the project controls font embedding.
- Treat GitHub and browser rendering as first-class targets, not afterthoughts.

## Editing rules

- Preserve stable IDs, layer names, and grouping so future edits stay cheap.
- Do not convert all text to outlines unless the delivery contract truly requires it.
- Do not rely on editor-specific effects that break in plain browser rendering.
- Keep numeric sizing intentional: shared padding, corner radius, stroke widths, and arrowhead scale.
- When reflowing one card, re-evaluate the whole row or column for symmetry.

## Validation

- Check XML validity when editing raw SVG.
- Compare at least two renderers when the output is public-facing.
- Verify the placed size inside the real target:
  - README/browser page
  - Sphinx HTML
  - slide
  - DOCX/PDF export
- If the project uses generated derivatives, regenerate them from the same source SVG before review.

## References

- Read `references/workflow.md` for the advanced checklist.
