# Security Policy

We want AGILAB to be safe for every team that experiments with it. This page explains how to
report issues and what you can expect from us when you do.

## Supported Versions

| Version / Branch | Supported |
|------------------|-----------|
| `main` (development head) | ✅ |
| Tagged releases older than 6 months | ⚠️ Fixes are best-effort |
| 1.0 and earlier | ❌ |

Security fixes are released on a rolling basis. If a vulnerability affects an unsupported version,
please upgrade to the latest release before requesting a patch.

## Reporting a Vulnerability

- Do **not** open a public GitHub issue for suspected vulnerabilities.
- Preferred channel: use GitHub Private Vulnerability Reporting when it is available for the
  repository.
- GitHub Issues, Discussions, pull requests, and README issue links are only for non-sensitive
  product bugs, support questions, and post-fix follow-up. They are not vulnerability intake
  channels.
- If private reporting is not available to you, contact your usual Thales representative or submit
  a request via <https://cpl.thalesgroup.com/fr/contact-us> and ask for a private AGILAB security
  intake.
- Do not include exploit code, secrets, detailed proof-of-concept material, or sensitive logs in a
  public issue, pull request, discussion, or comment.
- Include only non-sensitive routing details in the first contact:
  - A short summary and affected component names.
  - Which environments are affected (development install, packaged release, shared deployment, etc.).
  - A preferred way to reach you for follow-up questions.
- Share reproduction steps, proof-of-concept material, secrets, exploit details, or sensitive logs
  only after a private channel has been confirmed.
- Public GitHub issues are only for non-sensitive post-fix advisories or follow-up after a private
  report has been triaged. They are not an initial vulnerability disclosure channel.

We will acknowledge receipt within **two business days**. If you do not hear back, please resend your
message or reach out through your usual Thales representative.

## Coordinated Disclosure

1. We confirm the report and work with you to understand the impact.
2. A remediation plan is drafted. You will receive an estimated timeline (typically under 30 days
   for high-severity issues).
3. Confirmed issues are handled through a private GitHub Security Advisory when appropriate.
4. Fixes are released and security notes are published. We credit the reporter unless you request
   otherwise.

We appreciate coordinated disclosure and will keep you updated throughout the process.

## Security Updates

- Critical patches are released as soon as they are ready.
- Other fixes may be bundled into the next scheduled monthly update.
- Release notes highlight CVE identifiers or internal tracking IDs where applicable.

## Adoption Profile

AGILAB is designed as a trusted-operator experimentation workbench. It can install apps,
generate and execute Python snippets, launch worker environments, orchestrate local or
distributed runs, and optionally start UI, tracking, or local-model tooling. Treat every app,
notebook, generated snippet, and external apps repository as executable code until it has been
reviewed.

Recommended use without additional platform hardening:

- Local research sandbox, notebook-to-app migration, reproducible experiment replay, and internal
  demonstrations with non-sensitive data.
- Single-operator or controlled lab environments where the operator owns the apps, dependencies,
  datasets, secrets, and worker machines.

Conditional use only after hardening:

- Shared team deployments, internal clusters, local/remote LLM use, or external apps repositories.
- Minimum controls: per-user isolation, a dedicated OS user or equivalent workspace boundary,
  restricted outbound network access where appropriate, bounded CPU/RAM, reviewed app code,
  scanned dependencies, controlled logs, and secrets supplied outside repository or command-line
  arguments. Reserve container/VM boundaries for untrusted apps, shared sensitive deployments, or
  advanced raw-Python execution paths that need stronger isolation.

Not recommended as-is:

- public exposure without authentication, TLS, and sandboxing.
- Multi-tenant service use, writable shared cluster directories, untrusted apps, sensitive or
  regulated data, or production ML serving/governance/monitoring workloads.
- Environments where AGILAB must be the only production MLOps control plane. Use production
  serving, feature-store, monitoring, policy, and governance systems alongside AGILAB when those
  controls are required.

## Hardening Checklist

While AGILAB is open source, production-grade cluster deployments should be designed with your
organization's security requirements in mind. At minimum:

- Run AGILAB in a confined environment for shared or unknown workloads: container, VM, disposable
  workspace, dedicated UID, no default access to personal secrets, CPU/RAM quotas, and restricted
  network egress.
- Run behind HTTPS and limit inbound network access to trusted operators.
- Store API keys, model weights, and datasets outside of the repository, using a dedicated secrets
  manager where possible.
- Rotate credentials regularly and prefer short-lived access tokens to static passwords.
- Monitor and log execution environments; disable unused Streamlit pages or demo apps in shared
  environments.
