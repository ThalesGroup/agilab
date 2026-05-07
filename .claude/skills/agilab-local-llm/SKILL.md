---
name: agilab-local-llm
description: Guidance for using local LLM backends (Ollama/GPT-OSS) inside AGILAB with correctness-first prompts.
license: BSD-3-Clause (see repo LICENSE)
metadata:
  updated: 2026-05-07
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
- Probe the requested backend before claiming validation:
  - GPT-OSS Responses-compatible endpoint, usually
    `http://127.0.0.1:8000/v1/responses`
  - Ollama tags endpoint, usually `http://127.0.0.1:11434/api/tags`
- If the endpoint is unavailable or the selected model is absent, report that
  condition directly. Do not silently replace it with a fixture, cloud API, or
  different local model.

## Standalone Engine Validation

- For local contract tests, a temporary Responses-compatible HTTP server is
  acceptable when the goal is to prove AGILAB's request/response path, schema
  validation, and artifact generation without downloading a model.
- Label that result as a local contract engine, not as real model validation.
  Real model validation requires the actual requested engine to be running and
  selected.
- Validate the generated payload against the app schema and downstream artifacts,
  not only the raw model response. For educational diagnostics, assert fields
  such as `student_score` are persisted in CSV/JSON summaries when the UI or
  README claims them.
- Keep generated examples deterministic where possible by constraining prompts,
  seeds, and output schemas. Reject invalid JSON with an actionable error rather
  than repairing it silently.

## Ollama Notes

- Let users select:
  - model name
  - temperature/top_p/top_k
  - max tokens
  - seed (if supported)
  - “auto-run/auto-fix” loop guardrails (max iterations, stop on failure)
