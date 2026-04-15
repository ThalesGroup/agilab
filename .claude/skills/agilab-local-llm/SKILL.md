---
name: agilab-local-llm
description: Guidance for using local LLM backends (Ollama/GPT-OSS) inside AGILAB with correctness-first prompts.
license: BSD-3-Clause (see repo LICENSE)
metadata:
  updated: 2026-01-09
---

# Local LLM Skill (AGILAB)

Use this skill when working on local/offline engines or prompts.

## Correctness-First Defaults

- Prefer deterministic settings for code edits (lower temperature, explicit constraints).
- Require the model to return:
  - file list to edit
  - exact patch intent
  - tests/commands to validate

## No Silent Fallbacks

- Detect missing local endpoints/models up-front and surface an actionable error.
- Do not auto-switch APIs or rewrite parameters silently.

## Ollama Notes

- Let users select:
  - model name
  - temperature/top_p/top_k
  - max tokens
  - seed (if supported)
  - “auto-run/auto-fix” loop guardrails (max iterations, stop on failure)

