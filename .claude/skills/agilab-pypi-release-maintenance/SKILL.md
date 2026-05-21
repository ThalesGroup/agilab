---
name: agilab-pypi-release-maintenance
description: Guarded AGILAB PyPI release cleanup workflow. Use when an operator needs to inspect, prune, or delete old AGILAB PyPI package releases, especially after a noisy post-release or retention audit item.
license: BSD-3-Clause (see repo LICENSE)
metadata:
  updated: 2026-05-19
---

# AGILAB PyPI Release Maintenance

Use this skill only for AGILAB PyPI release cleanup and retention work. PyPI
release deletion is destructive and cannot be undone from the repository.

## Scope

This skill covers:

- inspecting current PyPI versions for AGILAB packages;
- deleting one exact old release version from an explicit package set;
- running the release-retention tool while protecting the current release;
- explaining why credentials are required and why Trusted Publishing cannot
  delete releases.

This skill does not cover normal package publication. Use
`agilab-release-verification` for release readiness and post-release truth.
For publication-process optimization checks, inspect the current workflow first:
`pypi-publish` has package-aware reuse logic and should avoid rebuilding or
uploading packages when PyPI already exposes the expected artifacts.

## Required Safety Rules

- Never delete the current protected release.
- Never delete a version inferred from memory. Read current state first.
- Never run broad cleanup before a dry-run or explicit state check.
- Never use `--delete-project`.
- Never print PyPI passwords, TOTP secrets, API tokens, or session cookies.
- Use exact versions for targeted deletion. Do not use loose regexes.
- Prefer exact deletion with `tools/pypi_publish.py --delete-pypi-release`
  when the user names a specific bad version.
- Use `tools/pypi_release_retention.py` only when the goal is to keep one
  protected release per selected package and prune everything older for a known
  package set.

## Credential Contract

PyPI file upload uses Trusted Publishing/OIDC, but PyPI release deletion is a
web-management operation. Cleanup needs real PyPI web-login credentials, not an
API token and not Trusted Publishing.

Accepted credential sources:

- CLI flags: `--username`, `--password`
- environment: `PYPI_USERNAME`, `PYPI_PASSWORD` or `PYPI_CLEANUP_PASSWORD`
- `~/.pypirc` cleanup section used by `tools/pypi_publish.py`

If 2FA is enabled, `tools/pypi_release_retention.py` can use `--otp-code` or
`--totp-secret`. Do not echo secret values.

## Inspection First

Start by identifying:

- the package names to affect;
- the exact version to delete, if this is targeted cleanup;
- the protected version that must remain visible;
- whether the release proof, changelog, and PyPI agree.

Useful checks:

```bash
uv --preview-features extra-build-dependencies run python tools/release_plan.py --format json --compact
uv --preview-features extra-build-dependencies run python tools/release_proof_report.py --check --compact
uv --preview-features extra-build-dependencies run python tools/show_dependencies.py --repo pypi
```

For a package-specific public state check:

```bash
python - <<'PY'
import json
import urllib.request

for name in ["agilab", "agi-core"]:
    payload = json.load(urllib.request.urlopen(f"https://pypi.org/pypi/{name}/json", timeout=30))
    print(name, payload["info"]["version"], sorted(payload.get("releases", {}))[-5:])
PY
```

## Explaining Two Visible Releases

When a user asks why there are still "two branches on PyPI", translate that
first: PyPI does not expose Git branches; it exposes project release versions.
Two visible entries usually means one current protected release plus one stale
older release.

Check live PyPI JSON before answering. If selected packages now show one visible
release, say that clearly and do not propose deletion. If some packages still
show two or more visible releases, explain the most likely causes:

- Trusted Publishing/OIDC can upload files but cannot delete old releases.
- Release deletion uses PyPI web-management credentials and may be blocked by
  2FA, unrecognized-login confirmation, CSRF/form changes, or PyPI cache delay.
- The AGILAB workflow records stale releases as a retention warning when PyPI
  deletion is operationally blocked, instead of invalidating otherwise complete
  release assets and Hugging Face sync.
- With split-package versioning, retention protects each selected package's own
  project version from the release-plan metadata. Do not assume every package
  must share the umbrella `agilab` version before deciding what is stale.

Only move to cleanup after verifying the exact stale version, the affected
package list, and the protected version that must remain.

