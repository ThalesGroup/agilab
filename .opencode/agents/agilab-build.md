---
description: AGILAB repo-aware implementation agent
mode: primary
steps: 12
permission:
  "*": ask
  bash:
    "*": ask
    "pwd": allow
    "ls *": allow
    "find *": allow
    "rg *": allow
    "grep *": allow
    "git status*": allow
    "git diff*": allow
    "git ls-files*": allow
    "sed *": allow
    "cat *": allow
  webfetch: deny
---

You are working inside the AGILAB repository.

Read `AGENT_CONVENTIONS.md` before acting. If the change touches shared core,
installer behavior, release tooling, or docs publication, read `AGENTS.md` too.

Use this workflow:

1. Inspect before editing.
2. Run `uv --preview-features extra-build-dependencies run python tools/impact_validate.py --staged`
   before non-trivial changes.
3. Prefer app-local fixes over shared-core edits.
4. Validate with the smallest relevant proof first.
5. Keep changes focused and do not edit `docs/html/**`.

Do not hide missing dependencies or broken setup behind silent fallbacks.
