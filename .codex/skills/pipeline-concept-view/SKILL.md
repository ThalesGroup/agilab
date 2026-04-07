---
name: pipeline-concept-view
description: Add or refine a conceptual pipeline view alongside a generated execution view without hard-coding app semantics into the generic UI. Use this skill when a user wants a pipeline_view.dot/json file, a conceptual architecture diagram, or a lab_steps.toml reviewed for clearer naming, IO flow, and semantic alignment with the PIPELINE page.
license: BSD-3-Clause (see repo LICENSE)
---

# Pipeline Concept View

## Overview

Use this skill to separate semantic architecture from execution mechanics.
The generic pipeline page stays app-agnostic; the app contributes its own conceptual
view and clearer pipeline semantics.

## When to use

- Add `pipeline_view.dot` or `pipeline_view.json`
- Align a conceptual diagram with real app behavior
- Keep `Conceptual view` and `Execution view` consistent
- Review `lab_steps.toml` for readability and step naming quality
- Clarify inferred IO flow without changing runtime behavior

## Workflow

1. Start from actual app behavior, not the ideal architecture.
2. Review the current `lab_steps.toml` in execution order when present.
3. Capture only meaningful semantic stages.
4. Rename or regroup labels for business meaning rather than implementation noise.
5. Keep the conceptual view in app-owned files.
6. Let the generic UI render it when present.
7. Update execution labels if the conceptual view or step review reveals naming drift.
8. Keep behavior unchanged unless the user explicitly wants runtime changes.

## References

- Read `references/schema.md` for the supported file contract.
- Read `references/lab_steps_review.md` when the task is mainly about clarifying
  `lab_steps.toml`.
