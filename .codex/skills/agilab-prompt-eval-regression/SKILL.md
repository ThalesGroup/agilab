---
name: agilab-prompt-eval-regression
description: Design and maintain regression evaluations for AGILAB prompts, local/remote LLM flows, notebook import classification, generated-code routing, agent-skill behavior, and prompt-driven repair or analysis features. Use when a change touches prompt templates, model defaults, local LLM readiness, notebook-to-project import, code generation, or AI-assisted UX.
license: BSD-3-Clause (see repo LICENSE)
metadata:
  updated: 2026-05-30
---

# AGILAB Prompt Eval Regression

Use this skill when AGILAB behavior depends on a prompt, model response, or
LLM-assisted classification. The goal is not to make tests depend on live model
luck. The goal is to turn prompt-sensitive workflows into deterministic
regression surfaces with clear fixtures, expected decisions, and replayable
evidence.

## Scope

Trigger this skill for changes touching:

- notebook import cell classification, manager/worker tagging, stage naming, or
  template selection;
- generated code snippets, prompt-to-code repair, local LLM autofix, or
  pipeline generation;
- `pre_prompt.json`, prompt templates, model defaults, provider capability
  checks, or OpenAI/Ollama/GPT-OSS routing;
- agent skills whose behavior depends on prompt wording;
- documentation that claims an LLM-assisted workflow is reliable, deterministic,
  or safe.

## Evaluation Pattern

Prefer a three-layer eval:

1. **Static prompt contract**: prompt inputs are bounded, redacted, and include
   enough task context without leaking private paths or secrets.
2. **Decision fixture**: deterministic fixtures assert classification/routing
   decisions without calling a live model.
3. **Optional live smoke**: model-backed checks are opt-in, tagged, bounded by
   timeout, and record model/provider/version in evidence.

Do not add live LLM calls to default unit tests. If a live model is useful, gate
it behind an explicit environment variable or workflow profile and document the
expected cost, timeout, and failure mode.

## Test Design

- Use small notebook, prompt, and traceback fixtures that exercise the failure
  mode without external services.
- Assert on structured decisions, not exact free-form prose.
- Include negative cases: ambiguous cell, unsafe generated code, missing model,
  unreachable local endpoint, unsupported provider, and prompt too large.
- Freeze schema fields for prompt-eval evidence: `schema`, `producer`,
  `fixture`, `decision`, `model` when used, `status`, and remediation.
- Keep expected outputs human-readable enough for a reviewer to spot drift.
- Redact secrets before storing prompt, response, or traceback evidence.

## AGILAB-Specific Checks

- Notebook import must fail closed when manager/worker role is ambiguous and no
  metadata or user decision exists.
- Generated code should be routed through existing review/sandbox boundaries,
  not autorun silently.
- Local LLM readiness should report actionable setup steps instead of falling
  back to a different provider.
- Provider capability mismatches should be detected up front; do not introduce
  automatic API/client fallback rewrites.
- Prompt changes should update docs only when deterministic fixtures or live
  evidence support the new behavior.

## Validation Commands

Start with targeted tests for the touched surface:

```bash
uv --preview-features extra-build-dependencies run pytest -q -o addopts='' test/test_pipeline_ai_support.py
uv --preview-features extra-build-dependencies run pytest -q -o addopts='' test/test_notebook_import_preflight.py test/test_notebook_pipeline_import_report.py
uv --preview-features extra-build-dependencies run pytest -q -o addopts='' test/test_agent_config_and_capabilities.py
```

For skill or prompt-runbook changes:

```bash
uv --preview-features extra-build-dependencies run python tools/workflow_parity.py --profile skills
```

For optional live local-model validation, first print the exact command and keep
the result out of the default regression path:

```bash
uv --preview-features extra-build-dependencies run python tools/launch_gpt_oss.py --print-only
```

Close with which layer was validated: static fixture only, deterministic
decision fixture, or opt-in live model smoke.
