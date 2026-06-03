---
name: scientific-svg-figures
description: Create or substantially refine publication-grade scientific and technical SVG figures for reports, slides, README/docs, and DOCX/PDF workflows. Use when the agent needs an editable SVG source of truth for architecture diagrams, methodology/training-loop figures, pipeline/workflow views, comparison grids, result-summary panels, timelines, or annotated system figures where deterministic layout, manual text wrapping, cross-medium readability, and export-safe geometry matter.
license: BSD-3-Clause (see repo LICENSE)
metadata:
  updated: 2026-04-15
---

# Scientific SVG Figures

Use this skill for technical figures that must explain a system, method, experiment, or result clearly at publication size.

If the request is only a tiny readability fix on one existing SVG, use `svg-diagram-tuning` instead. If the work is about a whole reusable visual language across many diagrams, use `advanced-svg-system-design`.

## Quick Start

1. Identify the figure class before drawing.
2. Choose the target surface profile.
3. Define a fixed `viewBox`, margins, and layout lanes.
4. Place containers first, then titles, then wrapped body text, then arrows.
5. Validate at the real output size, not only zoomed in.

Read `references/figure-classes.md` when choosing the figure structure.
Read `references/surface-profiles.md` when sizing for README, Sphinx, slides, or DOCX/PDF export.

## Figure Classes

Use one dominant structure per figure.

- Architecture stack
  Use for system decomposition, layer interaction, deployment, or component boundaries.
- Pipeline or workflow
  Use for ordered stages, data flow, preprocessing/training/inference paths, or app orchestration.
- Training loop or methodology
  Use for RL loops, optimization flow, actor/critic separation, feedback paths, or evaluation cycles.
- Comparison grid
  Use for baseline vs proposal, train vs inference, option A vs B, or KPI comparison.
- Result summary panel
  Use for outcome figures that combine a few metrics, notes, and a takeaway.
- Timeline or sequence
  Use for lifecycle, execution order, release flow, or event progression.

Do not mix figure classes casually. If the figure starts behaving like two figures, split it or subordinate one view into a small inset.

## Workflow

### 1. Define the message

Write the figure goal in one sentence before editing:

- "Show how actor, critic, environment, and rollout storage interact during PPO training."
- "Show the difference between edge-level PPO-GNN and path-level actor-critic routing."
- "Show the end-to-end airborne network data flow from scenario generation to evaluation artifacts."

If the message is not crisp, the geometry will drift.

### 2. Choose the surface first

Pick the main delivery surface before choosing canvas size.

- README/docs/browser: optimize for browser readability and GitHub rendering.
- Slide: optimize for room-distance readability and stronger hierarchy.
- DOCX/PDF report: optimize for print/export safety and moderate density.

If multiple surfaces matter, choose the strictest one first. For most technical figures that means README/browser or DOCX.

### 3. Build geometry before prose

Draw in this order:

1. Canvas and margins
2. Lanes, columns, or regions
3. Containers/cards
4. Titles and short labels
5. Wrapped explanatory text
6. Connectors and arrowheads
7. Notes, legends, and emphasis

Do not place long text first and then improvise boxes around it.

## Scientific Figure Rules

- Keep one editable SVG as the source of truth.
- Use explicit coordinates and a fixed `viewBox`.
- Wrap all boxed text manually with `<tspan>`.
- Reserve explicit gutters for arrows and legends.
- Prefer semantic labels over decorative styling.
- Keep connector routing orthogonal unless a diagonal adds meaning.
- Use stable `id` values on major groups when the figure is non-trivial.
- Prefer widening panels before shrinking text.
- Keep repeated sibling blocks aligned by bottoms, centers, or shared gutters.
- Keep color semantic and redundant with position or shape.
- Treat text overflow, edge-touching, and connector ambiguity as failures.

## Text and Annotation Rules

- Keep titles short and distinct from body text.
- Break body text by meaning, not arbitrary width alone.
- Reserve a bottom gutter between the last body line and footer notes.
- Keep badges, pills, and metric chips short; widen them before wrapping.
- Attach area labels to the area they name and edge labels to the edge they describe.
- If a label starts floating in whitespace, the geometry is wrong.

## Common Technical Cases

### Training or optimization figures

- Separate offline inputs, online loop, and outputs into different visual zones.
- Keep policy/action flow visually distinct from value/critic flow.
- If the figure includes train vs inference, split them explicitly instead of relying only on color.
- Keep reward, loss, or evaluation feedback arrows out of text corridors.

### Comparison figures

- Normalize peer card widths and text rhythm before tuning wording.
- Use the same substructure across peers unless the difference is semantically meaningful.
- Put the actual comparison axis in the title or top-row labels.

### Result summary figures

- Keep the main takeaway visually dominant.
- Do not let small notes compete with the headline metric or conclusion.
- If the figure is really a table, make it a grid instead of pretending it is a flowchart.

## Validation

Before finishing, verify:

- the SVG parses cleanly as XML
- no text crosses a box edge
- titles, notes, and body text follow a consistent rhythm
- arrows still point to the right semantic targets after resizing
- legends and side notes have their own lane
- the final reading order is obvious at first glance
- the figure is readable at the target embedded size

For report-facing figures, validate with the likely final width, not editor zoom.

## Anti-Patterns

- Do not solve every issue by shrinking fonts.
- Do not leave one long `<text>` line inside a bounded card.
- Do not route arrows through dense text zones.
- Do not mix unrelated visual metaphors in one figure.
- Do not keep stale connector coordinates after moving panels.
- Do not preserve decorative dividers that no longer add meaning.
- Do not trust a locally zoomed-in SVG if the target output is GitHub, Sphinx, or DOCX.
