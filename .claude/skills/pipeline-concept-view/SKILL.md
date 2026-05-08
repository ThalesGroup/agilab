---
name: pipeline-concept-view
description: Add or refine a conceptual workflow view alongside a generated execution view without hard-coding app semantics into the generic UI. Use this skill when a user wants a pipeline_view.dot/json file, a conceptual architecture diagram, or a lab_stages.toml reviewed for clearer naming, IO flow, and semantic alignment with the WORKFLOW page.
license: BSD-3-Clause (see repo LICENSE)
---

# Workflow Concept View

## Overview

Use this skill to separate semantic architecture from execution mechanics.
The generic WORKFLOW page stays app-agnostic; the app contributes its own conceptual
view and clearer workflow semantics.

## When to use

- Add `pipeline_view.dot` or `pipeline_view.json`
- Align a conceptual diagram with real app behavior
- Keep `Conceptual view` and `Execution view` consistent
- Review `lab_stages.toml` for readability and step naming quality
- Clarify inferred IO flow without changing runtime behavior

## Workflow

1. Start from actual app behavior, not the ideal architecture.
2. Review the current `lab_stages.toml` in execution order when present.
3. Capture only meaningful semantic stages.
4. Rename or regroup labels for business meaning rather than implementation noise.
5. Keep the conceptual view in app-owned files.
6. Let the generic UI render it when present.
7. Update execution labels if the conceptual view or step review reveals naming drift.
8. Keep behavior unchanged unless the user explicitly wants runtime changes.

## Naming Boundary

- Keep `pipeline_view.dot` / `pipeline_view.json` as the file contract unless the
  repository migrates the schema.
- Use `WORKFLOW` for the page name and `Workflow graph` for the user-facing graph
  label.
- Avoid reintroducing `PIPELINE` as a visible page label in docs, tests, screenshots,
  or demo scripts.

## References

- Read `references/schema.md` for the supported file contract.
- Read `references/lab_stages_review.md` when the task is mainly about clarifying
  `lab_stages.toml`.
