# OpenCode Workflow for AGILAB

## Purpose

Use this wrapper when you want a local terminal coding agent with AGILAB-aware
defaults and project-scoped OpenCode agents.

The repo ships:

- [`opencode.json`](../opencode.json) for project config
- [`.opencode/agents/agilab-build.md`](../.opencode/agents/agilab-build.md)
- [`.opencode/agents/agilab-review.md`](../.opencode/agents/agilab-review.md)
- [`AGENT_CONVENTIONS.md`](../AGENT_CONVENTIONS.md) for the short repo contract

## Standard commands

```bash
# Start an interactive OpenCode session in the repo root
./tools/opencode_workflow.sh chat

# One-off implementation task
./tools/opencode_workflow.sh exec "Refactor only ... keeping behavior unchanged"

# Review-focused one-off run
./tools/opencode_workflow.sh review
```

## Defaults enforced by the wrapper

- runs from the repository root
- defaults to `ollama/qwen2.5-coder:latest`
- defaults to the `agilab-build` primary agent
- uses the `agilab-review` agent for review mode
- logs non-interactive runs to `log/opencode/<mode>-YYYYmmdd-HHMMSS.log`
- keeps sharing disabled via [`opencode.json`](../opencode.json)

## Override model or agent

```bash
AGILAB_OPENCODE_MODEL=ollama/deepseek-coder:latest ./tools/opencode_workflow.sh chat
AGILAB_OPENCODE_MODEL=ollama/qwen3-coder:30b-a3b-q4_K_M ./tools/opencode_workflow.sh chat
AGILAB_OPENCODE_MODEL=ollama/ministral-3:14b-instruct-2512-q4_K_M ./tools/opencode_workflow.sh chat
AGILAB_OPENCODE_MODEL=ollama/phi4-mini:3.8b-q4_K_M ./tools/opencode_workflow.sh chat
AGILAB_OPENCODE_AGENT=agilab-build ./tools/opencode_workflow.sh exec "Add a regression test"
```

## Notes

- This setup assumes a running Ollama server.
- The project agents keep edits permissioned and web fetch disabled by default.
- For risky work, read [`AGENTS.md`](../AGENTS.md) in addition to the shorter
  conventions file.
