# Codex CLI Overview

The Codex CLI can be used alongside AGILab to keep agent-driven work reproducible (same commands, same scripts, same review surface).

## Background reading

- Codex CLI features: <https://developers.openai.com/codex/cli/features>
- Prompting guide: <https://cookbook.openai.com/examples/gpt-5-codex_prompting_guide>
- Spec-driven development (Spec Kit): <https://github.com/github/spec-kit>

## Local usage stats (optional)

`codex/export_codex_shell_stats.py` can export local Codex shell history + aggregated stats from `~/.codex/sessions/`.
The generated TSV/Markdown outputs are intentionally gitignored (they may contain machine-specific paths).

## Related runbook

See `AGENTS.md` for the repo’s launch/validation workflow (run configs, wrapper scripts, and common troubleshooting).
