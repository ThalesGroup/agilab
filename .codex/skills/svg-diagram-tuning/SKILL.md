---
name: svg-diagram-tuning
description: Refine SVG diagrams for readability in documents and slides. Use this skill when a user wants text resized, blocks widened, arrows rerouted, overlapping labels fixed, or an existing figure made easier to edit and export without redesigning it from scratch.
license: BSD-3-Clause (see repo LICENSE)
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

## GitHub-first guardrails

Use these rules whenever the SVG will be viewed on GitHub, in a README, or in a
blob/raw page:

- Treat text overflow as a hard failure. If any title, label, body line, or callout
  crosses a block edge in the target renderer, the SVG is not done.
- Treat browser rendering as the target, not only one local SVG engine.
- Prefer conservative geometry over tight packing; GitHub/browser rendering is less
  forgiving than local slide or DOCX export.
- Use browser-safe font stacks first (`Arial`, `Helvetica`, sans-serif) unless the
  document already relies on a guaranteed embedded font.
- Keep decorative rules, dividers, and arrows out of text corridors. If a line comes
  near a label, move the line, not the label.
- Keep a semantic vertical rhythm. Similar elements should use the same spacing
  pattern between title, kicker, body, note, and the next section break.
- After moving or resizing blocks, recalculate arrow anchors from the final geometry.
  Do not leave connector coordinates inherited from an older layout.
- For repeated connectors, keep arrow placement symmetric across the row or column so
  the figure reads as intentional rather than hand-adjusted.
- Prefer widening a badge, pill, or summary card before wrapping what is really one
  short label or one atomic message. Use wrapping only when the content is genuinely
  paragraph-like.
- For multiline card copy, make the block tall enough for the wrapped text first.
  Do not push a footer note, divider, or arrow closer just to preserve a fixed box
  height.
- If a block contains a title plus explanatory copy, reserve explicit top, middle,
  and bottom zones. Do not hand-place each text line independently without a repeatable
  vertical rhythm.
- Do not rely on implicit spacing between a numbered badge and the following title.
  Reserve explicit horizontal gap in the geometry.
- Do not keep long callouts on one line. Wrap them with `tspan` and increase the box
  size before shrinking text.
- Shorten labels like lane headers or section names before tightening letter spacing.
- When two renderers disagree, prefer the layout with more whitespace.

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
- Re-render the SVG and visually inspect every text-bearing block for overflow,
  collisions, and clipped whitespace before pushing.
- Confirm the figure is referenced from the expected `.rst` page.
- For published docs, verify the embedding page such as `architecture.html` or
  `agi-core-architecture.html`; Sphinx may publish figure assets under `_images/`.
- For GitHub-facing SVGs, validate with at least two renderers when possible:
  `rsvg-convert` plus a browser-adjacent renderer such as Quick Look (`qlmanage`) or
  an actual browser screenshot workflow.
- If the user points to a GitHub blob/raw URL, treat that observed rendering issue as
  real even if a local renderer looks acceptable.

## Priority order

- eliminate overflow and collisions
- remove overlap
- clarify hierarchy
- widen crowded blocks
- increase text size
- simplify wording when layout alone is not enough
- add whitespace before trusting typography tweaks
- keep section labels and divider rules on one shared visual axis
- recompute connector geometry after every layout shift

## References

- Read `references/layout.md` for the tuning checklist.
