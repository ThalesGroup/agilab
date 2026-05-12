# Agent Workflows for AGILAB

This repository is prepared for four agent paths:

- **Claude**: repo skills under [`.claude/skills`](../.claude/skills/README.md)
- **Codex**: repo skills under [`.codex/skills`](../.codex/skills/README.md) and the wrapper in [codex_workflow.sh](codex_workflow.sh)
- **Aider**: repo config in [`.aider.conf.yml`](../.aider.conf.yml) and the wrapper in [aider_workflow.sh](aider_workflow.sh)
- **OpenCode**: project config in [opencode.json](../opencode.json), agents under [`.opencode/agents`](../.opencode/agents), and the wrapper in [opencode_workflow.sh](opencode_workflow.sh)

Use the short repo contract in [AGENT_CONVENTIONS.md](../AGENT_CONVENTIONS.md)
for local coding agents with smaller context windows. Use [AGENTS.md](../AGENTS.md)
for the full AGILAB runbook when the task touches risky surfaces.

## Trace an agent run

Use `agilab agent-run` when a coding-agent action should leave product-style
evidence instead of only a tool-specific log:

```bash
agilab agent-run --agent codex --label "Review current diff" -- codex review
```

The command writes a redacted `agilab.agent_run.v1` manifest plus local
`stdout.txt` and `stderr.txt` artifacts under `~/log/agents/<agent>/<run-id>/`.
Command arguments are redacted by default and represented by an argv hash;
environment override values passed with `--env KEY=VALUE` are also redacted
from the manifest. Pass `--include-command-args` only when the prompt/arguments
are safe to store.

## CLI-first references

- [CLI-first workflow](../docs/CLI_FIRST_WORKFLOW.md)
- [Codex workflow](codex_workflow.md)
- [Aider workflow](aider_workflow.md)
- [OpenCode workflow](opencode_workflow.md)
