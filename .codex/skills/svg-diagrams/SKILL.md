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
3. Wrap text manually with `<tspan>` lines before considering the SVG done.
4. Re-read the final SVG and check every box for text overflow, clipping, and crowding.
5. If the SVG is meant for docs, GitHub, or article publication, validate it in
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

## Publication check

For GitHub-facing or article-facing SVGs:

- validate XML
- render once with `rsvg-convert`
- render once with Quick Look or another browser-adjacent renderer
- if either renderer shows crowding, shorten the copy before trying typography tricks

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
