# Article Checklist

Use this checklist only when the user wants a public-facing post, blog article, or
publication draft.

## Opening

- Open on the concrete incident, not generic AI rhetoric.
- State the contrast clearly:
  - one good fix vs one bad fix
  - same model / same log when supported
  - why the comparison matters
- Mention `coding agent` explicitly when that is part of the point.
- If available, state the real stack early:
  - CLI / agent version
  - model version
  - reasoning effort

## Middle

- Add enough AGILAB context that a non-insider can follow the story.
- If a tooling command is central to the incident, add a short explainer for it:
  - what the command does
  - where it sits in the workflow
  - why seeing it in the error log does not automatically make it the root cause
- Explain why the wrong fix looked reasonable at first.
- Show the wrong fix concretely, ideally with a small diff.
- Show the retained fix concretely, ideally with a small diff.
- Identify the exact abstraction-level mistake.
- Show why the retained fix was narrower or better scoped.
- Keep plan/subscription claims modest unless the corpus really proves them.
- If the article makes a comparative claim, include a short methodology note or
  bias-control section.

## Figures

- Prefer at least one semantic SVG when the article compares two trajectories.
- Best default:
  - same inputs
  - wrong abstraction path
  - right abstraction path
  - outcomes
- Good second figure:
  - incident timeline
- Good tooling explainer figure:
  - the normal command flow
  - the earlier leak point
  - the rejected workaround branch
- A figure should reduce reading effort, not add decoration.
- Use browser-safe fonts and leave enough gutter around arrows and pills.
- If text starts crowding the boxes, shorten the wording before shrinking type.
- Give full-width top banners and bottom takeaway bars extra height and padding.
- Give mixed title-plus-pill-plus-body cards explicit internal zones instead of
  stacking elements by hand.
- Keep labels like `visible error line` in a dedicated whitespace lane, not on
  top of a content card.
- If such a label sits between an upper explainer card and a lower panel, rebalance
  that full corridor rather than moving only the label or only the arrow.
- If a second cleanup pass is needed, rebalance the full figure instead of
  stacking more small nudges.
- After shrinking or moving one block, rerender and recheck the neighboring
  blocks so the crowding does not just move elsewhere.
- If the same figure has drawn repeated complaints, inspect a rendered image before
  declaring it fixed.

## Ending

- End with operational advice, not philosophy.
- Make the reader feel they can improve outcomes with the same model.
- If relevant, include a short checklist for session quality:
  - split sequential bugs
  - reset after pivots
  - ask for leak before patch
  - force layer naming
  - ask for minimal retained fix

## Reach

- If AGILAB is part of the story, include at least one public link:
  - `https://thalesgroup.github.io/agilab/`
  - `https://github.com/ThalesGroup/agilab`

## Tone

- Article, not memo
- Concrete, not promotional
- Confident, not overstated
