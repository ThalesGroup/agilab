# SVG Tuning Checklist

## First pass

- fix overlaps
- fix cropped text
- sweep sibling elements for the same defect class before stopping
- align arrows with intent
- remove redundant labels
- move decorative rules away from text corridors
- reserve explicit gaps between badges/numbers and titles
- recompute arrow start/end points after any card move or resize
- keep repeated arrows centered and symmetric

## Second pass

- increase minimum font size
- widen dense blocks
- normalize title/body hierarchy
- normalize title alignment across peer blocks
- reduce wording when needed
- wrap long callouts instead of forcing one-line text
- move legends and reading guides into their own stable lane

## Export awareness

- test at the actual placed size
- avoid assuming full-screen readability matches PDF readability
- for GitHub-bound SVGs, test with more than one renderer
- prefer browser-safe fonts over office-specific fonts
