# Repo Skills (Claude)

This repository includes a set of **Claude Code Agent Skills** under `.claude/skills/`.
Each skill is a folder containing a `SKILL.md` entrypoint and any supporting assets.

These skills are Claude-equivalent mirrors of the `.codex/skills/` set used by Codex.
The `SKILL.md` format is shared (YAML front-matter + markdown body), so updates to
either tree can be ported to the other with minimal changes.

## How Skills Are Used

- Skills are **opt-in**: the agent chooses to load and follow a skill when it is relevant to the current task.
- Skills are meant to be **actionable runbooks** (commands, conventions, pitfalls), not prose.
- Prefer **fail-fast guidance** and **reproducible commands** (use `uv` in this repo).

## Skill Catalog

- `agilab-runbook`: Core repo runbook (uv, Streamlit, run configs, troubleshooting).
- `agilab-installer`: Installer + apps/pages installation conventions and triage.
- `agilab-streamlit-pages`: Streamlit session-state patterns and page authoring rules.
- `agilab-docs`: Documentation workflow (public docs constraints, build steps, consistency).
- `agilab-testing`: Test strategy and quick commands to validate changes.
- `agilab-local-llm`: Local LLM usage guidance (Ollama/GPT-OSS) with correctness emphasis.
- `agilab-product-reels`: Build and refine short AGILAB product reels and demo videos.
- `pipeline-concept-view`: Patterns for app-specific conceptual pipeline views beside generated execution views, plus `lab_steps.toml` naming/IO-flow clarification.
- `notebook-to-agilab-project`: Migrate a small local notebook workflow into an AGILAB project with explicit pipeline and analysis artifacts.
- `svg-diagrams`: Author robust repo-native SVG diagrams with in-box text.

## Adding A New Skill

1. Create a new folder: `.claude/skills/<skill-name>/`.
2. Add `.claude/skills/<skill-name>/SKILL.md` with YAML front-matter:
   - `name`, `description`, `license`, optional `metadata`.
3. Keep the skill self-contained; include scripts/examples only when they materially help.
4. Mirror the new skill to `.codex/skills/<skill-name>/` if you want Codex parity.

## Keeping Codex and Claude trees in sync

Both trees carry the same skill content. When editing one, update the other if the
change is repo policy (not agent-specific). Agent-specific sections (for example,
framework-specific behavior in `agilab-runbook/SKILL.md`) may legitimately diverge.
