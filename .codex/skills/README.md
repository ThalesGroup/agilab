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
- `pipeline-concept-view`: Patterns for app-specific conceptual pipeline views beside generated execution views, plus `lab_steps.toml` naming/IO-flow clarification.
- `notebook-to-agilab-project`: Migrate a small local notebook workflow into an AGILAB project with explicit pipeline and analysis artifacts.
- `scientific-svg-figures`: Publication-grade scientific and technical SVG figure workflow for reports, slides, docs, and DOCX/PDF export.

## Adding A New Skill

Shared AGILAB skills should be created under `.claude/skills/<skill-name>/` first, then synced into `.codex/skills/`:

1. Create `.claude/skills/<skill-name>/`.
2. Add the skill content there.
3. Run `python3 tools/sync_agent_skills.py --skills <skill-name>`.
4. Regenerate the Codex index with `tools/codex_skills.py`.

Use `.codex/skills/` for the mirrored repo-visible Codex copy, not as the canonical edit location for shared skills.
Use `python3 tools/sync_agent_skills.py --all` only after deliberately reconciling any older drift between the Claude and Codex repo copies. Keep `~/.codex/skills/` for personal or machine-local skills.

## Managing the Skill Index

Use `tools/codex_skills.py` to validate and regenerate generated indexes:

- `python3 tools/codex_skills.py --root .codex/skills validate --strict`
- `python3 tools/codex_skills.py --root .codex/skills generate`

Generated files are written to:

- `.codex/skills/.generated/skills_index.json`
- `.codex/skills/.generated/skills_index.md`
