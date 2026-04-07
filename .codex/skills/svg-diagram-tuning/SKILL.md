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
3. Sweep the whole semantic family before replying: if one card title, legend, callout,
   or arrow corridor is wrong, inspect the sibling elements of the same type and fix
   the full class of issue in one pass.
4. Rebalance titles, body text, padding, and connector anchors together rather than as
   isolated micro-fixes.
5. Rebalance line breaks across sibling cards together. If one block is rewrapped,
   inspect whether its peers need the same semantic treatment.
6. Keep one editable SVG as the source of truth.
7. Re-render only after the SVG itself is clean.

## GitHub-first guardrails

Use these rules whenever the SVG will be viewed on GitHub, in a README, or in a
blob/raw page:

- Treat text overflow as a hard failure. If any title, label, body line, or callout
  crosses a block edge in the target renderer, the SVG is not done.
- Treat repeated user complaints about one SVG as evidence that the previous pass was
  incomplete. Do a full regression sweep before responding again.
- Treat browser rendering as the target, not only one local SVG engine.
- Prefer conservative geometry over tight packing; GitHub/browser rendering is less
  forgiving than local slide or DOCX export.
- Use browser-safe font stacks first (`Arial`, `Helvetica`, sans-serif) unless the
  document already relies on a guaranteed embedded font.
- Keep decorative rules, dividers, and arrows out of text corridors. If a line comes
  near a label, move the line, not the label.
- Keep a semantic vertical rhythm. Similar elements should use the same spacing
  pattern between title, kicker, body, note, and the next section break.
- Keep a semantic line-break rhythm too. Do not let one peer block use arbitrary
  manual wraps while its siblings use balanced semantic phrases.
- After moving or resizing blocks, recalculate arrow anchors from the final geometry.
  Do not leave connector coordinates inherited from an older layout.
- For repeated connectors, keep arrow placement symmetric across the row or column so
  the figure reads as intentional rather than hand-adjusted.
- Center connectors on the geometry they are meant to describe. A vertical flow arrow
  should sit on the actual center axis of the card or lane, not on a stale inherited x.
- Treat lane rules and section dividers as a family too. They should share a deliberate
  start/end axis rather than drifting with each label width.
- Prefer widening a badge, pill, or summary card before wrapping what is really one
  short label or one atomic message. Use wrapping only when the content is genuinely
  paragraph-like.
- Treat one-line summary callouts as a special case. If a banner or flow summary was
  intentionally designed as one atomic sentence, do not let later grid tightening
  break it into two lines without an explicit semantic reason.
- For multiline card copy, make the block tall enough for the wrapped text first.
  Do not push a footer note, divider, or arrow closer just to preserve a fixed box
  height.
- If a block contains a title plus explanatory copy, reserve explicit top, middle,
  and bottom zones. Do not hand-place each text line independently without a repeatable
  vertical rhythm.
- Treat manual line breaks as part of the layout contract. Rewrap body and note copy
  by meaning, not by whatever happened to fit at one intermediate width.
- For a family of peer cards, choose one text structure on purpose: for example one
  centered title plus two balanced body lines, or one title plus body plus note.
  Do not mix one-line, two-line, and awkward broken phrases without semantic reason.
- Reserve a real vertical gutter between body text and footer notes. If the last body
  line visually touches the note below, the card height or note position is wrong even
  if the text does not literally overlap.
- Treat edge-touching as a defect class too. Adjacent cards, callouts, or side panels
  should keep a visible gutter; “not overlapping” is not a sufficient quality bar.
- Do not rely on implicit spacing between a numbered badge and the following title.
  Reserve explicit horizontal gap in the geometry.
- Do not keep long callouts on one line. Wrap them with `tspan` and increase the box
  size before shrinking text.
- Give legends and reading guides their own lane. Do not let a legend compete for the
  same vertical band as the last row of cards.
- Keep card titles aligned by family. If most peer blocks use centered titles, do not
  leave one or two titles left-aligned without an explicit semantic reason.
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
- Before replying, perform a semantic sweep of:
  - all card titles
  - all card bodies/notes
  - all legends/callouts
  - all arrows and arrowheads
  - section labels and lane headers
- Check body-to-note spacing inside every card, not only overflow at the card border.
- Check that line breaks are semantically balanced across sibling cards instead of
  looking random or width-driven.
- Check gutters between neighboring panels and side callouts, not only strict overlap.
- Check that arrows, lane rules, and labels still share the same axes after any grid
  shift. Geometry drift in connectors is a first-class defect.
- Re-render the SVG and visually inspect every text-bearing block for overflow,
  collisions, and clipped whitespace before pushing.
- Re-check any badge, banner, or summary card that was previously one line after any
  global width or grid change. Do not assume it will survive a layout normalization.
- If the user pointed out one concrete defect, verify the same defect does not remain
  in sibling blocks before declaring the SVG fixed.
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
- fix the whole class of related defects, not just the line the user mentioned
- remove overlap
- clarify hierarchy
- widen crowded blocks
- increase text size
- simplify wording when layout alone is not enough
- add whitespace before trusting typography tweaks
- keep section labels and divider rules on one shared visual axis
- recompute connector geometry after every layout shift

## Anti-patterns

- Do not reply after fixing only the one line the user cited if adjacent blocks still
  have the same defect class.
- Do not solve GitHub overflow by shrinking text first when geometry can be widened,
  rewrapped, or reflowed.
- Do not leave arbitrary manual wraps in a diagram after resizing a block. Revisit
  every edited phrase and choose deliberate semantic breaks.
- Do not place legends, guides, or notes into leftover whitespace without checking
  whether they visually collide with the main diagram bands.

## References

- Read `references/layout.md` for the tuning checklist.
