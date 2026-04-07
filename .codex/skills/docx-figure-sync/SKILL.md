---
name: docx-figure-sync
description: Replace or update embedded figures in DOCX reports while preserving placement, sizing, and nearby captions. Use this skill when a user wants a figure updated inside a Word document, wants SVG/PNG media replaced without rebuilding the whole document manually, or needs related PDF regeneration only when explicitly requested.
license: BSD-3-Clause (see repo LICENSE)
---

# DOCX Figure Sync

## Overview

Use this skill for deterministic figure replacement inside existing DOCX reports.
Prefer the surrounding document layout over ad hoc copy-paste.

## When to use

- Replace an embedded figure in a `.docx`
- Swap a PNG for an SVG-derived render
- Keep figure placement and caption context stable
- Check whether a DOCX/PDF pair stayed structurally valid

## Workflow

1. Identify the target figure and its exact position in the document.
2. Update the editable figure source first when one exists (`.svg`, slide source, or app asset).
3. Replace the embedded media in the DOCX without changing unrelated content.
4. Validate DOCX integrity and openability.
5. Regenerate the PDF only when the user asks or when the task requires visual verification.

## Quick start

List embedded media:

```bash
python scripts/replace_docx_media.py report.docx --list
```

Replace one embedded image:

```bash
python scripts/replace_docx_media.py report.docx \
  --media image35.png \
  --replacement updated.png \
  --output report.updated.docx
```

## Guardrails

- Keep edits surgical; do not rewrite unrelated sections.
- Preserve captions and nearby keywords unless the user asks otherwise.
- If a source figure exists, update it before touching the packaged media.
- Prefer SVG as the editable source of truth when available.

## References

- Read `references/workflow.md` for the replacement and validation checklist.
- Use `scripts/replace_docx_media.py` for deterministic package-level replacement.
