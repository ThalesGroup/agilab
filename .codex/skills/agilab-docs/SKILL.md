---
name: agilab-docs
description: Documentation workflow for AGILAB (sources vs generated HTML, public constraints, consistency checks).
license: BSD-3-Clause (see repo LICENSE)
metadata:
  updated: 2026-02-20
---

# Docs Skill (AGILAB)

Use this skill when editing docs content or docs build tooling for AGILAB.

## Source Of Truth

- Canonical editable docs source is `../thales_agilab/docs/source`.
- `docs/html` in this repo is generated output only (including `docs/html/_sources`).
- Never hand-edit files under `docs/html`.

## Required Workflow (No Direct `docs/html` Edits)

1. Edit the canonical source file under `../thales_agilab/docs/source`.
2. Rebuild generated docs into this repo's `docs/html`.
3. Verify the change exists in both:
   - `../thales_agilab/docs/source/<file>`
   - `docs/html/<file>` (or `docs/html/_sources/<file>.txt`)

If you accidentally edit `docs/html` directly, discard that manual edit and regenerate from source.

## Commit Guardrail

- Do not stage or commit `docs/html/**` changes unless:
  1. a corresponding source edit exists under `../thales_agilab/docs/source/**`, and
  2. `docs/html/**` was regenerated from that source.
- If `docs/html/**` was modified by bulk replace/refactor unrelated to docs regeneration,
  revert those generated-file edits before committing.

## Public Docs Constraint

- Public documentation must not mention non-public apps/repositories.
- Keep examples generic and refer to “external apps repository” rather than naming private app modules.

## Build / Validate

- Local Sphinx build (from `agilab` repo root):
  - `uv --preview-features extra-build-dependencies run --project ../thales_agilab --group sphinx python -m sphinx -b html ../thales_agilab/docs/source docs/html`
- Regenerate run-config wrappers after `.idea/runConfigurations` changes:
  - `uv --preview-features extra-build-dependencies run python tools/generate_runconfig_scripts.py`

## Consistency Checklist

- Use consistent naming: “Pages”, “Page bundles”, “Apps-pages” (avoid near-duplicate headings).
- Keep diagrams (SVG) aligned with wording; remove stale labels when sections are removed.
- Ensure math renders via Sphinx math extension; keep equations in `.. math::` blocks when needed.
