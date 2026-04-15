# Surface Profiles

Use this reference to choose a conservative canvas and typography profile before drawing.

## README / GitHub / Browser

Best for:
- repository figures
- raw SVG viewing
- Sphinx HTML pages

Default profile:
- `viewBox`: about `0 0 1400 900`
- outer margin: `40-60`
- title size: `28-34`
- body size: `18-22`
- note size: `15-18`
- stroke width: `2-3`

Rules:
- treat overflow as a hard failure
- avoid dense prose
- prefer browser-safe fonts
- validate at real embedded width

## Slides

Best for:
- presentations
- demo walk-throughs
- wide landscape figures

Default profile:
- `viewBox`: about `0 0 1600 900`
- outer margin: `50-70`
- title size: `32-40`
- body size: `20-26`
- note size: `16-20`
- stroke width: `2.5-3.5`

Rules:
- favor stronger hierarchy and more whitespace
- keep callouts shorter than in reports
- optimize for room-distance readability

## DOCX / PDF Report

Best for:
- formal reports
- technical annexes
- figures placed in Word then exported to PDF

Default profile:
- `viewBox`: about `0 0 1400 850`
- outer margin: `36-56`
- title size: `24-30`
- body size: `17-21`
- note size: `14-17`
- stroke width: `2-3`

Rules:
- keep text slightly larger than you think is necessary
- avoid over-light colors and hairline strokes
- keep legends compact and detached from the main band
- validate after DOCX placement when possible

## Multi-Surface Strategy

If one SVG must serve many surfaces:

1. design to the strictest surface first
2. keep text moderate, not tiny
3. use a medium-density layout
4. widen cards before reducing font size

In practice:
- browser + report: design like a report figure with browser-safe spacing
- slide + report: favor the report if editability and export fidelity matter

## Export Safety Rules

- Avoid `foreignObject`
- Avoid renderer-sensitive filters and effects
- Keep text as text, not outlines, unless forced by the delivery contract
- Prefer explicit coordinates over stacked transforms
- Keep arrowheads simple and proportional
