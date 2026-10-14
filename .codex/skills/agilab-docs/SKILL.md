---
name: agilab-docs
description: Documentation workflow for AGILAB (sources vs generated HTML, public constraints, consistency checks).
license: BSD-3-Clause (see repo LICENSE)
metadata:
  updated: 2026-10-14
---

# Docs Skill (AGILAB)

Use this skill when editing docs content or docs build tooling for AGILAB.

## Source Of Truth

- The public checkout independently owns its editable `docs/source` tree.
  Public Pages and local docs builds use that tree.
- Do not discover, copy, sync, or build public docs from private
  `thales_agilab/docs/source`, another checkout, or another external source.
  Any docs source selected by `AGILAB_DOCS_SOURCE`, `DOCS_REPOSITORY`, or an
  explicit source argument must resolve to this checkout's own `docs/source`;
  external/private values are rejected before their contents are inspected.
- Generate and validate release/UI evidence in this public checkout:
  `data/release_proof.toml`, `release-proof.rst`, and
  `data/ui_robot_evidence.json` retain their dedicated owner validators.
- Refresh the public tree's integrity stamp with
  `uv --preview-features extra-build-dependencies run python tools/sync_docs_source.py --apply --delete`.
  The source and target default to this checkout's `docs/source`; this command
  stamps the local tree without importing another source. The historical stamp
  filename `docs/.docs_source_mirror_stamp.json` is retained by contract and
  must not be edited by hand. A valid stamp proves local integrity; it does not
  attest synchronization with private or external docs.
- `docs/html` in this repo is generated output only (including `docs/html/_sources`).
- Never hand-edit files under `docs/html`.
- Do not change visible page labels directly in `docs/html` without regenerating from
  source: this is a frequent cause of stale/publication mismatches.

## Required Workflow (No Direct `docs/html` Edits)

1. Edit the source file under this checkout's `docs/source`.
   For release/UI evidence, edit or regenerate the public file and run its
   dedicated proof validator.
2. Refresh the local integrity stamp from the AGILAB repo root:
   `uv --preview-features extra-build-dependencies run python tools/sync_docs_source.py --apply --delete`
3. If the change touches an SVG diagram, validate the SVG as XML, render a local
   preview at the intended docs width, and confirm the referencing `.rst` page
   still points to the intended file. Treat the source SVG, surrounding wording,
   captions, alt text, and rendered page as one alignment
   unit. Do not rely on XML validity alone; inspect the rendered preview for
   clipped text, overlong labels, hidden cards, and unreadable feedback arrows.
4. If the change touches visible UI behavior, page labels, screenshots, GIFs, or
   screenshot-derived diagrams, refresh the corresponding source screenshot
   assets in `docs/source` in the same change. Update captions, alt
   text, and `.rst` references together; refresh the integrity stamp; and inspect the
   rendered page so stale labels, duplicate sidebars, old workflow names, or
   outdated screenshots cannot remain in public docs. Do not hand-edit generated
   `docs/html/_images` or copied Sphinx outputs.
5. Validate the local integrity stamp before committing:
   `uv --preview-features extra-build-dependencies run python tools/sync_docs_source.py --verify-stamp`
   Use the checkout-local default source. Do not provide a private/external
   source or bypass its rejection to obtain a passing check.
6. Rebuild or run the docs profile when the rendered page matters:
   `uv --preview-features extra-build-dependencies run python tools/workflow_parity.py --profile docs`
7. Verify the change exists in:
   - this checkout's `docs/source/<file>`
   - the locally rendered HTML output when a build was run
8. Validate the rendered public page after publish. Prefer checking the HTML page
   that embeds the figure, not a guessed raw asset URL.
9. During an SVG tuning loop, do not publish every micro-retouch. Publish only after
   the local region is stable and the public source changes are committed.

If you accidentally edit `docs/html` directly, discard that manual edit and regenerate from source.

## Source vs Published Pages

- The Pages workflow currently builds `docs/html` from `docs/source` in the
  `agilab` repo.
