# SVG Tuning Checklist

## First pass

- fix overlaps
- fix cropped text
- sweep sibling elements for the same defect class before stopping
- align arrows with intent
- remove redundant labels
- rebalance line breaks by semantic phrase, not by leftover width
- move decorative rules away from text corridors
- remove decorative rules that do not add meaning
- enforce a visible gutter between body copy and footer notes
- enforce a visible gutter between adjacent panels or side callouts
- reserve explicit gaps between badges/numbers and titles
- recompute arrow start/end points after any card move or resize
- keep repeated arrows centered and symmetric
- preserve one-line atomic summary banners unless there is a semantic reason to wrap
- keep lane rules on a deliberate shared axis
- keep vertical connectors centered on the cards they link
- keep local alignment contracts intact: shared bottoms, shared centers, and column
  spacing should survive local edits
- attach section labels to the panel or region they describe
- keep connector annotations visually tied to a specific edge
- if the user restricts the change to only the arrow or only the block, do not move
  the other element as a hidden compensation
- classify the requested move before editing: arrow-only, block-only, text-only, or
  full local rebalance
- when a panel gets shorter, rebalance the inner cards as a family so the lower gutter
  stays intentional
- when a side column moves, move its related badge and connectors by the same delta
- if the same local region is criticized repeatedly, stop nudging one line at a time
  and rebalance that region as a coherent sub-ensemble

## Second pass

- increase minimum font size
- widen dense blocks
- normalize title/body hierarchy
- normalize title alignment across peer blocks
- normalize line-break structure across peer blocks
- recheck previously one-line summary callouts after any global width change
- recheck connector axes after any card width or position change
- recheck area-label anchoring after any panel move
- reduce wording when needed
- wrap long callouts instead of forcing one-line text
- move legends and reading guides into their own stable lane
- question whether lane rules are needed at all before refining them
- if a problem sits in a local cluster, rebalance the full sub-ensemble instead of
  oscillating one connector or one card through successive micro-fixes
- before declaring success, verify that the final state still matches the last user
  constraint about what was allowed to move

## Export awareness

- test at the actual placed size
- avoid assuming full-screen readability matches PDF readability
- for GitHub-bound SVGs, test with more than one renderer
- prefer browser-safe fonts over office-specific fonts
