# Agent Workflows for AGILAB

This repository is prepared for four agent paths:

- **Claude**: repo skills under [`.claude/skills`](../.claude/skills/README.md)
- **Codex**: repo skills under [`.codex/skills`](../.codex/skills/README.md) and the wrapper in [codex_workflow.sh](codex_workflow.sh)
- **Aider**: repo config in [`.aider.conf.yml`](../.aider.conf.yml) and the wrapper in [aider_workflow.sh](aider_workflow.sh)
- **OpenCode**: project config in [opencode.json](../opencode.json), agents under [`.opencode/agents`](../.opencode/agents), and the wrapper in [opencode_workflow.sh](opencode_workflow.sh)

Use the short repo contract in [AGENT_CONVENTIONS.md](../AGENT_CONVENTIONS.md)
for local coding agents with smaller context windows. Use [AGENTS.md](../AGENTS.md)
for the full AGILAB runbook when the task touches risky surfaces.

## CLI-first references

- [CLI-first workflow](../docs/CLI_FIRST_WORKFLOW.md)
- [Codex workflow](codex_workflow.md)
- [Aider workflow](aider_workflow.md)
- [OpenCode workflow](opencode_workflow.md)
