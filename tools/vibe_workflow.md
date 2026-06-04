# Mistral Vibe Workflow for AGILAB

## Purpose

Use this wrapper when you want Mistral Vibe Code to operate from the AGILAB
repository root with the same logging conventions as the other local coding
agent wrappers.

The wrapper does not rewrite Vibe model settings. Configure hosted or local
providers through Vibe's own `~/.vibe/config.toml` and use this repo entry point
only to standardize launch location and non-interactive logs.

## Standard commands

```bash
# Start an interactive Vibe session in the repo root
./tools/vibe_workflow.sh chat

# One-off implementation task
./tools/vibe_workflow.sh exec "Refactor only ... keeping behavior unchanged"

# Review-focused one-off run
./tools/vibe_workflow.sh review

# Run Vibe setup from the repo root
./tools/vibe_workflow.sh setup
```

## Defaults enforced by the wrapper

- runs from the repository root
- delegates provider and model selection to Vibe
- logs non-interactive runs to `log/vibe/<mode>-YYYYmmdd-HHMMSS.log`
- uses Vibe's documented `vibe` and `vibe "<prompt>"` command shapes only

## Offline Devstral

For local/offline use, serve Devstral behind an OpenAI-compatible endpoint and
select it in Vibe. A minimal Vibe model alias looks like:

```toml
[[providers]]
name = "local"
api_base = "http://localhost:8080/v1"
api_style = "openai"
backend = "generic"

[[models]]
name = "mistralai/Devstral-Small-2-24B-Instruct-2512"
provider = "local"
alias = "devstral-local"

active_model = "devstral-local"
```

AGILAB's installer can also pull the Ollama `devstral:latest` family for the
WORKFLOW local assistant:

```bash
./install.sh --install-local-models devstral
```

## Notes

- Install Vibe with the upstream `mistral-vibe` package before using the wrapper.
- Set `AGILAB_VIBE_COMMAND=/path/to/vibe` when the executable is not on `PATH`.
- Disable external tools, connectors, telemetry, or auto-update in Vibe's config
  when a task must stay fully offline.
