---
name: plan-before-code
description: Plan before editing code. Use this skill for multi-step implementation, debugging, refactors, release work, or any coding task where sequencing, assumptions, or validation matter. It enforces a short plan first, validates assumptions before edits, and verifies results before close-out.
license: Private local skill
metadata:
  updated: 2026-04-16
---

# Plan Before Code

Use this skill to force a planning pass before coding.
The goal is not paperwork. The goal is to improve sequencing, reduce avoidable edits,
and catch bad assumptions before touching files.

## When to use

- Multi-file changes
- Bug fixes with unclear root cause
- Refactors
- Release or packaging work
- Tests or docs that depend on code behavior
- Any task where validation matters before execution

## Skip only for trivial tasks

You may skip an explicit visible plan only when all of these are true:

- the task is local and obvious
- one file is affected
- the edit is mechanically safe
- failure impact is negligible

Even then, still make a private micro-plan before editing.

## Modes

Choose one mode before editing.

### Lightweight mode

Use for bounded work with low ambiguity.

- Restate the goal in one sentence
- Identify likely files or components
- Make a 2-4 step plan
- Validate the critical assumption
- Edit
- Run targeted verification

### Strict mode

Use for risky or multi-step work.

- Inspect the current implementation first
- Identify touch points and likely blast radius
- Produce an ordered plan
- Validate assumptions before the first edit
- Execute one step at a time
- Re-plan if facts change
- Verify each critical change
- Summarize residual risk at the end

## Required workflow

1. Understand the real task.
   - Separate the user request from the likely root problem.
   - If the task mentions a symptom, inspect the cause before proposing edits.

2. Inspect before proposing a fix.
   - Read the relevant files.
   - Check logs, failing tests, or current behavior when available.
   - Do not start editing from memory.

3. Create the plan before coding.
   - Use a short visible plan for substantial work.
   - For complex work, use the planning tool if available.
   - The plan should be ordered, concrete, and testable.
   - In `agilab`, run
     `uv --preview-features extra-build-dependencies run python tools/impact_validate.py --staged`
     or `--files ...` if a diff already exists, and use its output to shape the plan.

4. Validate assumptions before execution.
   - Confirm the file path, call site, dependency, config source, or failing case.
   - If a key assumption is unverified and easy to check, check it first.
   - Do not code around uncertainty when inspection can remove it.

5. Execute in sequence.
   - Change one logical unit at a time.
   - Keep the write scope aligned with the plan.
   - If reality diverges from the plan, stop and re-plan before continuing.

6. Verify before declaring success.
   - Prefer targeted tests first.
   - Use the narrowest validation that proves the fix.
   - If validation was not possible, say so explicitly.
   - In `agilab`, prefer the validations and artifact refreshes reported by
     `tools/impact_validate.py` over ad hoc guesses.

7. Close with outcome and remaining risk.
   - What changed
   - What was verified
   - What is still unverified or risky

## Planning quality bar

A good plan:

- names the concrete files or modules likely involved
- separates inspection from editing
- includes at least one validation step
- is short enough to execute without drift
- can be updated when facts change

A bad plan:

- repeats the user request without sequencing
- skips inspection
- assumes the cause before checking
- lumps unrelated edits together
- has no validation step

## Guardrails

- Do not code first and invent the plan afterwards.
- Do not jump to a core/shared fix when an app-local fix may be enough.
- In `agilab`, do not skip `tools/impact_validate.py` for multi-file diffs or risky bug fixes when it
  can clarify shared-core, installer, badge, or skill-index impact.
- Do not treat “I know this codebase” as evidence.
- Do not let a plan become stale after new evidence appears.
- Do not over-plan tiny work; choose the lightest mode that still protects quality.

## Expected visible behavior

For substantial tasks, the user should see:

- a short statement of what is being checked first
- a concise plan before edits
- an update when the diagnosis changes
- validation before final close-out

## References

- Read `references/workflow.md` when you need the strict checklist or examples of
  lightweight versus strict planning.
