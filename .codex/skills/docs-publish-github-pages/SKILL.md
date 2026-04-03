---
name: docs-publish-github-pages
description: Review, fix, and validate docs publishing workflows for GitHub Pages. Use this skill when a user needs a docs deploy workflow corrected, wants versioning behavior explained, needs publish triggers adjusted, or wants a Pages deployment flow verified end to end.
---

# Docs Publish GitHub Pages

## Overview

Use this skill for GitHub Pages documentation pipelines.
Focus on trigger logic, deploy behavior, version visibility, and what is actually published.

## When to use

- Docs version online is stale
- Workflow triggers do not match expected publish behavior
- Pages is misconfigured or disabled
- The repo publishes from a branch or workflow but the site disagrees

## Workflow

1. Confirm which repository and Pages site the user is actually looking at.
2. Inspect the docs publish workflow triggers.
3. Check whether the workflow succeeded and whether Pages is enabled.
4. Explain the difference between package version, git tag, and published site version.
5. Patch triggers or gating logic only after verifying the current deploy path.
6. For AGILAB, prefer validating published HTML pages over guessed raw asset URLs.

## AGILAB Notes

- Repository: `ThalesGroup/agilab`
- Workflow: `.github/workflows/docs-publish.yaml`
- Public site: `https://thalesgroup.github.io/agilab/`
- The workflow can be triggered manually with:
  - `gh workflow run docs-publish.yaml -R ThalesGroup/agilab --ref main`
- Inspect a run with:
  - `gh run view <run-id> -R ThalesGroup/agilab --json status,conclusion,url`
- Figure assets referenced from Sphinx pages may be copied under `_images/`, so a
  path like `/diagrams/pipeline_example.svg` can return `404` even when the docs
  deploy is healthy. Verify the page that embeds the figure.

## References

- Read `references/checklist.md` for the publish-debug checklist.
