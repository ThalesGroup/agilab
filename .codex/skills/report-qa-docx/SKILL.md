---
name: report-qa-docx
description: Review DOCX reports for missing figures, stale wording, duplicate sections, caption drift, and local consistency issues. Use this skill when a user asks for a quality pass on a Word report, wants to compare exported versus source versions, or needs a review-driven cleanup checklist before delivery.
---

# Report QA DOCX

## Overview

Use this skill for a pragmatic QA pass on report-style DOCX files.
Focus on structural defects, wording drift, and figure/caption consistency.

## When to use

- Check whether figures are missing or orphaned
- Detect duplicated chapter blocks or export artefacts
- Review terminology consistency after edits
- Compare a reviewed/exported DOCX against a working chapter DOCX

## Workflow

1. Scan figure captions and nearby media.
2. Check for stale duplicated sections or repeated chapter exports.
3. Search for terminology drift and known banned/stale phrases.
4. Compare reviewed/exported variants against the working source.
5. Report concrete issues first; patch only what the user asks to change.

## Quick start

```bash
python scripts/check_docx_report.py report.docx
python scripts/check_docx_report.py report.docx --term "Scope:" --term "TS1" --json
```

## Output style

Always report:

- confirmed issues
- likely issues needing visual confirmation
- remaining non-blocking inconsistencies

## References

- Read `references/checklist.md` for the QA checklist.
- Use `scripts/check_docx_report.py` for a deterministic first-pass report.
