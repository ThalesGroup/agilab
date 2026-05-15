---
name: agilab-docs
description: Documentation workflow for AGILAB (sources vs generated HTML, public constraints, consistency checks).
license: BSD-3-Clause (see repo LICENSE)
metadata:
  updated: 2026-05-15
---

# Docs Skill (AGILAB)

Use this skill when editing docs content or docs build tooling for AGILAB.

## Source Of Truth

- Canonical editable docs source is `../thales_agilab/docs/source`.
- The public Pages workflow in `agilab` currently builds from the mirrored
  `docs/source` tree in this repo, so that mirror must be kept in sync with the
  canonical source for published pages to stay correct.
- Refresh the public mirror with
  `uv --preview-features extra-build-dependencies run python tools/sync_docs_source.py --apply --delete`.
  The generated stamp `docs/.docs_source_mirror_stamp.json` is part of the mirror
  contract and must not be edited by hand.
- `docs/html` in this repo is generated output only (including `docs/html/_sources`).
- Never hand-edit files under `docs/html`.
- Do not change visible page labels directly in `docs/html` without regenerating from
  source: this is a frequent cause of stale/publication mismatches.

## Required Workflow (No Direct `docs/html` Edits)

1. Edit the canonical source file under `../thales_agilab/docs/source`.
2. Sync the public mirror from the AGILAB repo root:
   `uv --preview-features extra-build-dependencies run python tools/sync_docs_source.py --apply --delete`
3. If the change touches an SVG diagram, validate the SVG as XML and confirm the
   referencing `.rst` page still points to the intended file.
4. Validate the mirror stamp before committing:
   `uv --preview-features extra-build-dependencies run python tools/sync_docs_source.py --verify-stamp`
5. Rebuild or run the docs profile when the rendered page matters:
   `uv --preview-features extra-build-dependencies run python tools/workflow_parity.py --profile docs`
6. Verify the change exists in both:
   - `../thales_agilab/docs/source/<file>`
   - `docs/source/<file>` when it is part of the public mirror
   - the locally rendered HTML output when a build was run
7. Validate the rendered public page after publish. Prefer checking the HTML page
   that embeds the figure, not a guessed raw asset URL.
8. During an SVG tuning loop, do not publish every micro-retouch. Publish only after
   the local region is stable and both canonical + mirror copies are committed.

If you accidentally edit `docs/html` directly, discard that manual edit and regenerate from source.

## Source vs Published Pages

- The Pages workflow currently builds `docs/html` from `docs/source` in the
  `agilab` repo.
- That means updating only `../thales_agilab/docs/source` is not sufficient for
  public publication; refresh `agilab/docs/source` with `tools/sync_docs_source.py`
  so the mirror stamp stays valid.
- Figures referenced by Sphinx may be copied to `_images/` in the built site, so a
  raw URL such as `/diagrams/foo.svg` can legitimately return `404` even when the
  published page is correct.
- For a mismatch report (old labels still visible online), check:
  1. source in `../thales_agilab/docs/source` is updated,
  2. the mirrored file in `../agilab/docs/source` and the mirror stamp were refreshed,
  3. `../agilab/docs/html` has been regenerated locally for validation,
  4. a publish/redeploy has been triggered after the commit (push to the branch path
     watched by `docs-publish.yaml`).
- Keep a habit of validating one canonical page after publish:
  - confirm `https://thalesgroup.github.io/agilab/agilab-help.html` and sibling pages
    show the new text.

## Commit Guardrail

- Do stage/commit mirrored `docs/source/**` updates and
  `docs/.docs_source_mirror_stamp.json` in `agilab` when a public page depends on
  the change.
- Do not stage or commit `docs/html/**`; it is generated local output and should
  remain outside commits.
- If `docs/html/**` was modified by a local build, leave it unstaged or clean the
  generated output before committing source changes.

## Public Docs Constraint

- Public documentation must not mention non-public apps/repositories.
- Keep examples generic and refer to “external apps repository” rather than naming private app modules.
- Public examples should teach the current public API shape. Prefer exported
  constants, request objects, and stable wrappers over private `AGI._*`
  internals, raw mode bitmasks, stale generated scripts, or legacy event-loop
  snippets.
- When updating public examples, add or refresh a stale-snippet grep/test for the
  old pattern so outdated snippets do not reappear in README, `docs/source`,
  canonical docs, or Hugging Face copy.
- Before a public release or Hugging Face deploy, scan public docs and demo
  packaging for internal competitive wording, private project names, local
  validation paths, and non-public strategy text. Include at least README,
  `docs/source`, canonical `../thales_agilab/docs/source`, and the Hugging Face
  README bundle in the scan.
- Public demo copy must describe AGILAB's capabilities directly. Do not publish
  internal comparison language such as "beats <competitor>", "make it obsolete",
  or named internal competitor positioning.

## Positioning Claim Guardrail

- For framework/tool comparisons, prefer precise current-state wording over
  product marketing shorthand.
- If a competing framework already supports a capability (for example Airflow
  dynamic task mapping / dynamic DAG generation), say so explicitly instead of
  implying AGILAB has feature parity by default.
