---
name: agilab-docs
description: Documentation workflow for AGILAB (sources vs generated HTML, public constraints, consistency checks).
license: BSD-3-Clause (see repo LICENSE)
metadata:
  updated: 2026-01-09
---

# Docs Skill (AGILAB)

Use this skill when editing `docs/source` or any docs build tooling.

## Source Of Truth

- `docs/html` is generated: do not hand-edit it.
- Edit `docs/source/*` and regenerate.

## Public Docs Constraint

- Public documentation must not mention non-public apps/repositories.
- Keep examples generic and refer to “external apps repository” rather than naming private app modules.

## Build / Validate

- Local Sphinx build (repo root):
  - `uv --preview-features extra-build-dependencies run python -m sphinx -b html docs/source docs/html`

## Consistency Checklist

- Use consistent naming: “Pages”, “Page bundles”, “Apps-pages” (avoid near-duplicate headings).
- Keep diagrams (SVG) aligned with wording; remove stale labels when sections are removed.
- Ensure math renders via Sphinx math extension; keep equations in `.. math::` blocks when needed.

