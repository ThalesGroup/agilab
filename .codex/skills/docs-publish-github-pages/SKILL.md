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

## References

- Read `references/checklist.md` for the publish-debug checklist.
