---
name: agilab-security-review-patterns
description: Review AGILAB changes for security hardening risks. Use when code, docs, or workflows touch installers, Streamlit exposure, cluster/SSH/share behavior, app execution, notebooks, LLM connectors, secrets, PyPI/GitHub/Hugging Face publishing, dependency policy, or external repositories.
license: BSD-3-Clause (see repo LICENSE)
metadata:
  updated: 2026-05-30
---

# AGILAB Security Review Patterns

Use this skill to review AGILAB changes through a security-hardening lens before
merge, release, or public documentation. It is a review workflow, not a pentest
claim. Keep findings tied to concrete files, commands, and user impact.

## Start Here

1. Inspect the diff and classify the touched security surface:
   - UI exposure: Streamlit host, settings page, routes, auth/TLS assumptions.
   - Execution: apps, notebooks, generated code, service tasks, autorun paths.
   - Cluster: SSH, Dask, shared folders, remote accounts, worker deployment.
   - Secrets: `.env`, CLI args, logs, session state, run evidence, artifacts.
   - Supply chain: `pyproject.toml`, installers, PyPI workflows, external repos.
   - LLM connectors: local/remote models, API capability checks, prompt injection.
2. Read the closest guardrail before deciding severity:
   - `SECURITY.md` for supported and unsupported deployment posture.
   - `AGENTS.md` for repo runbook constraints and shared-core approval rules.
   - `tools/security_check.py` for user-facing security diagnostics.
   - `tools/workflow_parity.py` and release workflows for CI/publish coverage.
3. Reproduce or prove the issue with the smallest command that exercises the risk.
4. Prefer fail-closed behavior over silent fallback, especially for cluster,
   public UI bind, secrets, dependency resolution, and publication flows.

## Review Checks

- **Insecure defaults**: public bind, permissive network access, autorun,
  remote execution, or relaxed validation must require explicit opt-in.
- **Trust boundaries**: do not treat external apps, notebooks, generated snippets,
  PyPI packages, Hugging Face artifacts, or cluster workers as trusted just
  because they are convenient.
- **Secrets**: no secrets in tracked files, generated docs, logs, screenshots,
  CLI examples, exception text, or persisted app settings.
- **Serialization and tasks**: reject unsafe legacy formats instead of loading
  them. Prefer JSON schemas and explicit validation.
- **Cluster shares**: cluster mode must require a usable shared path distinct
  from local-only paths; do not silently degrade to local execution.
- **Installer changes**: compare source manifests with copied worker manifests
  before patching app dependencies. Treat manifest rewriting as shared install
  risk.
- **Publishing**: Trusted Publishing, release evidence, provenance, and
  skip-existing behavior must match the workflow contract before claiming
  publication.
- **Documentation**: never present hardening advice, certification, broad OS/cloud
  coverage, or production safety as shipped unless evidence exists.

## Fix Preference

- First remove or narrow the risky behavior.
- If behavior is required, gate it with an explicit setting, clear warning, and
  targeted regression test.
- If the risk crosses shared core, stop for explicit approval and state blast
  radius before editing.
- Do not add silent API/client fallbacks. Detect capabilities up front and fail
  with actionable errors.
- Keep security docs and user-facing diagnostics aligned with the implementation.

## Validation

Run the narrowest relevant checks first:

```bash
uv --preview-features extra-build-dependencies run python tools/impact_validate.py --staged
uv --preview-features extra-build-dependencies run pytest -q -o addopts='' test/test_security_check.py
uv --preview-features extra-build-dependencies run python tools/workflow_parity.py --profile dependency-policy
uv --preview-features extra-build-dependencies run python tools/workflow_parity.py --profile skills
```

For release or publishing risk, add:

```bash
./dev --print-only release
uv --preview-features extra-build-dependencies run python tools/pypi_project_preflight.py
```

Report residual risk explicitly when a check is skipped, environment-specific,
or not reproducible locally.
