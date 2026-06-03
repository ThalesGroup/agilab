# Plan-before-code workflow

Use this reference when the task is large enough that a one-line plan is not enough.

## Lightweight pattern

Use this when the task is bounded and local.

1. Confirm the goal.
2. Read the likely file or failing test.
3. Write a 2-4 step plan.
4. Check the one assumption that could invalidate the fix.
5. Edit.
6. Run one targeted verification.

Example:

- inspect failing helper
- patch the path resolution
- add a regression test
- rerun the targeted test file

## Strict pattern

Use this when work is ambiguous, risky, or spread across components.

1. Inspect the current implementation and failure evidence.
2. List likely touch points.
3. Decide the execution order.
4. Identify assumptions to verify before editing.
5. Edit one logical unit at a time.
6. Re-check plan validity after each meaningful discovery.
7. Run targeted tests, then broader checks if needed.
8. Report residual risk explicitly.

## Assumption checklist

Before the first edit, try to verify:

- correct file or module
- correct runtime path
- current failing behavior
- dependency or packaging scope
- whether the same bug class exists in sibling code

## Escalation rule

If the task touches shared core, release machinery, installer logic, or anything with
clear blast radius, default to strict mode.

## Completion rule

The task is not done until one of these is true:

- the relevant validation passed
- or you explicitly state why validation could not be run
