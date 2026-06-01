---
name: agilab-release-verification
description: Verify AGILAB release readiness and post-release truth across PyPI, GitHub Releases, release proof, docs, coverage badges, and Hugging Face Space sync. Use when the user asks "ready for release?", "release it", "all good?", "HF aligned?", "why badge failed?", or any release/publication alignment check.
license: BSD-3-Clause (see repo LICENSE)
metadata:
  updated: 2026-06-01
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
uv --preview-features extra-build-dependencies run python tools/pypi_project_preflight.py
rg -n "sync-hf-space|publish-release-assets|publish-dataset-release-assets|dataset_release_assets|pypi-release-retention|release-proof|HF_TOKEN|hf_space_release_sync" .github/workflows/pypi-publish.yaml tools README.md docs/source
```

State whether Hugging Face sync, release proof refresh, PyPI retention, GitHub
code release assets, GitHub dataset release assets, and docs updates are
workflow-owned or manual for the current release scope. For PyPI, inspect
whether the optimized release plan selected packages or skipped
already-complete PyPI artifacts. For datasets, inspect whether the workflow
publishes a separate `datasets-<content-hash>` release or skips it because the
same dataset payload already exists. If a workflow owns a step, give its
condition instead of adding a duplicate manual step.

## Release Readiness Gate

Run this before tagging or dispatching the release workflow:

```bash
git status --short --branch --untracked-files=no
./dev maintenance
./dev release
```

`./dev release` must start with the strict AGILAB audit/review gate
(`./dev audit --strict`) before impact, PyPI, docs, typing, and badge checks.
The GitHub `pypi-publish` release workflow must mirror that ordering by running
`tools/agilab_audit.py --strict` as its first validation step after checkout,
Python, and `uv` setup.

If the checkout is dirty or diverged, do not call it release-ready until the
dirty paths and ahead/behind state are explained.

If `./dev release` fails, fix the local guard first unless the failure is
explicitly GitHub-only, secret-dependent, or network/publication-dependent.
If `./dev maintenance` fails, fix the reported extension-contract, ADR, docs
mirror, app/package contract, Evidence Core, or shared-core guardrail drift
before calling the release ready. A warning is not automatically a release
blocker, but it must be named explicitly; expected warnings currently include
coverage below the maintenance floor or real TODO/FIXME hotspot triage. The
dashboard still reports the gap to the long-term 99% coverage aspiration.
If `tools/pypi_project_preflight.py` reports a `missing-project` blocker,
register the pending trusted publisher before dispatching the release workflow.
An existing PyPI project with a new unpublished version is normal; a missing
project or newer PyPI version than the committed source is not.

Before registering a pending publisher for a new or renamed app package, sanity
check the public distribution name. Prefer concise `agi-app-<domain>` names and
avoid redundant forms such as `agi-app-*-project`, `agi-app-*-app-*`, or stale
prototype names. Once the name is chosen, update the complete package contract
surface in one change: `tools/package_split_contract.py`,
`src/agilab/lib/app_project_build_support.py`,
`src/agilab/lib/agi-apps/pyproject.toml`, `src/agilab/pypi_app_packages.py`,
`.github/dependabot.yml`, package README/metadata, public docs/license pages,
and tests. Then prove the rename with an old-name grep, `tools/app_contract_matrix.py
--quiet`, `tools/release_plan.py --check-workflow ... --skip-existing-pypi`,
`tools/pypi_trusted_publisher_contract.py --package <new-name>`, and a local
`python -m build <package-dir>` before creating the PyPI pending publisher.

For a release that should prune old PyPI releases and sync Hugging Face, verify
the required repository secrets exist before dispatching or rerunning the
workflow. Do not print secret values:

```bash
gh secret list -R ThalesGroup/agilab
```

Expected release automation secrets include `HF_TOKEN`,
`PYPI_RELEASE_PRUNE_USERNAME`, `PYPI_RELEASE_PRUNE_PASSWORD`, and either
`PYPI_RELEASE_PRUNE_TOTP_SECRET` or a one-time `PYPI_RELEASE_PRUNE_OTP` for
non-interactive PyPI cleanup. If `HF_TOKEN` is missing but the local Hugging
Face CLI is authenticated, set it without echoing the token:

```bash
hf auth token | gh secret set HF_TOKEN -R ThalesGroup/agilab
```

Before publishing a retry release, also verify the package graph that will be
uploaded, not just the source version:

```bash
uv lock --check
uv run python tools/release_plan.py --check-workflow .github/workflows/pypi-publish.yaml --format json --compact
uv run python tools/release_plan.py --check-workflow .github/workflows/pypi-publish.yaml --format json --compact --skip-existing-pypi
rm -rf /tmp/agilab-build-check
uv run python -m build --wheel --outdir /tmp/agilab-build-check .
python - <<'PY'
import email, pathlib, zipfile
wheel = next(pathlib.Path("/tmp/agilab-build-check").glob("agilab-*.whl"))
with zipfile.ZipFile(wheel) as archive:
    metadata_name = next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
    metadata = email.message_from_bytes(archive.read(metadata_name))
