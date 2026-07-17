---
name: repo-skill-maintenance
description: Maintain repo-managed agent skills across `.claude/skills` and `.codex/skills`, including targeted sync, validation, index regeneration, drift checks, and Tokki skill visibility. Use when adding or updating a shared skill, migrating a user-managed skill into the repo, or reconciling agent skill copies without overwriting unrelated skills.
license: BSD-3-Clause (see repo LICENSE)
metadata:
  updated: 2026-07-16
---

# Repo Skill Maintenance

Use this skill when working on the shared skill trees in `agilab`.

The goal is to keep one canonical source for shared skills, keep the repo Codex
mirror valid, and avoid the accidental bulk-sync regressions that can overwrite
newer Codex-specific content.

## Canonical contract

- Shared source of truth: `.claude/skills/`
- Repo Codex mirror: `.codex/skills/`
- Tokki skill source: the canonical `.claude/skills/` tree, read directly with
  `tokki skills list --skills-dir .claude/skills --json`. Tokki has no repo
  mirror; do not create `.tokki/skills` or `.agilab/skills` copies.
- Personal or tool-managed home skills:
  - `~/.codex/skills/` for local-only skills
  - `~/.codex/skills/.system/` for system-managed skills

Do not hand-edit both repo trees for the same shared skill.

## Placement policy

Repo-managed skills in this public checkout must be:

- AGILAB-specific
- cross-repo reusable for AGILAB work
- or direct support for this repository's workflow, validation, docs, release,
  packaging, UI, or example maintenance

Keep these out of the public repo-managed trees:

- personal productivity skills
- private CV, recruiting, or career skills
- non-AGILAB domain skills
- skills whose examples depend on private customer/program context
- machine-local skills with hard-coded usernames, absolute private paths, or
  personal service accounts

Use `~/.codex/skills/` for personal local skills and the relevant private repo
for private-domain skills.

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
   If the skill belongs in the public repo but needs local examples, use placeholders
   such as `<repo>`, `<apps-repo>`, `<space-owner>`, `$HOME`, or relative paths instead
   of maintainer-specific absolute paths.
2. For shared repo skills, edit `.claude/skills/<skill>/` first.
3. Keep the skill self-contained:
   - `SKILL.md`
   - optional `agents/openai.yaml`
   - optional `references/`, `scripts/`, `assets/`
4. Sync only the intended skill or skills into `.codex/skills/`. The sync
   validates the canonical tree first, then regenerates the Codex skill index,
   badges, catalog, capability manifest, and agenticweb surfaces, and finishes
   by verifying Tokki skill visibility:

```bash
python3 tools/sync_agent_skills.py --skills <skill-name> [<skill-name> ...]
```

5. Confirm the Codex index plus public agent discovery surfaces are valid and
   current. The sync in step 4 already regenerated them; rerun these
   explicitly after manual reconciliation or when in doubt:

```bash
python3 tools/codex_skills.py --root .codex/skills validate --strict
python3 tools/codex_skills.py --root .codex/skills generate
python3 tools/agent_skill_catalog.py --apply
python3 tools/agilab_capabilities_manifest.py --apply
python3 tools/agenticweb_manifest.py --apply
```

6. Check the generated surfaces before committing:

```bash
python3 tools/agent_skill_catalog.py --check
python3 tools/agilab_capabilities_manifest.py --check
python3 tools/agenticweb_manifest.py --check
python3 tools/agent_instruction_contract.py --check
```

7. Verify tree drift and Tokki skill visibility with the read-only check. It
   compares the canonical and mirror trees file by file, then confirms the
   Tokki agent enumerates every canonical skill (skipped with a notice when
   the `tokki` CLI is not installed). The command is registered as a Tokki
   model-free validation route in `.tokki/model-free-commands`:

```bash
python3 tools/sync_agent_skills.py --check
```

8. If a user-managed home skill is being migrated, replace the home copy with a
   symlink back to the repo Codex copy instead of keeping two real directories.
9. Update repo-facing skill docs when the catalog changes:
   - `.claude/skills/README.md`
   - `.codex/skills/README.md`
   - root `README.md` if the repo-level agent workflow description changed

## Guardrails

- Do not run `python3 tools/sync_agent_skills.py --all` unless you have already
  reconciled any older Claude/Codex drift on purpose.
- When multiple skills are being edited in one pipeline, sync all touched
  skills in one targeted command so the Codex index and discovery surfaces
  regenerate once, instead of running one sync per skill.
- Do not treat `.codex/skills/.generated/*` as the only generated output of a
  skill change. Skill text can also affect `llms-full.txt`,
  `agilab-capabilities.json`, and `agenticweb.md`; regenerate and check the
  whole agent discovery surface before push.
- Do not create a third repo skills tree for Tokki. Tokki consumes the
  canonical `.claude/skills/` tree; in this repo, `tokki skills capture` and
  `tokki skills promote` must always pass an explicit `--skills-dir` because
  the Claude and Codex trees are distinct real directories.
- Keep the Tokki model-free route for this tool limited to
  `python3 tools/sync_agent_skills.py --check`; the sync itself mutates the
  mirror and must stay a reviewed, modeled action.
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
