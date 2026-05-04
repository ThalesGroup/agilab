# Aider Workflow for AGILAB

## Purpose

Use this wrapper when you want AGILAB-aware repo editing with Aider and local
models exposed through Ollama.

The repo ships:

- [`.aider.conf.yml`](../.aider.conf.yml) for repo-local defaults
- [`AGENT_CONVENTIONS.md`](../AGENT_CONVENTIONS.md) for a short agent contract
- [`AGENTS.md`](../AGENTS.md) for the full runbook when the task is risky

## Standard commands

```bash
# Start an interactive session in the repo root
./tools/aider_workflow.sh chat

# One-off implementation task
./tools/aider_workflow.sh exec "Refactor only ... keeping behavior unchanged"

# Review-focused one-off run
./tools/aider_workflow.sh review src/agilab/pipeline_ai.py test/test_pipeline_ai.py
```

## Defaults enforced by the wrapper

- runs from the repository root
- loads [`.aider.conf.yml`](../.aider.conf.yml)
- defaults to `qwen-local`, which maps to `ollama_chat/qwen2.5-coder:latest`
- logs non-interactive runs to `log/aider/<mode>-YYYYmmdd-HHMMSS.log`
- keeps Aider auto-commits disabled

## Supported local model aliases

- `qwen-local`
- `deepseek-local`
- `gpt-oss-local`
- `qwen3-local`
- `qwen3-coder-local`
- `ministral-local`
- `phi4-mini-local`

Override the default model with:

```bash
AGILAB_AIDER_MODEL=deepseek-local ./tools/aider_workflow.sh chat
AGILAB_AIDER_MODEL=qwen3-coder-local ./tools/aider_workflow.sh chat
```

## Notes

- This setup assumes a running Ollama server.
- Aider works best with stronger edit-capable local models; weak models may
  return text that does not apply cleanly as file edits.
- For bigger tasks, still start with `tools/impact_validate.py` and validate
  with narrow local tests before broader workflows.
