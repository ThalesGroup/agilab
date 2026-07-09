---
name: agilab-security-review-patterns
description: Review AGILAB changes for security hardening risks. Use when code, docs, or workflows touch installers, Streamlit exposure, cluster/SSH/share behavior, app execution, notebooks, LLM connectors, secrets, PyPI/GitHub/Hugging Face publishing, dependency policy, or external repositories.
license: BSD-3-Clause (see repo LICENSE)
metadata:
  updated: 2026-07-09
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
- **Pickle/model loading**: require a trusted root plus manifest/hash
  verification before loading pickle-backed models or caches. A production caller
  being safe is not enough when the helper default can be reused unsafely; make
  missing trust context fail closed and add a regression for that default.
- **Cluster shares**: cluster mode must require a usable shared path distinct
  from local-only paths; do not silently degrade to local execution.
- **Share-root path confinement**: app UI fields such as `data_in`,
  `data_out`, inbox directories, service configs, and workflow artifact paths
  are untrusted input even when they come from `app_args_form.py`. Do not let
  absolute paths pass through verbatim, and do not accept `..` traversal after a
  simple join. The shared resolver layer should expand and resolve the share
  root and candidate path, then require `candidate.is_relative_to(share_root)`;
  app-local forms should only add defaults or display helpers unless the app has
  a genuinely local path contract. When hardening a generic resolver, sweep
  sibling forms for settings paths and artifact-root joins that depend on CWD or
  allow an absolute target component to replace the intended export root.
- **SSH host identity**: cluster transport must verify the remote host key.
  Flag `known_hosts=None` (asyncssh), `StrictHostKeyChecking=no`, and
  `UserKnownHostsFile=/dev/null` (scp/ssh) in
  `agi_distributor/runtime/transport_support.py` and deployment helpers.
  Disabled host-key checking plus password auth (`sshpass`/`SSHPASS`,
  `asyncssh password=`) over LAN discovery is a MITM credential/data leak;
  require a real `known_hosts` by default, prefer key auth, and make
  TOFU/`accept-new` an explicit lab-bootstrap mode with documentation that
  fingerprints still need out-of-band verification.
- **Remote command construction**: remote shell commands (`exec_ssh`,
  `conn.run`, scp/ssh argv) must be argument vectors or `shlex.quote`d. Flag
  f-string interpolation of paths, versions, share settings, or a node's probe
  output into a command string sent to another host. Add regressions with shell
  metacharacters for fixed command builders.
- **Connector SSRF**: outbound fetches (`urllib.request.urlopen`, `requests`,
  `httpx`) on connector/config-supplied URLs must enforce an https scheme
  allowlist, block link-local/metadata ranges (`169.254.0.0/16`, `::1`,
  `file://`), and never forward credentials (Bearer tokens, basic auth) to a
  non-allowlisted origin. An operator allow-list of connector IDs is necessary
  but not sufficient; the URL itself still needs validation.
- **MCP and file-read tools**: read-only tools must stay read-only and contain
  caller-supplied paths to a configured root (`Path.resolve()` +
  `is_relative_to(root)`). Flag tools that load an arbitrary `manifest_path`
  with no containment, even when the manifest content is redacted.
- **GUI dynamic HTML**: any value interpolated into `unsafe_allow_html=True`
  markup or `components.html` must be `html.escape`d. Treat run names, file
  paths, connector fields, and log content as untrusted in the rendered page.
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
