---
name: agilab-session-fix-quality
description: Improve AGILAB live debugging session quality so the same coding agent is more likely to reach the right bug origin, compare theories before patching, reset after pivots, and propose the smallest retained fix instead of a broad workaround.
license: BSD-3-Clause (see repo LICENSE)
metadata:
  updated: 2026-04-10
---

# AGILAB Session Fix Quality

Use this skill when the user wants to:

- get a better fix from the same coding agent during a live debugging session
- reduce drift after a blocker change, thread compaction, or topic pivot
- keep the session focused on bug origin rather than the first visible command
- force theory comparison before code changes
- ask for the smallest retained fix instead of the first passing workaround

This skill is for steering a live investigation. If the user wants a retrospective
comparison or a publishable incident write-up, use `agilab-coding-agent-postmortem`
instead.

## Core Rule

Do not let the session jump from visible failure to code patch in one move.

Prefer this sequence:

1. freeze the current bug
2. classify the failing layer
3. identify where the bad value first enters the system
4. compare at least two theories
5. only then discuss code changes

## Live Workflow

### 1. Freeze the current bug

As soon as one blocker is resolved, declare it closed and restate only the new
failure.

Good pattern:

- `The scipy conflict is resolved. Ignore it. Analyze only the new worker failure.`

Do not let the previous root cause remain as ambient context.

### 2. Force classification before patching

Ask the model to name the primary failing layer before it proposes code.

Default layer choices:

- dependency metadata
- staging
- subprocess environment
- path resolution
- workflow design

If the model names more than one layer, ask:

- `Which layer first creates the bad value?`

### 3. Ask where the bad value first enters the system

Before accepting a fix proposal, require:

- the exact file or step where the bad value is first introduced
- the first point where that bad value becomes visible in logs or behavior
- the narrowest reproducer that separates source from symptom

This is the fastest way to stop a session from overfitting to the first visible
failing command.

### 4. Make the model compare theories before coding

Do not accept the first plausible mechanism.

Ask for:

- Theory A
- Theory B
- the evidence that would discriminate between them

If the model cannot state what evidence would separate the theories, the session
is not ready to patch.

### 5. Reset after a real pivot

Treat the session as contaminated and force a reset when any of these happens:

- a previous blocker has been resolved
- the subsystem under discussion changes
- the model already proposed one broad fix that you rejected
- the thread has become long, compacted, or multi-topic

Reset by starting a fresh thread or by forcing a short restatement of the new
failure only.

### 6. Require extra justification before changing shared core

When the first proposed fix touches shared core, require a justification first.

The model must answer:

- why an app-local fix is insufficient
- what the blast radius is
- which design invariant would change

If those answers are weak, reject the shared-core move and keep investigating.

### 7. Ask for the minimal retained fix

Prefer:

- `propose the smallest fix we should keep in main`

Do not settle for:

- `make the failing install pass`

This wording change sharply improves the quality bar.

## Prompt Shape

Use this template when the session is drifting:

> Ignore previously resolved blockers. Analyze only the current failure. Classify
> it as symptom, visible mechanism, and bug origin. Identify the first file or
> step that introduces the bad value. Give two competing theories, the evidence
> that would discriminate between them, and the smallest retained fix we should
> keep in main if the leading theory is confirmed.

If the answer jumps directly to code without first naming the layer and the
first point where the bad value is introduced, stop and ask again.

## AGILAB-Specific Reminders

- A visible `uv` command in the logs is not automatically the place where the
  bug begins.
- When a new error appears after a previous one was fixed, treat it as a new
  analysis object.
- Broad shared-core workarounds are easy to justify too early. Keep the burden
  of proof high.

Read `references/checklist.md` when you need the short operational version.