- Edit this checkout's `docs/source` and refresh its integrity stamp with
  `tools/sync_docs_source.py`; another repository's documentation cannot supply
  public publication inputs.
- `tools/release_proof_report.py --check` remains the independent public
  release-proof owner guard.
- Figures referenced by Sphinx may be copied to `_images/` in the built site, so a
  raw URL such as `/diagrams/foo.svg` can legitimately return `404` even when the
  published page is correct.
- For a mismatch report (old labels still visible online), check:
  1. this checkout's `docs/source` is updated,
  2. the local integrity stamp was refreshed and verified,
  3. this checkout's `docs/html` has been regenerated locally for validation,
  4. a publish/redeploy has been triggered after the commit (push to the branch path
     watched by `docs-publish.yaml`).
- Keep a habit of validating one public page after publish:
  - confirm `https://thalesgroup.github.io/agilab/agilab-help.html` and sibling pages
    show the new text.

## Commit Guardrail

- Do stage/commit public `docs/source/**` updates and
  `docs/.docs_source_mirror_stamp.json` in `agilab` when a public page depends on
  the change.
- For the three public-owned evidence paths, stage the validated generated
  public files and refresh the local stamp with the appropriate owner workflow.
  Never copy private snapshots over public documentation or evidence.
- Do not stage or commit `docs/html/**`; it is generated local output and should
  remain outside commits.
- If `docs/html/**` was modified by a local build, leave it unstaged or clean the
  generated output before committing source changes.

## Public Docs Constraint

- Public documentation must not mention non-public apps/repositories.
- When the user asks to hide or de-emphasize public README/PyPI README badges,
  preserve the badge sources and assets unless removal is explicitly requested.
  Move non-primary badges into a rendered ``<details>`` expander such as
  ``More project badges`` instead of deleting badge markdown, generated SVGs,
  or agent/discovery badge assets.
- Release-proof and install-proof docs that execute the packaged first proof
  should use `agilab[examples]`, not bare `agilab`, because the base package is
  intentionally lean while the demo proof depends on packaged example payloads.
  When changing this command, update public `docs/source` and any
  compatibility/report guard that asserts the proof command.
- Keep examples generic and refer to “external apps repository” rather than naming private app modules.
- Public examples should teach the current public API shape. Prefer exported
  constants, request objects, and stable wrappers over private `AGI._*`
  internals, raw mode bitmasks, stale generated scripts, or legacy event-loop
  snippets.
- When describing notebook export, position it as a runnable `agi-core` runtime
  handoff, not as a UI-only fallback or a local sidecar feature. The public
  claim is that users can keep stage order, runtime hints, review context, and
  executable notebook code usable through the stable core runtime even when the
  AGILAB UI or distributed runtime is not used.
- When updating public examples, add or refresh a stale-snippet grep/test for the
  old pattern so outdated snippets do not reappear in README, `docs/source`,
  or the reviewed Hugging Face export copy.
- Before a public release or Hugging Face deploy, scan public docs and demo
  packaging for internal competitive wording, private project names, local
  validation paths, and non-public strategy text. Include at least README,
  `docs/source` and the narrowly selected Hugging Face README export bundle in
  the scan. Do not include private docs as publication inputs.
- Public demo copy must describe AGILAB's capabilities directly. Do not publish
  internal comparison language such as "beats <competitor>", "make it obsolete",
  or named internal competitor positioning.
- Proof-pack docs must keep the shipped boundary clear. The current first layer
  operates on `run_manifest.json` and writes JSON evidence through commands such
  as `agilab prove`, `verify`, `replay`, `export-lineage`, `policy-check`,
  `cards`, and `metadata-store`. Hash-verifiable `.agipack` archives and
  optional detached Ed25519 signatures are shipped; external Sigstore/SLSA
  attestation remains roadmap unless the implementation and release proof show
  it is shipped.

## Agent-Readable Documentation

When a change improves discoverability for agents, downstream tools, or
machine-readable catalogs, keep human docs and machine-readable indexes aligned.
Useful public patterns include:

