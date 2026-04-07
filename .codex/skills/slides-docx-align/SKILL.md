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
5. Export deck outputs only if requested.

## References

- Read `references/alignment.md` for the alignment rules.