- Scope operational-footprint claims to AGILAB's real strength:
  lower operational overhead during experimentation and early validation, not a
  blanket replacement for production MLOps/platform operations.
- Do not claim reduced repository footprint unless the statement is backed by a
  concrete repository comparison; this is not an inherent AGILAB property.
- When AGILAB lacks a first-class product primitive, state the current limit
  plainly. Example: AGILAB can express dynamic behavior inside Python stages, but
  it does not yet provide first-class runtime workflow-stage expansion in
  `WORKFLOW`.

## Security / Adoption Audit Docs

- When an audit points to security disclosure, shared-adoption, or production
  boundary wording, check all public entry points together:
  `SECURITY.md`, `README.md`, `README.pypi.md`, `ADOPTION.md`,
  canonical `../thales_agilab/docs/source`, mirrored `docs/source`, and any
  generated guardrail tests.
- Never route suspected vulnerabilities to public GitHub issues, discussions,
  pull requests, or comments. Public docs should route reporters to GitHub
  Private Vulnerability Reporting when available, or to a private AGILAB security
  intake through the usual Thales contact path.
- Keep the audit-facing adoption boundary explicit:
  controlled local evaluation, conditional shared/team use after hardening, and
  no-go as a standalone production MLOps platform.
- If adding or changing an audit/security page, add it to the canonical docs
  toctree, sync the mirror, and update tests/guardrails so stale public-issue
  disclosure wording such as `[SECURITY]` cannot reappear silently.
- Run the security and docs checks that prove the public posture:
  `uv --preview-features extra-build-dependencies run python tools/security_hygiene_report.py --compact`,
  the targeted audit/security docs tests, mirror stamp verification, and
  `uv --preview-features extra-build-dependencies run python tools/workflow_parity.py --profile docs`.
- After pushing docs changes, verify the published HTML page directly. Do not
  call public docs aligned until the Pages workflow succeeds and the new text is
  visible online.

## Build / Validate

- Public mirror sync (from `agilab` repo root):
  - `uv --preview-features extra-build-dependencies run python tools/sync_docs_source.py --apply --delete`
  - `uv --preview-features extra-build-dependencies run python tools/sync_docs_source.py --verify-stamp`
- Docs alignment check without editing files:
  - `uv --preview-features extra-build-dependencies run python tools/sync_docs_source.py --delete`
  - `uv --preview-features extra-build-dependencies run python tools/sync_docs_source.py --verify-stamp`
  - Treat the canonical source and public mirror as locally aligned only when the
    dry run reports `create: 0`, `update: 0`, `delete: 0` and the stamp check is OK.
  - A dirty Git status can still be aligned locally; it means the aligned docs are
    uncommitted/unpublished. Online docs require commit, push, and a successful
    Pages publication before they can be called aligned.
- Public docs parity build (from `agilab` repo root):
  - `uv --preview-features extra-build-dependencies run python tools/workflow_parity.py --profile docs`
- Local Sphinx build (from `../thales_agilab` repo root):
  - `uv sync --group sphinx --dev` (or equivalent environment bootstrap command in your `uv` version).
  - `uv run sphinx-build -n -q -b html docs/source docs/_build/html`
    - Keep `--group sphinx` variants if your installed `uv` supports it for your workflow.
  - Prefer this path when validating canonical docs edits; only sync to `../agilab/docs/source`
    when the page is published through the `agilab` repo workflow.
- Quick mirror validation:
  - verify the canonical change is present in `../thales_agilab/docs/source`.
  - run the mirror sync command from `../agilab`.
  - run the stamp verification command from `../agilab`.
- Publish workflow check (AGILAB public site):
  - `gh workflow run docs-publish.yaml -R ThalesGroup/agilab --ref main`
  - `gh run view <run-id> -R ThalesGroup/agilab --json status,conclusion,url`
  - for a slow or opaque deploy, prefer:
    - `gh run view <run-id> -R ThalesGroup/agilab --json status,conclusion,jobs,url`
      instead of waiting blindly on a watcher

## Newcomer Documentation Review

- Before publishing, do a quick onboarding-focused pass on any edited page:
  - installation flow is executable as written.
  - environment paths are source-agnostic where possible (especially for
    `apps` and workspace directories).
  - when a page mixes an activated environment with a source checkout command,
    avoid bare `cd <checkout> && uv run ...` unless a project-env switch is the
    explicit goal; prefer `uv run --active ...` or document it as a separate
    developer flow.
  - any `app_settings.toml` mention explains both valid seed locations:
    `<project>/app_settings.toml` and `<project>/src/app_settings.toml`.
  - external links and labels are clear, not placeholder or contradictory.
- Regenerate run-config wrappers after `.idea/runConfigurations` changes:
  - `uv --preview-features extra-build-dependencies run python tools/generate_runconfig_scripts.py`

## Consistency Checklist

- Use consistent naming: “Pages”, “Page bundles”, “Apps-pages” (avoid near-duplicate headings).
- Keep diagrams (SVG) aligned with wording; remove stale labels when sections are removed.
- Ensure math renders via Sphinx math extension; keep equations in `.. math::` blocks when needed.