print(metadata["Version"])
for requirement in metadata.get_all("Requires-Dist") or []:
    if requirement.startswith(("agi-core", "agi-env", "agi-apps", "agi-pages", "agi-gui")):
        print(requirement)
PY
```

Do not publish if the top-level wheel metadata still pins internal packages to
the previous release. A PyPI upload can succeed while fresh installs fail later
because `Requires-Dist` points at pruned versions.

## Current Workflow Contract

The public release path is currently GitHub-workflow-owned after the tag or
workflow dispatch:

- `release-plan`: by default passes `--skip-existing-pypi`, so split packages whose current wheel/sdist already exist on PyPI are omitted from publication, provenance, retention, and release assets. Manual workflow dispatch can set `include_existing_pypi=true` only for deliberate release-asset repair.
- `publish-library-packages`: publishes selected split packages with PyPI Trusted Publishing.
- `publish-agilab`: publishes the top-level `agilab` package only when the umbrella package is still selected.
- `pypi-provenance-evidence`: verifies PyPI attestations only for `provenance_packages` selected by the release plan.
- `pypi-release-retention`: prunes older public PyPI releases only for selected provenance packages; missing current releases or failed cleanup are hard failures.
- `publish-release-assets`: uploads release artifacts and supply-chain evidence to GitHub Releases.
- `publish-dataset-release-assets`: builds a complete tracked-dataset archive, manifest, and checksums from an LFS-materialized checkout, then creates a separate content-addressed `datasets-<manifest-hash>` GitHub Release only when that dataset payload has not already been published. This job is intentionally independent from PyPI package selection; PyPI packages keep their packaged datasets.
- `sync-hf-space`: deploys the public Hugging Face Space after release assets only when the umbrella `agilab` release is selected.
- `sync-hf-space` also runs the hosted smoke check and records the deployed Space commit in release proof; package-only app/page publishes should skip it by release scope.

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
dataset-release-assets, and `sync-hf-space` jobs to be successful or
intentionally skipped by release scope. If the optimized release plan reports
`pypi_publish_selected=false`, the
publish/provenance/retention/release-assets path is expected to skip. Do not
report that as a failed release unless the user intended a new public
publication. The dataset release job has a separate skip condition: unchanged
dataset content should reuse the existing `datasets-<content-hash>` release.

### GitHub Release

```bash
gh release list --repo ThalesGroup/agilab --limit 5
gh release view <tag> --repo ThalesGroup/agilab
uv run python tools/release_status.py --tag <tag>
```

Check that assets exist and match the expected tag. Do not treat a tag alone as
a release. Prefer `tools/release_status.py` when you need one bounded tag-level
truth check across GitHub Release assets and PyPI package versions.

For dataset assets, check the separate dataset release, not the source/code
release. The code release should contain wheels, sdists, checksum manifests,
distribution evidence, provenance evidence, and supply-chain evidence. The
dataset release should contain `agilab-datasets-<hash>.tar.gz`,
`dataset-release-manifest.json`, and `dataset-SHA256SUMS.txt` under a
`datasets-<manifest-hash>` tag. Do not remove datasets from PyPI package
contents only because the dataset GitHub Release exists; the dataset release is
an additional source/LFS recovery surface.

For optimized split-package or repair releases, do not run `release_status.py`
against every public AGILAB package unless every package was intentionally
published at the same version. Pass the completed workflow's
`provenance_packages` list, plus the exact package version when the tag suffix
does not equal the package version:

```bash
uv --preview-features extra-build-dependencies run python tools/release_status.py \
  --tag <tag> \
  --package-version <package-version> \
  --packages "<provenance-packages-from-workflow>"
```

This avoids false failures on unchanged public apps/pages that are expected to
remain on their previous PyPI version. If old versions were pruned manually
outside the first workflow attempt, verify the selected package set with this
package-scoped command before calling the release complete.

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

For split-package release truth, check every provenance package from the
completed workflow, not only `agilab`. Do not recompute the optimized plan after
publication and assume an empty `provenance_packages` list means nothing was
published; after PyPI propagation, `--skip-existing-pypi` should often return
no remaining targets.

For a pre-dispatch preview:

```bash
uv run python tools/release_plan.py --skip-existing-pypi --format json --compact
```

For a completed workflow, use the `provenance_packages` output or step summary
from that run, then check those packages:

```bash
uv run python - <<'PY'
import json, urllib.request