- Treat AGILAB command execution as a trusted-operator boundary. Shared deployments should restrict
  project roots, environment variables, writable paths, and network access according to the team
  threat model.
- Run ``agilab security-check --profile shared --json`` before shared adoption reviews. The default
  ``local`` profile stays advisory for single-operator experiments; ``shared``, ``cluster``, and
  ``public-ui`` promote deployment-boundary issues to failures so ``--strict`` can be used as a real
  gate. The report covers floating or unallowlisted ``APPS_REPOSITORY`` checkouts, plaintext
  ``~/.agilab/.env`` secrets, exposed UI binds, cluster-share isolation, generated-code execution,
  optional local-model profiles, and missing SBOM / ``pip-audit`` evidence.
- Keep the Streamlit UI on loopback by default. AGILAB refuses ``0.0.0.0`` or ``::`` public binds
  unless ``AGILAB_PUBLIC_BIND_OK=1`` is paired with an explicit auth/TLS indicator such as
  ``AGILAB_TLS_TERMINATED=1``.
- Treat shell execution and install profiles as privileged operator surfaces. The installer can
  prepare development, local-model, and cluster dependencies; use an isolated lab machine or
  container for untrusted apps, and review dry-run/log output before enabling optional system-level
  profiles.
- Treat ``APPS_REPOSITORY`` as an executable-code trust boundary. For shared use, only allow
  repositories from an explicit allowlist via ``AGILAB_APPS_REPOSITORY_ALLOWLIST`` or
  ``AGILAB_APPS_REPOSITORY_ALLOWLIST_FILE``, pin them to a reviewed commit SHA or immutable tag,
  reject floating branches, and scan the repository before installing or linking apps/pages.
- Treat the service queue as scheduler-owned state. Workers process ``*.task.json`` payloads with
  the ``agi.service.task.v1`` schema, and legacy ``*.task.pkl`` files are quarantined without
  deserialization. The queue directory must be writable only by the trusted scheduler/operator.
- Treat generated code as untrusted until reviewed. WORKFLOW defaults dataframe generation to a
  safe-action contract: the model returns versioned JSON, AGILAB validates it against the dataframe
  schema, and AGILAB converts the approved contract into deterministic pandas code. Raw Python
  generation remains an advanced/manual path. WORKFLOW auto-fix refuses to execute model-generated
  Python for validation unless ``AGILAB_GENERATED_CODE_SANDBOX`` is set by the operator. Prefer
  ``container`` or ``vm`` for shared use; ``process`` mode is only acceptable when the operator also
  enforces resource/filesystem/network/secret limits and sets ``AGILAB_GENERATED_CODE_PROCESS_LIMITS=1``.
- Treat local ``~/.agilab/.env`` secrets as developer convenience only. Prefer OS keyrings,
  enterprise vaults, or short-lived environment variables for shared, sensitive, or production-like
  deployments. The Streamlit environment editor must redact secret-like keys in previews and never
  pre-fill existing ``KEY``, ``TOKEN``, ``SECRET``, ``PASSWORD``, or ``CREDENTIAL`` values into
  visible fields.
- Treat public release evidence as bounded evidence, not production certification. PyPI publishing
  should use Trusted Publishing/OIDC, SBOM and vulnerability scan artifacts should be archived when
  available, and deployments that handle sensitive data need their own threat model and acceptance
  profile. Release evidence does not certify long-running production operations.
- Verify PyPI provenance after publication with ``tools/pypi_provenance_check.py``. The release
  workflow now fails before GitHub release asset publication if a selected PyPI artifact is missing
  Trusted Publishing attestations.
- Generate supply-chain evidence for the actual install profile you deploy, not only for the base
  package. At minimum, archive a CycloneDX SBOM and ``pip-audit`` report for each enabled profile
  such as base CLI, ``agilab[ui]``, MLflow/tracking, offline/local-LLM tooling, and
  worker/cluster extras.
- Keep remote installer profiles opt-in. Prefer ``--dry-run`` first, use ``--no-remote-installers``
  for hardened/local-only installs, disable local-model/Ollama and cluster automation profiles
  unless they are needed, and review any staged remote shell installer before running it on a
  developer workstation.
- Keep public release proof synchronized with the GitHub tag and PyPI version. If release-proof
  pages lag behind a published release, republish the documentation and re-run the docs-source guard
  before using the page as audit evidence.

For end-to-end secure deployments or bespoke threat modelling, please engage your Thales security
contact or submit a request via <https://cpl.thalesgroup.com/fr/contact-us>.

Thanks for helping us keep AGILAB and its community secure.
