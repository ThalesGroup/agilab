---
name: repo-skill-maintenance
description: Maintain repo-managed agent skills across `.claude/skills` and `.codex/skills`, including targeted sync, validation, index regeneration, and drift checks. Use when adding or updating a shared skill, migrating a user-managed skill into the repo, or reconciling Claude/Codex skill copies without overwriting unrelated skills.
license: BSD-3-Clause (see repo LICENSE)
metadata:
  updated: 2026-04-15
---

# Repo Skill Maintenance

Use this skill when working on the shared skill trees in `agilab`.

The goal is to keep one canonical source for shared skills, keep the repo Codex
mirror valid, and avoid the accidental bulk-sync regressions that can overwrite
newer Codex-specific content.

## Canonical contract

- Shared source of truth: `.claude/skills/`
- Repo Codex mirror: `.codex/skills/`
- Personal or tool-managed home skills:
  - `~/.codex/skills/` for local-only skills
  - `~/.codex/skills/.system/` for system-managed skills

Do not hand-edit both repo trees for the same shared skill.

## When to use

- Add a new shared repo skill
- Update an existing shared skill
- Migrate a user-managed skill from `~/.codex/skills` into the repo
- Reconcile drift between the Claude and Codex repo skill trees
- Refresh the generated Codex skill index after skill changes

## Workflow

1. Identify whether the skill is:
   - shared repo skill
   - repo-specific domain skill
   - personal home-only skill
   - system/plugin-managed skill
   If the skill is personal, career-related, or otherwise not an AGILAB workflow asset,
   stop and keep it out of the repo-managed trees.
2. For shared repo skills, edit `.claude/skills/<skill>/` first.
3. Keep the skill self-contained:
   - `SKILL.md`
   - optional `agents/openai.yaml`
   - optional `references/`, `scripts/`, `assets/`
4. Sync only the intended skill into `.codex/skills/`:

```bash
python3 tools/sync_agent_skills.py --skills <skill-name>
```

5. Validate and regenerate the Codex index:

```bash
python3 tools/codex_skills.py --root .codex/skills validate --strict
python3 tools/codex_skills.py --root .codex/skills generate
```

6. If a user-managed home skill is being migrated, replace the home copy with a
   symlink back to the repo Codex copy instead of keeping two real directories.
7. Update repo-facing skill docs when the catalog changes:
   - `.claude/skills/README.md`
   - `.codex/skills/README.md`
   - root `README.md` if the repo-level agent workflow description changed

## Guardrails

- Do not run `python3 tools/sync_agent_skills.py --all` unless you have already
  reconciled any older Claude/Codex drift on purpose.
- Do not migrate `~/.codex/skills/.system` into the repo.
- Do not leave a copied third-party skill with missing repo-required frontmatter
  such as `license`.
- Do not keep duplicate real directories in both the repo and `~/.codex/skills`
  for the same shared skill.
- If a skill is domain-specific to another repo, keep it there instead of forcing
  it into `agilab`.
- Do not add private CV, recruiting, or personal productivity skills to the public
  AGILAB repo-managed skill trees. Put them in `~/.codex/skills/` or the relevant
  private repo instead.

## Typical fixes

- Add missing `license` frontmatter when importing an upstream skill
- Normalize a skill description so it says `the agent` instead of naming one agent
- Restore a newer repo Codex copy if an over-broad sync overwrote it
- Rebuild `.codex/skills/.generated/skills_index.*` after the skill set changes
