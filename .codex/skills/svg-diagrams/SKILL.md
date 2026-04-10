---
name: svg-diagrams
description: Create or edit repo-native SVG diagrams, architecture sketches, and explanatory visuals. Use this when Codex must produce standalone SVG assets and text must stay inside boxes without overflow.
metadata:
  short-description: Author robust SVG diagrams
  updated: 2026-04-10
---

# SVG diagrams

Use this skill when creating or editing standalone SVG assets in the repo.

## Default workflow

1. Start from a fixed `viewBox` and explicit box geometry.
2. Treat every text block as width-constrained even though plain SVG does not enforce it.
3. Classify blocks before tuning them:
   - full-width banner or input layer
   - lane card
   - annotation label
   - bottom takeaway or callout bar
4. Wrap text manually with `<tspan>` lines before considering the SVG done.
5. Re-read the final SVG and check every box for text overflow, clipping, and crowding.
6. If the SVG is meant for docs, GitHub, or article publication, validate it in
   at least two renderers before closing the task.

## Hard rules

- Never place long prose in a single `<text>` line inside a box.
- For boxed content, use one `<text>` element with multiple `<tspan x="...">` lines.
- Keep a safety margin of at least 20 px between text and the box border.
- Prefer short lines over dense paragraphs.
- If a block needs more than 5 short lines, enlarge the box or shorten the content.
- Increase canvas height instead of compressing text vertically.
- Do not rely on justification, auto-wrap, or renderer-specific behavior.
- Avoid `foreignObject` unless the user explicitly wants HTML-in-SVG behavior.
- Prefer browser-safe font stacks for publication-oriented figures:
  `Arial, Helvetica, sans-serif` unless the user needs a different visual system.
- Keep arrows out of text blocks; route them through gutters and whitespace.
- Use code pills sparingly. If pills begin to crowd the card, move the detail to
  prose or simplify the card copy.
- Treat top banners and bottom takeaway bars as high-risk blocks. Give them more
  height and padding than ordinary cards.
- Treat cards that mix a title, code pills, and body copy as high-risk too. Reserve
  explicit vertical zones for each layer instead of hand-placing them ad hoc.
- Put annotation labels in dedicated whitespace lanes. Do not let them graze the
  edge of a content card or sit in a text corridor.
- If an annotation label lives between an upper card and a lower band, rebalance that
  whole corridor together instead of squeezing the label into leftover space.
- If a figure still shows overflow after one cleanup pass, stop making tiny local
  nudges. Rebalance the whole lane or enlarge the canvas.
- Only reduce a block size when the reduced geometry still preserves the text
  corridor and the surrounding gutter.

## Practical wrapping heuristics

- Title line: keep under about 40 characters.
- Body line in a medium box: keep under about 38-44 characters.
- Bullet line in a medium box: keep under about 34-40 characters.
- Break at phrase boundaries, not mid-concept.
- When comparing two columns, keep corresponding blocks visually balanced.

## Box checklist

Before finishing, verify each box has:

- a clear title
- no overflowing text
- enough vertical padding
- consistent line spacing
- no lines touching arrows, icons, or dividers
- no pills or badges colliding with body text
- no annotation label overlapping the box or its connector
- enough gutter between stacked title, pill, and body zones inside mixed-content cards

## Rebalance trigger

Switch from micro-tuning to a structural pass when any of these is true:

- the same block still crowds after one fix
- a top banner or bottom callout is close to the line-height limit
- an arrow or annotation reroute steals space from a neighboring text block
- shrinking one box causes a sibling block to crowd again

Structural pass options:

- increase canvas height
- widen the lane and shorten the copy
- move labels into a dedicated annotation lane
- split one dense figure into two simpler figures

## Publication check

For GitHub-facing or article-facing SVGs:

- validate XML
- render once with `rsvg-convert`
- render once with Quick Look or another browser-adjacent renderer
- if either renderer shows crowding, shorten the copy before trying typography tricks
- after reducing or moving a block, re-render the edited figure and re-check the
  neighboring blocks, not only the block you touched
- if the user has already reported the same figure twice, inspect the rendered image
  before replying; do not trust geometry alone

## Minimal pattern

```svg
<rect x="80" y="120" width="320" height="120" rx="16" ry="16"/>
<text x="104" y="152">
  <tspan x="104" dy="0">First wrapped line.</tspan>
  <tspan x="104" dy="22">Second wrapped line.</tspan>
  <tspan x="104" dy="22">Third wrapped line.</tspan>
</text>
```

## Failure mode to avoid

Bad:

```svg
<text x="104" y="152">A long sentence that visually belongs to the box but can overflow because SVG does not wrap it.</text>
```

Good:

```svg
<text x="104" y="152">
  <tspan x="104" dy="0">A long sentence split into</tspan>
  <tspan x="104" dy="22">shorter lines that stay</tspan>
  <tspan x="104" dy="22">inside the box.</tspan>
</text>
```
