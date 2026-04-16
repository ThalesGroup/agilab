---
name: codex-session-learning
description: Turn past Codex debugging sessions into reusable bug-fix guidance, prompt templates, and validation rules. Use this skill when the user wants to learn from prior sessions, extract bug/postmortem cases, route future bug logs into stronger prompts, or build an explicit prompt-improvement loop instead of relying on hidden memory.
license: BSD-3-Clause (see repo LICENSE)
metadata:
  updated: 2026-04-16
---

# Codex Session Learning

Use this skill to convert prior Codex work into explicit reusable assets.
The goal is not to pretend the agent has hidden long-term memory. The goal is to
extract structured cases, reusable prompt patterns, and validation rules from
earlier sessions so future bug fixing starts from a stronger prompt.

## When to use

- Build a bug-fix prompt from one or more prior Codex sessions
- Turn chat logs or tracebacks into reusable postmortem cases
- Create a bug taxonomy for recurring AGILAB failures
- Derive validation rules from successful or failed fixes
- Build a prompt-routing layer that chooses investigation order before coding

## Do not use for

- direct code editing with no session-learning goal
- generic “summarize this chat” work with no bug-fix reuse target
- pretending the model automatically learned from earlier sessions

If the source material is a raw transcript or JSON export, use `chat-export`
first when needed to normalize it.

## Core idea

Use past sessions to learn process, not to blindly replay patches.

Extract:

- the bug family
- the real failure surface
- the files inspected first
- the first wrong turns
- the fix pattern that worked
- the validation depth required before push

Then feed those results into a future prompt as explicit guidance.

## Workflow

1. Define the learning target.
   - `prompt-routing`: choose the right initial debugging plan
   - `postmortem`: capture why the bug happened and how to prevent it
   - `validation-policy`: decide what must be tested before push
   - `case-library`: build reusable examples for recurring failures
2. Normalize the session inputs.
   - Gather traceback, command context, edited files, tests run, and outcome.
   - Strip noise such as repeated logs or irrelevant tool chatter.
3. Extract one case per real bug.
   - Record the initial symptom separately from the root cause.
   - Record whether the first attempted fix was wrong or incomplete.
4. Generalize the reusable rule.
   - Convert one bug into a rule such as:
     - `missing import after refactor -> inspect extracted support modules and import wiring first`
     - `installer solver drift -> compare source app manifest with copied worker manifest before editing app dependencies`
5. Build the prompt asset.
   - Prefer structured prompt controls over free-form prose.
   - Good outputs include:
     - bug family
     - suspected scope
     - first files to inspect
     - likely false fixes to avoid
     - minimum validation to require
6. Close the loop after the next session.
   - Mark whether the routed prompt improved first-pass success.
   - Update the case if the new session revealed a better diagnosis path.

## Recommended outputs

- `session_case.json` or `session_case.md`
- `bug_taxonomy.md`
- `prompt_template.md`
- `validation_rules.md`
- `next_prompt.md`

## Prompt-building pattern

Do not ask a routing model or rules table to write the final fix prompt from
scratch. Use it to choose controls that a prompt builder assembles.

Prefer prompt controls such as:

- `bug_family`
- `scope`
- `first_checks`
- `avoid_moves`
- `required_validation`
- `push_gate`

Then generate a concrete prompt that tells Codex:

- what to inspect first
- what assumptions must be checked before edits
- what class of fix to avoid
- what validation is required before push

## Quality bar for a useful case

A good case includes:

- exact symptom
- execution context such as install, service, page render, or test run
- root cause
- smallest correct fix
- why earlier attempts failed or would have failed
- validation that actually proved the fix
- reusable rule for next time

A weak case only records:

- the traceback
- the final patch
- a vague “fixed by adding import” summary

## AGILAB-specific bug families worth tracking

- refactor regressions after helper extraction or support-module splits
- installer dependency drift between source app and copied worker manifest
- Streamlit session-state and rerun bugs
- service-state or cluster-share persistence failures
- coverage/badge mismatches caused by stale generated artifacts
- app-settings seed/workspace confusion

Read `references/schema.md` when you need a concrete case schema and a prompt-pack
layout.

## Guardrails

- Do not treat one successful patch as a universal rule.
- Do not train on noisy sessions without separating symptom from root cause.
- Do not encode “always push after green unit tests” as policy; keep validation
  context-specific.
- Do not hide uncertainty. If the session data is incomplete, record the gap.
- Do not replace repo-specific runbooks or test skills; use this skill to route
  into them.

## Good pairings

- `chat-export` for transcript normalization
- `plan-before-code` for prompt sections that enforce inspection before edits
- `agilab-testing` for repo-specific validation rules
- `agilab-installer` when the learned cases are install or worker-manifest failures
- `agilab-streamlit-pages` when the learned cases are Streamlit/session-state failures
