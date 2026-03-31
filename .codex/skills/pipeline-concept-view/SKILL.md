---
name: pipeline-concept-view
description: Add or refine a conceptual pipeline view alongside a generated execution view without hard-coding app semantics into the generic UI. Use this skill when a user wants a pipeline_view.dot/json file, a conceptual architecture diagram, or an app-specific semantic view that complements a generic execution pipeline.
---

# Pipeline Concept View

## Overview

Use this skill to separate semantic architecture from execution mechanics.
The generic pipeline page stays app-agnostic; the app contributes its own conceptual view.

## When to use

- Add `pipeline_view.dot` or `pipeline_view.json`
- Align a conceptual diagram with real app behavior
- Keep `Conceptual view` and `Execution view` consistent

## Workflow

1. Start from actual app behavior, not the ideal architecture.
2. Capture only meaningful semantic stages.
3. Keep the conceptual view in app-owned files.
4. Let the generic UI render it when present.
5. Update the execution labels if the conceptual view reveals naming drift.

## References

- Read `references/schema.md` for the supported file contract.