## Exact Old-Version Deletion

Use this when the user identifies a specific stale version that should disappear
from selected packages.

Dry-run first:

```bash
uv --preview-features extra-build-dependencies run python tools/pypi_publish.py \
  --repo pypi \
  --cleanup-only \
  --dry-run \
  --packages agilab agi-core \
  --delete-pypi-release 2026.05.17.post1 \
  --cleanup-timeout 120 \
  --verbose
```

Then run the destructive command only after explicit confirmation that:

- the package list is correct;
- the version is not the protected/current release;
- real PyPI web-login credentials are available.

```bash
uv --preview-features extra-build-dependencies run python tools/pypi_publish.py \
  --repo pypi \
  --cleanup-only \
  --packages agilab agi-core \
  --delete-pypi-release 2026.05.17.post1 \
  --cleanup-timeout 120 \
  --verbose
```

`tools/pypi_publish.py` uses an exact normalized `pypi-cleanup --version-regex`
match for this path.

## Retention Cleanup

Use this only when the desired policy is "keep this protected release and delete
older releases" for selected packages.

For normal split-package releases, protect each selected package's own project
version from the release-plan metadata:

```bash
uv --preview-features extra-build-dependencies run python tools/pypi_release_retention.py \
  --repo pypi \
  --packages "agilab agi-core agi-env" \
  --repo-root . \
  --protect-versions-from-projects \
  --dry-run \
  --json
```

Use a single `--protect-version` only for legacy aligned-version cleanup.

Dry-run with one aligned protected version:

```bash
uv --preview-features extra-build-dependencies run python tools/pypi_release_retention.py \
  --repo pypi \
  --packages "agilab agi-core agi-env" \
  --protect-version 2026.05.17.post2 \
  --dry-run \
  --json
```

Destructive retention:

```bash
uv --preview-features extra-build-dependencies run python tools/pypi_release_retention.py \
  --repo pypi \
  --packages "agilab agi-core agi-env" \
  --repo-root . \
  --protect-versions-from-projects \
  --confirm-delete \
  --json
```

If PyPI requests unrecognized-login confirmation or interactive cleanup, report
that as an operational blocker. Do not work around it by storing credentials or
weakening the protected-release check.

## Retention Retry Lessons

When retention cleanup runs from GitHub Actions against many split packages:

- PyPI may require an unrecognized-login confirmation URL from the same runner
  IP before direct web fallback can delete releases.
- `pypi-cleanup` can fail to parse PyPI's release delete form with `No CSFR`
  / `No CSRF`; the direct web fallback is the intended recovery route.
- When PyPI 2FA uses TOTP, do not reuse the same generated code across package
  deletions. Wait for a fresh TOTP window before each deletion, otherwise a
  later package can fail with an invalid authentication code.
- After the workflow reports success, verify public PyPI JSON again with
  cache-busting headers before declaring cleanup complete; immediately after
  deletion, stale versions can appear briefly due to PyPI/cache propagation.
- Remove temporary confirmation handoff variables or short-lived reader tokens
  after the run. Keep only the normal release-prune credentials that are part
  of the repository maintenance contract.

## Publication Reuse Behavior

If an audit or release review flags noisy public publishes, check whether the
real issue is cleanup or package reuse. The public `pypi-publish` workflow now
performs a package-aware PyPI state check before each publishable package build:

- it reads the selected package/project/version from the release-plan matrix;
- it compares the expected wheel/sdist filenames with the current PyPI JSON
  metadata;
- when every expected artifact exists, it skips build, Trusted Publishing auth,
  and upload for that package;
- it writes release artifact hash evidence from PyPI metadata and downloads the
  reused files back into the GitHub Release distribution bundle;
- when any expected artifact is missing, it falls back to build, verify,
  manifest, and Trusted Publishing upload.

Do not use deletion/reupload churn to compensate for unchanged package
publication. Prefer fixing the reuse gate, release-plan matrix, or artifact
policy if the workflow rebuilds a package that is already complete on PyPI.

## After Cleanup

Verify that PyPI now exposes the intended state:

```bash
uv --preview-features extra-build-dependencies run python tools/release_proof_report.py --check --compact
uv --preview-features extra-build-dependencies run python tools/show_dependencies.py --repo pypi
```

If cleanup changes public release history materially, update release notes or
public docs only when they currently make a false claim.