- `llms.txt` or a similar compact docs index for agent entry points;
- `agilab.yml` or capability manifests that list shipped commands, packages,
  apps, pages, schemas, and evidence outputs;
- JSON Schema, OpenAPI, or JSON-LD only when there is a real API or stable
  artifact contract to describe;
- links from docs to the exact generated catalog files and the command that
  refreshes them.

Do not publish a catalog entry for a roadmap-only feature. If a catalog mentions
a command, schema, package, app, or page, add a local check or test that proves
the referenced artifact exists and is current.

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
  this checkout's `docs/source` and any
  generated guardrail tests.
- Never route suspected vulnerabilities to public GitHub issues, discussions,
  pull requests, or comments. Public docs should route reporters to GitHub
  Private Vulnerability Reporting when available, or to a private AGILAB security
  intake through the usual Thales contact path.
- Keep the audit-facing adoption boundary explicit:
  controlled local evaluation, conditional shared/team use after hardening, and
  no-go as a standalone production MLOps platform.
- If adding or changing an audit/security page, add it to the public docs
  toctree, refresh the local stamp, and update tests/guardrails so stale public-issue
  disclosure wording such as `[SECURITY]` cannot reappear silently.
- Run the security and docs checks that prove the public posture:
  `uv --preview-features extra-build-dependencies run python tools/security_hygiene_report.py --compact`,
  the targeted audit/security docs tests, local integrity stamp verification, and
  `uv --preview-features extra-build-dependencies run python tools/workflow_parity.py --profile docs`.
- After pushing docs changes, verify the published HTML page directly. Do not
  call public docs aligned until the Pages workflow succeeds and the new text is
  visible online.

## Build / Validate

- Public source integrity (from `agilab` repo root):
  - `uv --preview-features extra-build-dependencies run python tools/sync_docs_source.py --apply --delete`
  - `uv --preview-features extra-build-dependencies run python tools/sync_docs_source.py --verify-stamp`
  - Source and target default to this checkout's `docs/source`. These commands
    refresh and verify local integrity without importing private/external docs.
    Run the dedicated release/UI evidence validators before stamping their
    changed files.
- SVG docs figure preview:
  - Parse the public source SVG with `xml.etree.ElementTree`.
  - Prefer `rsvg-convert -w 1600 -o /tmp/<name>.png <figure>.svg` when available
    because it matches the Sphinx/browser rendering path better than Quick Look.
  - On macOS, `qlmanage -t -s 1600 -o /tmp <figure>.svg` is a useful second
    preview, but check its aspect-ratio behavior before trusting layout.
  - Inspect the PNG at full size; labels must fit their boxes at docs scale.
- Docs alignment check without editing files:
  - `uv --preview-features extra-build-dependencies run python tools/sync_docs_source.py --delete`
  - `uv --preview-features extra-build-dependencies run python tools/sync_docs_source.py --verify-stamp`
  - Treat public source integrity as verified only when the stamp check is OK.
    A self-check does not prove equality with any external documentation tree.
  - A dirty Git status can still pass local validation; it means the docs are
    uncommitted/unpublished. Online docs require commit, push, and a successful
    Pages publication before they can be called aligned.
- Public docs parity build (from `agilab` repo root):
  - `uv --preview-features extra-build-dependencies run python tools/workflow_parity.py --profile docs`
  - This profile resolves its Sphinx dependencies and builds the local public
    `docs/source` into `docs/html`. Use the existing profile instead of another
    repository's environment or docs source.
- Quick source validation:
  - verify the change is present in this checkout's `docs/source`.
  - refresh the local stamp from this checkout's repo root.
  - verify that stamp from the same root.
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
- For docs/SVG alignment asks, report whether the source SVG, `.rst`
  references, captions/alt text, public source, and rendered page all
  agree. Do not call the docs fully aligned after an inspection-only pass if a
  source or published surface still needs to be updated.
- Ensure math renders via Sphinx math extension; keep equations in `.. math::` blocks when needed.
