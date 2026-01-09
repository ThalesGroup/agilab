# Repo Skills

This repository includes a small set of **Codex Agent Skills** under `.codex/skills/`.
They are inspired by the structure used in `github.com/anthropics/skills` (each skill
is a folder containing a `SKILL.md` entrypoint and any supporting assets).

## How Skills Are Used

- Skills are **opt-in**: the agent can choose to load and follow a skill when it is relevant.
- Skills are meant to be **actionable runbooks** (commands, conventions, pitfalls), not prose.
- Prefer **fail-fast guidance** and **reproducible commands** (use `uv` in this repo).

## Skill Catalog

- `agilab-runbook`: Core repo runbook (uv, Streamlit, run configs, troubleshooting).
- `agilab-installer`: Installer + apps/pages installation conventions and triage.
- `agilab-streamlit-pages`: Streamlit session-state patterns and page authoring rules.
- `agilab-docs`: Documentation workflow (public docs constraints, build steps, consistency).
- `agilab-testing`: Test strategy and quick commands to validate changes.
- `agilab-local-llm`: Local LLM usage guidance (Ollama/GPT-OSS) with correctness emphasis.
- `template`: Minimal skeleton for adding a new skill.

## Adding A New Skill

1. Create a new folder: `.codex/skills/<skill-name>/`.
2. Add `.codex/skills/<skill-name>/SKILL.md` with YAML front-matter:
   - `name`, `description`, `license`, optional `metadata`.
3. Keep the skill self-contained; include scripts/examples only when they materially help.

