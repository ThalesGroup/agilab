# Repo Skills (Codex Mirror)

This repository includes a Codex-consumable mirror of the shared repo skills
under `.codex/skills/`. Each skill is a folder containing a `SKILL.md`
entrypoint and any supporting assets.

These shared repo skills are authored under `.claude/skills/` and mirrored into
`.codex/skills/` for Codex consumption. The `SKILL.md` format is shared, so one
canonical source can serve both agents.

## How Skills Are Used

- Skills are **opt-in**: the agent chooses to load and follow a skill when it is relevant to the current task.
- Skills are meant to be **actionable runbooks** (commands, conventions, pitfalls), not prose.
- Prefer **fail-fast guidance** and **reproducible commands** (use `uv` in this repo).

## Skill Catalog

- `advanced-svg-system-design`: Build reusable SVG visual systems and consistent figure families across docs, slides, and reports.
- `agilab-runbook`: Core repo runbook (uv, Streamlit, run configs, troubleshooting).
- `agilab-installer`: Installer + apps/pages installation conventions and triage.
- `agilab-streamlit-pages`: Streamlit session-state patterns and page authoring rules.
- `agilab-docs`: Documentation workflow (public docs constraints, build steps, consistency).
- `agilab-testing`: Test strategy and quick commands to validate changes.
- `agilab-code-statistics`: Generate tracked-file LOC, language, file-count, and churn summaries without builds.
- `agilab-example-maturity`: Improve packaged examples to external-beta quality with deterministic first-run behavior and newcomer-safe adaptation.
- `agilab-local-llm`: Local LLM usage guidance (Ollama/GPT-OSS) with correctness emphasis.
- `agilab-product-reels`: Build and refine short AGILAB product reels and demo videos.
- `agilab-huggingface-spaces`: Maintain and deploy the official AGILAB Docker Space from the public checkout and sibling Hugging Face bundle.
- `chat-export`: Export chat transcripts or conversation JSON into Markdown, JSON, text, or DOCX artifacts.
- `codex-session-learning`: Turn prior Codex sessions into reusable bug-fix guidance, prompt routing, and validation rules.
- `docs-publish-github-pages`: Review and fix GitHub Pages documentation publish workflows.
- `docx-figure-sync`: Replace embedded DOCX figures without disturbing nearby layout and captions.
- `pipeline-concept-view`: Patterns for app-specific conceptual pipeline views beside generated execution views, plus `lab_stages.toml` naming/IO-flow clarification.
- `notebook-to-agilab-project`: Migrate a small local notebook workflow into an AGILAB project with explicit pipeline and analysis artifacts.
- `plan-before-code`: Enforce a short planning and validation pass before multi-step code changes.
- `report-qa-docx`: Review DOCX reports for missing figures, duplicate sections, stale wording, and caption drift.
- `repo-skill-maintenance`: Maintain the shared `.claude/skills` and `.codex/skills` trees safely, with targeted sync and validation.
- `svg-diagrams`: Author robust repo-native SVG diagrams with in-box text.
- `scientific-svg-figures`: Create publication-grade scientific and technical SVG figures for reports, slides, README/docs, and DOCX/PDF workflows.
- `svg-diagram-tuning`: Refine an existing SVG for readability and export safety without redesigning it from scratch.
- `slides`: Create and edit `.pptx` decks with PptxGenJS and bundled validation/render helpers.
- `slides-docx-align`: Keep slide decks aligned with DOCX report content while preserving each artifact’s role.

## Adding A New Skill

1. Create a new folder: `.claude/skills/<skill-name>/`.
2. Add `.claude/skills/<skill-name>/SKILL.md` with YAML front-matter:
   - `name`, `description`, `license`, optional `metadata`.
3. Keep the skill self-contained; include scripts/examples only when they materially help.
4. Run `python3 tools/sync_agent_skills.py --skills <skill-name>` to mirror it into `.codex/skills/`.

## Keeping Codex and Claude trees in sync

Shared repo skills are now maintained with this contract:

- Canonical shared source: `.claude/skills/`
- Codex mirror: `.codex/skills/`
- Personal Codex-only skills: `~/.codex/skills/`

Use:

- `python3 tools/sync_agent_skills.py --skills scientific-svg-figures` to sync one skill
- `python3 tools/sync_agent_skills.py --all` only after intentionally reconciling older Claude/Codex skill drift
- `python3 tools/codex_skills.py --root .codex/skills validate --strict`
- `python3 tools/codex_skills.py --root .codex/skills generate`

Do not hand-edit both trees for the same shared skill. Edit `.claude/skills/`, sync the specific skill into `.codex/skills/`, then regenerate the Codex index. Keep `~/.codex/skills/` for personal or machine-local skills only.
