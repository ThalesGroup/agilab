---
name: agilab-release-verification
description: Verify AGILAB release readiness and post-release truth across PyPI, GitHub Releases, release proof, docs, coverage badges, and Hugging Face Space sync. Use when the user asks "ready for release?", "release it", "all good?", "HF aligned?", "why badge failed?", or any release/publication alignment check.
license: BSD-3-Clause (see repo LICENSE)
metadata:
  updated: 2026-05-17
---

# AGILAB Release Verification

Use this skill for release readiness, release execution checks, and post-release
alignment. Its purpose is to prevent stale plans and false "all good" answers by
checking the current code, current workflows, and public surfaces before making
claims.

Do not use this for normal bugfix validation. Use `agilab-testing` and
`plan-before-code` first for code changes.

## Non-Negotiable Rule

Before answering any release sequencing question, inspect the current workflow
contract. Do not answer from memory.

```bash
./dev --print-only release
uv --preview-features extra-build-dependencies run python tools/release_plan.py --check-workflow .github/workflows/pypi-publish.yaml
rg -n "sync-hf-space|publish-release-assets|pypi-release-retention|release-proof|HF_TOKEN|hf_space_release_sync" .github/workflows/pypi-publish.yaml tools README.md docs/source
```

State whether Hugging Face sync, release proof refresh, PyPI retention, GitHub
release assets, and docs updates are workflow-owned or manual for the current
release scope. If a workflow owns a step, give its condition instead of adding a
duplicate manual step.

## Release Readiness Gate

Run this before tagging or dispatching the release workflow:

```bash
git status --short --branch --untracked-files=no
./dev release
```

If the checkout is dirty or diverged, do not call it release-ready until the
dirty paths and ahead/behind state are explained.

If `./dev release` fails, fix the local guard first unless the failure is
explicitly GitHub-only, secret-dependent, or network/publication-dependent.

## Current Workflow Contract

The public release path is currently GitHub-workflow-owned after the tag or
workflow dispatch:

- `publish-library-packages`: publishes selected split packages with PyPI Trusted Publishing.
- `publish-agilab`: publishes the top-level `agilab` package.
- `pypi-provenance-evidence`: verifies PyPI attestations after upload.
- `pypi-release-retention`: prunes older public PyPI releases for selected projects.
- `publish-release-assets`: uploads release artifacts and supply-chain evidence to GitHub Releases.
- `sync-hf-space`: deploys the public Hugging Face Space after release assets when PyPI publication is selected and release assets succeeded.
- `sync-hf-space` also runs the hosted smoke check and records the deployed Space commit in release proof.

Confirm this against `.github/workflows/pypi-publish.yaml` before each release
answer because the workflow can change.

## Post-Release Truth Check

After the release workflow completes, verify each public surface separately.
Do not infer one surface from another.

### GitHub Actions

```bash
gh run list --repo ThalesGroup/agilab --workflow pypi-publish.yaml --limit 5
gh run view <run-id> --repo ThalesGroup/agilab --json status,conclusion,url,jobs
```

Success requires the relevant publish, provenance, retention, release-assets,
and `sync-hf-space` jobs to be successful or intentionally skipped by release
scope.

### GitHub Release

```bash
gh release list --repo ThalesGroup/agilab --limit 5
gh release view <tag> --repo ThalesGroup/agilab
```

Check that assets exist and match the expected tag. Do not treat a tag alone as
a release.

### PyPI

Use network truth, not a cached local install:

```bash
python - <<'PY'
import json, urllib.request
name = "agilab"
payload = json.load(urllib.request.urlopen(f"https://pypi.org/pypi/{name}/json", timeout=30))
print(payload["info"]["version"])
print(payload["info"]["project_url"])
PY
```

Check the simple index when resolver behavior looks stale:

```bash
python - <<'PY'
import urllib.request
print(urllib.request.urlopen("https://pypi.org/simple/agilab/", timeout=30).status)
PY
```

For install proof, always run outside the repo checkout:

```bash
cd /tmp
uv run --refresh-package agilab --no-project --with agilab==<version> python -c "import importlib.metadata as m; print(m.version('agilab'))"
uv --preview-features extra-build-dependencies run --refresh-package agilab --no-project --with 'agilab[examples]==<version>' python -m agilab.lab_run first-proof --json --max-seconds 60
```

Use `agilab[examples]` for packaged first-proof smoke; bare `agilab` is
intentionally lean.

### Release Proof and Docs

```bash
uv --preview-features extra-build-dependencies run python tools/release_proof_report.py --check --check-github-runs --compact
uv --preview-features extra-build-dependencies run python tools/workflow_parity.py --profile docs
```

If release proof was updated by the release workflow, verify the pushed docs
source and the published page:

```bash
gh run list --repo ThalesGroup/agilab --workflow docs-publish.yaml --limit 5
```

Then inspect:

- `https://thalesgroup.github.io/agilab/release-proof.html`
- `https://thalesgroup.github.io/agilab/`

Do not call docs aligned until the Pages workflow has succeeded and the public
page shows the expected version/tag/HF commit.

### Hugging Face Space

For the public demo route:

```bash
uv --preview-features extra-build-dependencies run python tools/hf_space_smoke.py --json
```

If checking deployment state directly:

```bash
python - <<'PY'
import json, urllib.parse, urllib.request
space = urllib.parse.quote("jpmorard/agilab", safe="")
payload = json.load(urllib.request.urlopen(f"https://huggingface.co/api/spaces/{space}", timeout=30))
print(payload.get("sha"))
print(payload.get("runtime", {}).get("stage"))
PY
```

The release workflow should record the Space commit in release proof when
`sync-hf-space` runs. If it did not, inspect the workflow job before doing any
manual sync.

### Badges

Check what the README points to before claiming a badge is fixed:

```bash
rg -n "badge|coverage|pypi-version|actions/workflows" README.md badges .github/workflows
uv --preview-features extra-build-dependencies run python tools/coverage_badge_guard.py --changed-only --require-fresh-xml
```

Coverage badge freshness is not the same thing as the GitHub workflow badge.
If the live badge still looks stale, check whether the workflow ran on `main`
after the badge/source change.

## Failure Triage

- PyPI JSON current but install resolves old version: check the Simple API and
  force a fresh resolver cache with `uv --refresh-package`.
- GitHub Release exists but PyPI missing: inspect `publish-agilab` and split
  package jobs; do not assume release assets imply package upload.
- PyPI published but `sync-hf-space` skipped: check
  `needs.release-plan.outputs.pypi_publish_selected` and
  `needs.publish-release-assets.result`.
- HF Space changed but release proof stale: inspect the `sync-hf-space` commit
  step before applying a manual docs refresh.
- Docs source updated but public page stale: check `docs-publish.yaml` run and
  Pages publication status.
- Badge failed online but local guard passes: identify which badge is failing
  and whether it is CI status, coverage workflow, static PyPI badge, or a
  generated coverage SVG.

## Final Answer Contract

When answering "all good?", report a compact matrix:

- Local release gate: pass/fail and command.
- GitHub release workflow: run id, conclusion, and failed/skipped jobs.
- PyPI: observed version from JSON or simple index.
- GitHub Release: observed tag/assets state.
- Release proof/docs: local check and published page state.
- Hugging Face: Space runtime stage and smoke result.
- Residual risks: anything not checked, cached, skipped, or dependent on a
  still-running workflow.

If any surface was not checked, say "not checked" rather than implying it is
good.
