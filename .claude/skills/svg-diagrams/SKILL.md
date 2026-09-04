---
name: svg-diagrams
description: Create a simple standalone repo-native SVG or directly edit its boxes, text, and connectors. Use for one-off architecture sketches and explanatory visuals; use svg-diagram-tuning for repair of an existing crowded figure, scientific-svg-figures for publication-grade technical figures, and advanced-svg-system-design for a reusable multi-figure visual system.
license: BSD-3-Clause (see repo LICENSE)
metadata:
  short-description: Author robust SVG diagrams
  updated: 2026-09-04
---

# SVG diagrams

Use this skill when creating or editing standalone SVG assets in the repo.

## Default workflow

1. Start from a fixed `viewBox` and explicit box geometry.
2. Treat every text block as width-constrained even though plain SVG does not enforce it.
3. Wrap text manually with `<tspan>` lines before considering the SVG done.
4. Re-read the final SVG and check every box for text overflow, clipping, and crowding.
5. Run `scripts/check_svg_markers.py` from this skill directory when the SVG uses arrow markers.

## Hard rules

- Never place long prose in a single `<text>` line inside a box.
- For boxed content, use one `<text>` element with multiple `<tspan x="...">` lines.
- Keep a safety margin of at least 20 px between text and the box border.
- Prefer short lines over dense paragraphs.
- If a block needs more than 5 short lines, enlarge the box or shorten the content.
- Increase canvas height instead of compressing text vertically.
- Do not rely on justification, auto-wrap, or renderer-specific behavior.
- Avoid `foreignObject` unless the user explicitly wants HTML-in-SVG behavior.

## Arrow-marker contract

- Declare `markerUnits` on every `<marker>`; never depend on the SVG default.
- Prefer `markerUnits="userSpaceOnUse"` when arrowhead size must remain stable as connector stroke widths change.
- Use explicit `markerUnits="strokeWidth"` only when proportional arrowhead scaling is deliberate.
- Give each marker a stable `id`, and verify every `url(#...)` marker reference resolves in the same SVG.
- Recalculate connector endpoints after moving a block. Keep arrowheads outside text and stop the line at the target boundary.
- Validate markers with `python3 .codex/skills/svg-diagrams/scripts/check_svg_markers.py path/to/figure.svg` when using the Codex mirror, or the equivalent `.claude/skills/...` path from the canonical tree.

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
