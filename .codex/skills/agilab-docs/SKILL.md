---
name: agilab-docs
description: Documentation workflow for AGILAB (sources vs generated HTML, public constraints, consistency checks).
license: BSD-3-Clause (see repo LICENSE)
metadata:
  updated: 2026-04-03
---

# Docs Skill (AGILAB)

Use this skill when editing docs content or docs build tooling for AGILAB.

## Source Of Truth

- Canonical editable docs source is `../thales_agilab/docs/source`.
- The public Pages workflow in `agilab` currently builds from the mirrored
  `docs/source` tree in this repo, so that mirror must be kept in sync with the
  canonical source for published pages to stay correct.
- `docs/html` in this repo is generated output only (including `docs/html/_sources`).
- Never hand-edit files under `docs/html`.
- Do not change visible page labels directly in `docs/html` without regenerating from
  source: this is a frequent cause of stale/publication mismatches.

## Required Workflow (No Direct `docs/html` Edits)

1. Edit the canonical source file under `../thales_agilab/docs/source`.
2. Sync the corresponding file into this repo's mirrored `docs/source` when the
   published Pages site depends on it.
3. If the change touches an SVG diagram, validate the SVG as XML and confirm the
   referencing `.rst` page still points to the intended file.
3. Rebuild generated docs into this repo's `docs/html`.
4. Verify the generated page renders the updated labels in:
   - `docs/html/<page>.html`
   - any sidebar or navigation fragments in the same HTML build
5. Verify the change exists in both:
   - `../thales_agilab/docs/source/<file>`
   - `docs/source/<file>` when it is part of the public mirror
   - `docs/html/<file>` (or `docs/html/_sources/<file>.txt`)
6. Validate the rendered public page after publish. Prefer checking the HTML page
   that embeds the figure, not a guessed raw asset URL.
7. During an SVG tuning loop, do not publish every micro-retouch. Publish only after
   the local region is stable and both canonical + mirror copies are committed.

If you accidentally edit `docs/html` directly, discard that manual edit and regenerate from source.

## Source vs Published Pages

- The Pages workflow currently builds `docs/html` from `docs/source` in the
  `agilab` repo.
- That means updating only `../thales_agilab/docs/source` is not sufficient for
  public publication; the mirrored `agilab/docs/source` copy must also be
  refreshed when the page is public.
- Figures referenced by Sphinx may be copied to `_images/` in the built site, so a
  raw URL such as `/diagrams/foo.svg` can legitimately return `404` even when the
  published page is correct.
- For a mismatch report (old labels still visible online), check:
  1. source in `../thales_agilab/docs/source` is updated,
  2. the mirrored file in `../agilab/docs/source` was refreshed when needed,
  3. `../agilab/docs/html` has been regenerated locally for validation,
  4. a publish/redeploy has been triggered after the commit (push to the branch path
     watched by `docs-publish.yaml`).
- Keep a habit of validating one canonical page after publish:
  - confirm `https://thalesgroup.github.io/agilab/agilab-help.html` and sibling pages
    show the new text.

## Commit Guardrail

- Do stage/commit mirrored `docs/source/**` updates in `agilab` when a public
  page depends on the change.
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
- Publish workflow check (AGILAB public site):
  - `gh workflow run docs-publish.yaml -R ThalesGroup/agilab --ref main`
  - `gh run view <run-id> -R ThalesGroup/agilab --json status,conclusion,url`
  - for a slow or opaque deploy, prefer:
    - `gh run view <run-id> -R ThalesGroup/agilab --json status,conclusion,jobs,url`
    instead of waiting blindly on a watcher
- Regenerate run-config wrappers after `.idea/runConfigurations` changes:
  - `uv --preview-features extra-build-dependencies run python tools/generate_runconfig_scripts.py`

## Consistency Checklist

- Use consistent naming: “Pages”, “Page bundles”, “Apps-pages” (avoid near-duplicate headings).
- Keep diagrams (SVG) aligned with wording; remove stale labels when sections are removed.
- Ensure math renders via Sphinx math extension; keep equations in `.. math::` blocks when needed.
