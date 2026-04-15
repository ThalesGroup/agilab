---
name: svg-diagrams
description: Create or substantially rework repo-native SVG diagrams, architecture sketches, and explanatory visuals. Use this when Codex must produce a standalone SVG asset, define or restructure the layout, and keep text inside boxes without overflow.
license: BSD-3-Clause (see repo LICENSE)
metadata:
  short-description: Build robust SVG diagrams
  updated: 2026-04-14
---

# SVG diagrams

Use this skill when creating a new SVG, doing a major redesign of an existing one,
or turning a rough sketch into a repo-native source-of-truth asset.

If the user only wants a local readability fix on an existing SVG, prefer the
`svg-diagram-tuning` skill instead of redesigning the figure here.

## What this skill is for

- new architecture or system diagrams
- substantial SVG refactors where geometry changes
- repo-native figures for docs, README pages, slides, or reports
- diagrams that must stay editable as plain SVG source
- figures where text wrapping and box sizing must be deterministic

## What this skill is not for

- tiny touch-ups on one arrow or one label
- raster image generation
- HTML layouts disguised as SVG
- diagrams that depend on `foreignObject` unless the user explicitly asks for it

## Default workflow

1. Identify the target medium: docs page, GitHub README, slide, DOCX, or mixed use.
2. Decide whether the job is:
   - new diagram
   - structural redesign
   - local tuning
3. Define a fixed `viewBox`, outer margins, and a small layout grid before drawing.
4. Place major regions first: columns, lanes, cards, legends, or side notes.
5. Add text only after box geometry is stable.
6. Wrap all boxed text manually with `<tspan>` lines.
7. Route arrows after the final box geometry is known.
8. Re-read the final SVG source and visually check overflow, spacing, and connector clarity.

## Hard rules

- Keep one editable SVG as the source of truth.
- Use a fixed `viewBox` and explicit geometry.
- Prefer simple primitives: `rect`, `line`, `path`, `circle`, `text`, `tspan`, `g`.
- Give important groups stable `id` attributes when the structure is non-trivial.
- Treat every text block as width-constrained even though SVG does not enforce wrapping.
- Never leave long prose in one `<text>` line inside a box.
- Keep at least 16-20 px of inner padding around boxed text.
- Increase box size or canvas size before shrinking text aggressively.
- Avoid `transform` stacks when direct coordinates are clearer.
- Avoid `foreignObject`, filters, and renderer-sensitive features unless required.
- Prefer browser-safe font stacks unless the figure already depends on a bundled font.

## Geometry-first layout

Build diagrams in this order:

1. Canvas
2. Lanes or columns
3. Containers and cards
4. Titles and labels
5. Body text
6. Connectors
7. Decorative polish

Do not start by hand-placing text lines and then trying to draw boxes around them.

## Text rules

- Use one `<text>` element per semantic block when possible.
- Use `<tspan x="...">` for each wrapped line.
- Break lines by meaning, not by arbitrary width alone.
- Keep titles short and visually distinct from body text.
- If a block needs more than about 5 short lines, enlarge the block or shorten the copy.
- Keep line spacing explicit and consistent across sibling blocks.
- Prefer balanced semantic wraps across peer cards instead of one-off line breaks.

## Practical wrapping heuristics

- Title line: under about 40 characters
- Body line in a medium card: about 38-44 characters
- Bullet line in a medium card: about 34-40 characters
- Summary banner: widen the banner before breaking an atomic one-line message

## Connector rules

- Route arrows after final geometry, not before.
- Keep connectors out of text corridors.
- Prefer horizontal and vertical segments over unnecessary diagonals.
- Recompute arrow anchors after any box move or resize.
- Keep repeated connectors aligned symmetrically where possible.
- Attach labels to the connector they describe, not to leftover whitespace.

## Visual system guidance

- Define a small, deliberate palette before styling the full figure.
- Reuse a limited set of corner radii, stroke widths, and font sizes.
- Group similar semantics visually: same card family, same note style, same connector class.
- Use whitespace to establish hierarchy before adding decoration.
- Remove decorative lines that no longer add meaning.

## Minimal robust pattern

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 700">
  <defs>
    <style>
      .card { fill: #f8fafc; stroke: #334155; stroke-width: 2; }
      .title { font: 700 24px Arial, Helvetica, sans-serif; fill: #0f172a; }
      .body { font: 400 18px Arial, Helvetica, sans-serif; fill: #334155; }
    </style>
  </defs>

  <g id="example-card">
    <rect class="card" x="80" y="120" width="320" height="140" rx="16" ry="16"/>
    <text class="title" x="104" y="156">Execution layer</text>
    <text class="body" x="104" y="190">
      <tspan x="104" dy="0">Short wrapped line one.</tspan>
      <tspan x="104" dy="24">Short wrapped line two.</tspan>
      <tspan x="104" dy="24">Short wrapped line three.</tspan>
    </text>
  </g>
</svg>
```

## Failure modes to avoid

Bad:

```svg
<text x="104" y="152">A long sentence that overflows because plain SVG will not wrap it for you.</text>
```

Bad:

```svg
<g transform="translate(81.2,119.7) scale(0.98)">
```

Bad:

```svg
<foreignObject x="80" y="120" width="320" height="120">...</foreignObject>
```

Good:

```svg
<text x="104" y="152">
  <tspan x="104" dy="0">A long sentence split into</tspan>
  <tspan x="104" dy="22">shorter semantic lines that</tspan>
  <tspan x="104" dy="22">fit inside the box.</tspan>
</text>
```

## AGILAB docs workflow

Use these rules when the SVG is part of AGILAB documentation:

1. Edit the canonical source under `/Users/agi/PycharmProjects/thales_agilab/docs/source` when that checkout exists.
2. Sync the mirrored public copy under `docs/source` in this repo when the page is published from `agilab`.
3. Do not edit `docs/html` by hand.
4. If the SVG is referenced by an `.rst` page, confirm the path still matches after any move or rename.
5. If the figure belongs to a report or slide asset instead of docs, keep the repo SVG as the editable source and export derivatives only after the SVG is clean.

## Validation checklist

Before finishing, verify:

- the SVG parses as XML
- every text-bearing box has enough padding
- no titles or body lines overflow their boxes
- arrows do not cross labels or body copy
- sibling cards use consistent spacing and line-break rhythm
- legends, notes, and badges have their own visual lane
- the final figure still matches the user's requested scope
- the file remains understandable as source, not only as a rendered image

## Priority order

- eliminate overflow and collisions
- fix the whole local defect class, not just one line
- clarify reading order
- rebalance geometry
- widen blocks
- simplify wording if geometry alone is not enough
- add polish last

## Anti-patterns

- Do not solve every issue by shrinking fonts.
- Do not rely on renderer-specific wrapping behavior.
- Do not keep stale connector coordinates after moving cards.
- Do not use arbitrary line breaks that make sibling blocks feel inconsistent.
- Do not leave the SVG full of unexplained transforms if plain coordinates would work.
- Do not push a barely readable diagram just because it is technically non-overlapping.
