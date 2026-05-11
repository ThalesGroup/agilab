## Contributor Quick Start

Use the same local-first path as adopters before changing code:

```bash
git clone https://github.com/ThalesGroup/agilab.git
cd agilab
git config core.hooksPath .githooks
uv --preview-features extra-build-dependencies sync --group dev
uv --preview-features extra-build-dependencies run python tools/newcomer_first_proof.py
```

If the newcomer proof fails, fix that baseline first or document why your
change is unrelated. The adoption checklist in `ADOPTION.md` explains the
supported first routes.

## How To Contribute

- Open a GitHub issue containing `[CONTRIBUTOR]` in its title if you are a new contributor.
- Keep pull requests focused on one app, feature, bug class, or documentation path.
- Prefer app-local changes before shared-core changes. Shared core includes `src/agilab/core/*`, installer/build/deploy tooling, and generic helpers reused across apps.
- Declare any third-party intellectual property used by your change in an `IP.md` file before pushing.
- Open management/process issues with `[MANAGEMENT]` in the title.

## Contribution Certificate And Review Policy

- DCO: by submitting a pull request, you certify the Developer Certificate of Origin 1.1 for your contribution. Add `Signed-off-by` trailers when requested by maintainers or when repository automation enforces them.
- CLA: no separate contributor license agreement is required for normal BSD-3-Clause contributions unless maintainers explicitly request one for a specific corporate or large-code contribution.
- Review policy: every pull request needs maintainer review before merge. Shared core, release tooling, security-sensitive, dependency, and packaging changes require review from an owner of that area.
- Branch protection: `main`, release tags, and publication workflows are maintainer-owned. Do not bypass required reviews, local guardrails, or release proof checks.
- Release ownership: only maintainers should create release tags, publish PyPI artifacts, update release proof, or approve Trusted Publishing changes.

## Pull Request Checklist

- Explain the use case or failure that the pull request addresses.
- Include the narrowest local validation command that proves the change.
- Add or update tests when behavior changes and an adjacent test pattern exists.
- Include a license check report using [checklicense](https://pypi.org/project/licensecheck/) when new dependencies, vendored code, or generated artifacts are introduced.
- If dependencies, extras, workflows, or optional runtime profiles change, include the relevant SBOM / `pip-audit` evidence or explain why the existing release profile is unchanged.
- Keep generated and local-only artifacts out of the diff.

## Security Checklist

Apply this checklist to any code, docs, workflow, app, or example that changes runtime behavior:

- Secrets: no credentials, tokens, API keys, private hostnames, or sensitive logs are committed or printed by default.
- Filesystem: app writes stay inside documented workspace/share paths and do not assume a developer-specific home directory.
- SSH and cluster execution: remote commands are quoted, host-key expectations are explicit, cluster-share behavior is documented, and public examples do not require private infrastructure.
- Streamlit exposure: public or shared deployments require an auth/TLS/reverse-proxy plan; local UI examples must not imply public production exposure is safe.
- Logs and artifacts: generated evidence avoids raw secrets and keeps sensitive datasets out of repository history.
- Dependencies: new dependencies are justified, scoped to the narrowest package or optional extra, license-reviewed, and included in supply-chain evidence when release-impacting.

## External App Acceptance

External apps and packaged examples are accepted only when they are reproducible and safe to run in the documented scope:

- The app has a clear `pyproject.toml`, deterministic first-run defaults, and no hidden dependency on private data or private network services.
- Network, LLM, cloud, SSH, GPU, or hardware-specific behavior is opt-in and documented with environment variables or settings.
- Analysis views and artifacts are understandable from public sample data or generated synthetic data.
- Secrets are referenced through environment variables or external secret stores, never checked into app files.
- Tests or smoke commands cover install/run/read-output behavior where a comparable public app already has coverage.

## Validation Guide

Start with the smallest useful check:

| Change type | Preferred local check |
|---|---|
| README or root docs only | `git diff --check` |
| Newcomer or install flow | `uv --preview-features extra-build-dependencies run python tools/newcomer_first_proof.py` |
| App-local behavior | Targeted `pytest` for that app or page |
| Workflow parity | `uv --preview-features extra-build-dependencies run python tools/workflow_parity.py --profile <name>` |
| Shared-core typing slice | `uv --preview-features extra-build-dependencies run --with mypy python tools/shared_core_strict_typing.py` |

Run broader test suites only when the change needs them. Do not trigger GitHub
Actions when the same failure can be reproduced locally.

## Coding Style

- Follow existing project style and keep changes minimal.
- Use [Black](https://pypi.org/project/black/) formatting for Python code.
- Prefer deterministic filesystem ordering in runtime code and tests.
- Do not introduce automatic API fallbacks; fail with a clear actionable error when a capability is missing.

## Repository Hygiene

- Do not commit virtual environments or build artifacts: `.venv/`, `dist/`, `build/`, `docs/html/`, `docs/build/`, `*.pyc`, `.pytest_cache/`.
- Recreate environments with `uv --preview-features extra-build-dependencies sync --group dev`.
- Do not commit datasets, generated binaries, archives, SQLite databases, or local IDE state.
- Store large data externally or use explicit Git LFS patterns.
- This repo may periodically rewrite history to remove large artifacts; rebase or re-clone if you see non-fast-forward updates.

## Documentation Hygiene

- Do not commit `docs/html/**`; it is generated output.
- Treat root files such as `README.md`, `README.pypi.md`, `ADOPTION.md`, `CHANGELOG.md`, and `CONTRIBUTING.md` as direct repository entry points.
- Sphinx documentation under `docs/source` is a managed public mirror. Maintainers refresh it from the canonical docs source before publication.
