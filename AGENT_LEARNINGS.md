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

- When asked to hide badges or public README metadata, do not interpret
  "hide" as deletion. Keep badge source/assets available and move secondary
  badges into a rendered expander unless the user explicitly asks for removal.
- When external agent-instruction projects inspire AGILAB, extract the
  AGILAB-native operating primitive and reject generic boilerplate replacement.
- When a pre-push guard fails, do not bypass it silently. Re-run the underlying
  guard with useful output, classify whether the failure belongs to the current
  diff, a real repository contract, or polluted local filesystem state, then
  fix the right layer or document the exact unrelated failure before pushing.
- When changing visible UI action labels, audit sibling pages for semantic
  collisions before closing. The same visible button text must not mean
  different operations across pages; use scoped labels and update page tests and
  robot click-label coverage with the split.
- Product-copy renames must not force stable API renames. For ORCHESTRATE,
  explain that `Deploy workers` still calls `AGI.install` because it prepares
  manager/worker runtime environments and reuses an already-ready local manager
  environment instead of forcing a reinstall.
- When the user combines execution, validation, publish, merge, and follow-up
  planning in one message, such as `do it; validate; push if clean; merge it;
  then next move`, treat it as an ordered single turn. Execute each explicit
  step after its safety gate, report the result, and provide the next
  recommendation without requiring a second user round trip unless a real
  blocker needs input.
- When asked for token-saving or workflow-saving tactics and a repo-local
  default is clear, do not end with a broad clarification menu. State the
  assumed target, choose the highest-leverage applicable mechanism, and either
  implement it or name the exact blocker that prevents implementation.
- When validation succeeds, keep the final close-out terse: `Validation passed.`
  Do not expand it into a command-by-command list unless failures, skipped
  checks, release/audit evidence, PR proof, or an explicit user request make the
  details useful.
- When passing URLs, GitHub API paths, or query strings through the shell,
  quote the entire argument or use stdin/structured flags. In zsh, unquoted
  `?`, `&`, `[]`, or other glob-sensitive characters can change or reject the
  command, so an unquoted `gh api repos/.../file?ref=main` style check is a
  preventable command-construction error. When Tokki is available, run ad-hoc
  verification commands through `tokki run -- ...`; Tokki reduces output noise
  but does not replace correct shell quoting.
