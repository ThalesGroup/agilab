# AGILAB Agent Learnings

This file is the compact correction ledger for recurring AGILAB agent mistakes.
It complements `AGENTS.md`, `AGENT_CONVENTIONS.md`, and repo-managed skills; it
is not a scratchpad or task log.

## When to add a rule

- Add a rule only after a user, reviewer, or failed validation corrects an agent
  behavior that is not already covered by the repo runbooks.
- Write one concrete rule that changes future behavior; avoid generic warnings
  such as "be careful".
- Tighten an existing rule instead of adding a duplicate.
- Promote durable workflow rules into `AGENTS.md`, `AGENT_CONVENTIONS.md`,
  skills, or tests when they become more than a correction note.
- Prune entries when the underlying issue is fixed by code, tooling, or a
  clearer upstream contract.

## Maintenance contract

- Keep this file short enough to read before work; the target ceiling is 120
  lines.
- Run `python3 tools/agent_instruction_contract.py --check` after editing this
  file or any root agent runbook.
- Do not store credentials, private URLs, customer data, or session transcripts
  here.

## Current rules

- When external agent-instruction projects inspire AGILAB, extract the
  AGILAB-native operating primitive and reject generic boilerplate replacement.
