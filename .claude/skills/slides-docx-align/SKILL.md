---
name: slides-docx-align
description: Align a slide deck with a DOCX report while preserving each artifact’s role. Use this skill when a user wants missing report figures inserted into slides, terminology synchronized across report and deck, or extra slides added without overwriting the current summary version.
license: BSD-3-Clause (see repo LICENSE)
---

# Slides DOCX Align

## Overview

Use this skill when a report and a slide deck have drifted apart.
Keep the deck usable while making the report and slides say the same thing.

## When to use

- Add a report figure into slides
- Keep the current slide summary and add a supporting slide
- Synchronize terminology between a DOCX and a PPTX
- Check for missing conceptual or educational content in slides

## Workflow

1. Treat the DOCX as the content source unless the user says otherwise.
2. Identify what is missing in the deck versus what should stay summarized.
3. Add new slides instead of overwriting existing summary slides when both are useful.
4. Keep figure titles, keywords, and terminology aligned.
5. When editing a generated deck or a `python-pptx` builder, normalize layout rules in helpers first before nudging one slide at a time.
6. For repeated cards, pills, badges, and callouts, keep one shared vertical text contract:
   - same vertical anchor for the same family
   - same top/bottom margins for the same family
   - no one-off text offsets unless the content is semantically different
7. Validate the rendered deck, not just the source geometry. Prefer exporting through LibreOffice or PowerPoint and checking the actual slides for:
   - clipped or wrapped text
   - inconsistent vertical centering
   - labels that sit too high or too low inside repeated blocks
   - banners or callouts that look visually off even if coordinates seem correct
8. Export deck outputs only if requested.

## Guardrails

- If a pill or badge family requires repeated `top + 0.03` style fixes, stop and move that behavior into the helper.
- Do not mix top-aligned and middle-aligned text inside peer blocks without a clear semantic reason.
- When one slide family uses centered labels, keep the same visual center across the deck.
- For generated decks, fix alignment at the builder/helper level whenever the same defect appears more than once.

## References

- Read `references/alignment.md` for the alignment rules.
