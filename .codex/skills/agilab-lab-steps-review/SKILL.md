---
name: agilab-lab-steps-review
description: Review AGILab lab_steps.toml files for readability, inferred IO flow, and step naming quality. Use this skill when a user wants a pipeline clarified, wants labels cleaned up without changing behavior, or needs the execution flow made easier to understand in the PIPELINE page.
---

# AGILab Lab Steps Review

## Overview

Use this skill to improve how `lab_steps.toml` communicates a pipeline.
Focus on names, IO semantics, and whether the execution flow matches the intended architecture.

## When to use

- Review a dense `lab_steps.toml`
- Rename steps to be more semantic
- Align execution labels with a conceptual view
- Reduce redundant `data_in` / `data_out` noise in displays

## Workflow

1. Parse the steps in execution order.
2. Identify what each step really contributes.
3. Rename steps for business meaning, not internal implementation alone.
4. Keep execution behavior unchanged unless the user explicitly wants runtime changes.
5. Validate that the resulting flow is still truthful.

## References

- Read `references/review-checklist.md` for the review checklist.