expected = "<normalized-version>"  # Example: 2026.5.17.post2
packages = "<workflow provenance_packages output>".split()
missing = []
stale = []
for name in packages:
    req = urllib.request.Request(
        f"https://pypi.org/pypi/{name}/json",
        headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        releases = sorted((json.load(response).get("releases") or {}))
    if expected not in [version.lower() for version in releases]:
        missing.append((name, releases))
    old = [version for version in releases if version.lower() != expected]
    if old:
        stale.append((name, old))
print(json.dumps({"missing_expected": missing, "stale_old_releases": stale}, sort_keys=True))
PY
```

After PyPI pruning, `missing_expected` must be empty. `stale_old_releases`
should be empty when strict retention succeeds, but stale versions can remain as
cleanup debt when PyPI web login, unrecognized-login confirmation, or
reauthentication blocks deletion. Do not confuse that warning state with a
failed publish or failed provenance check.

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

When manually refreshing release proof after a failed or rerun deployment, edit
the canonical docs source, not only the public mirror:

```bash
uv --preview-features extra-build-dependencies run python tools/release_proof_report.py \
  --docs-source ../thales_agilab/docs/source \
  --refresh-from-local \
  --github-release-tag <tag> \
  --github-release-url "https://github.com/ThalesGroup/agilab/releases/tag/<tag>" \
  --hf-space-commit <space-sha> \
  --render \
  --check \
  --check-github-runs \
  --compact
uv --preview-features extra-build-dependencies run python tools/sync_docs_source.py \
  --source ../thales_agilab/docs/source \
  --target docs/source \
  --apply \
  --delete
```

After publishing, grep the public page for the expected values and stale
release wording. A page can contain the right table row while a CI evidence
summary still mentions an older tag.

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

If manual HF recovery is required after package publication, do it from a clean
public worktree at the intended `origin/main` commit, not from a dirty local
checkout. Run `tools/hf_space_release_sync.py --dry-run --json` first, then the
real sync, then update release proof with the returned `hf_space_commit`.

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
- Fresh PyPI install fails after retention/pruning: inspect the published
  `agilab` wheel metadata. If `Requires-Dist` pins internal packages to a
  deleted version, publish a new corrective `.postN` release for the whole
  package graph before deleting anything else.
- PyPI retention reports success but old releases remain: confirm whether PyPI
  required password/TOTP reauthentication or unrecognized-login confirmation.
  OIDC Trusted Publishing cannot delete old releases.
- GitHub Release exists but PyPI missing: inspect `publish-agilab` and split
  package jobs; do not assume release assets imply package upload.
- PyPI published but `sync-hf-space` skipped: first check
  `needs.release-plan.outputs.umbrella_selected`. A package-only app/page
  publish should skip HF Space sync and release-proof refresh. For an umbrella
  release, also check `needs.publish-release-assets.result`.
- `sync-hf-space` failed immediately with a missing token: configure the
  repository `HF_TOKEN` secret from a valid local or service Hugging Face token,
  then rerun the workflow job or perform a clean-worktree manual sync.
- PyPI retention records an interactive authentication or unrecognized-login
  warning: verify `PYPI_RELEASE_PRUNE_TOTP_SECRET` or a one-time
  `PYPI_RELEASE_PRUNE_OTP`, then use a self-hosted/static-IP runner or manual
  cleanup from a confirmed device if strict one-release retention is required.
- HF Space changed but release proof stale: inspect the `sync-hf-space` commit
  step before applying a manual docs refresh.
- Release proof shows the new tag/commit but still mentions an old tag in a
  CI-run summary: update `docs/source/data/release_proof.toml`, rerender, sync
  the public mirror, wait for `docs-publish`, and verify the published page.
- Docs source updated but public page stale: check `docs-publish.yaml` run and
  Pages publication status.
- Badge failed online but local guard passes: identify which badge is failing
  and whether it is CI status, coverage workflow, static PyPI badge, or a
  generated coverage SVG.

## PyPI Retention Guardrails

- Never delete the previous release until the replacement release is published
  and a clean public PyPI install with Python 3.13 succeeds.
- Delete only explicit stale versions. Protect the expected version in any
  cleanup script and fail closed when the current page is ambiguous.
- Treat PyPI credentials, TOTP seeds, recovery codes, cookies, and browser
  session data as secrets. Do not print them, commit them, or store them in
  repo-managed skills.
- If old releases must be deleted manually, use PyPI's project release pages or
  a controlled browser session, then re-run the split-package release truth
  check above.
- Keep a single-current-release policy as a post-publish cleanup step, not as a
  precondition for publishing the replacement package graph.

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
