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
- When a product or code fix was designed or implemented with model assistance,
  request a review from a stronger model before closing, pushing, or merging
  when that is available. If no stronger model is available, say so explicitly
  and still run the normal local review and validation path.
- When a source Streamlit UI is running, do not run plain repo-level `uv run`
  validation commands against the same `.venv`. Use `./dev`, which isolates uv
  subprocesses in `.venv-dev`, or pass an explicit ignored
  `UV_PROJECT_ENVIRONMENT` so validation cannot strip Streamlit static assets
  from the live UI environment.
- When a shared Streamlit helper needs to remember that a page has been
  configured, store that marker in `st.session_state`, not on the imported
  `streamlit` module. Module attributes are process-global and can leak layout
  or title decisions across browser sessions.
- When passing URLs, GitHub API paths, or query strings through the shell,
  quote the entire argument or use stdin/structured flags. In zsh, unquoted
  `?`, `&`, `[]`, or other glob-sensitive characters can change or reject the
  command, so an unquoted `gh api repos/.../file?ref=main` style check is a
  preventable command-construction error. When Tokki is available, run ad-hoc
  verification commands through `tokki run -- ...`; Tokki reduces output noise
  but does not replace correct shell quoting.
- When the user asks to install or test source apps and AGILAB is already
  installed, use the model-free `src/agilab/install_apps.sh` or
  `src\agilab\install_apps.ps1` script with explicit `APPS_REPOSITORY` and
  `BUILTIN_APPS`. Do not replace that with root reinstall flows, manual
  `~/.agilab/.env` patching, or hand-written pytest loops.
- When the user asks to update AGILAB repos, do not silently narrow `repo` to
  only the current checkout. Treat the default maintenance target set as
  `agilab` plus sibling `thales_agilab` when present, print both in the command
  plan, and explicitly report any dirty, missing, or intentionally skipped
  checkout.
- Before acting on a stale sibling worktree reported by `./dev audit`, verify
  it still exists in `git worktree list --porcelain`. If it is missing, stop
  and ask whether to recreate that branch or continue from the current checkout.
- On agent-prefixed branches such as `codex/*`, `codex-*`, `claude/*`,
  `aider/*`, `opencode/*`, or `agent/*`, never commit with a human Git
  identity. Run `python3 tools/agent_commit_provenance_guard.py --check-config`
  before committing; configure an explicit agent identity when needed.
- When `gh pr merge --delete-branch` fails because another local worktree owns
  `main`, check the remote PR state before retrying. Prefer a remote-only
  retry from outside the checkout, for example `gh pr merge <n> --repo
  ThalesGroup/agilab --merge --delete-branch` from `/tmp`; if the PR already
  merged, delete the remote feature branch separately and report the local
  cleanup failure as local-only.
- When auditing commit provenance, do not infer the worker from a signature or
  configured author name alone. Inventory author, committer, signature identity,
  GitHub actor, PR metadata, and timestamps before attributing work.
- When a built-in app README, quality plan, or docs page names output
  artifacts, verify those exact names against worker code and documented
  outputs before merging. Fix the docs or generation path if the artifact is
  not actually emitted.
- When a Streamlit configure form has an expensive preview that reads upstream
  artifacts, make refresh an explicit one-shot action and add a regression that
  proves ordinary widget changes do not trigger that preview. Do not use a
  persistent checkbox for expensive previews unless the user explicitly asks for
  live recomputation.
- Treat built-in app maturity as one gate: first-run UX, deterministic sample
  data, README artifact truth, app-local tests, installer/catalog contract, and
  clear example value must align before calling the app example-grade.
- For docs/SVG alignment, compare editable source, mirrored/public references,
  captions/alt text, and the rendered page together. Do not call docs aligned
  from raw SVG validity or source text inspection alone.
