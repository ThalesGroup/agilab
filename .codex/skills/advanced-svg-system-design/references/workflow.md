# Advanced SVG Checklist

## Scope first

- list the target surfaces
- define the primary source of truth
- decide whether the project has one figure or a figure family
- note whether interactivity, animation, or export fidelity matters most

## System design

- define a grid or spacing rhythm
- define component types: cards, labels, arrows, badges, legends
- define type hierarchy: title, body, annotation, axis, footnote
- define semantic color rules and neutral states
- define connector rules: straight, elbow, curved, crossing policy

## Authoring hygiene

- keep groups named and stable
- keep transforms understandable; avoid deeply nested accidental transforms
- reuse geometry patterns instead of freehand drift
- preserve text as text unless outlining is required

## Export safety

- test in at least two renderers
- test at final size, not only zoomed
- prefer browser-safe fonts unless fonts are shipped with the project
- avoid effects that flatten poorly into PDF or DOCX

## Review questions

- is the hierarchy readable in under 10 seconds?
- can a second editor modify this without reverse-engineering it?
- do repeated components look deliberately consistent?
- do connectors explain causality or only add clutter?
- is there any label that should become a caption or legend instead?
