---
name: agilab-pypi-release-maintenance
description: Guarded AGILAB PyPI release cleanup workflow. Use when an operator needs to inspect, prune, or delete old AGILAB PyPI package releases, especially after a noisy post-release or retention audit item.
license: BSD-3-Clause (see repo LICENSE)
metadata:
  updated: 2026-05-26
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
- For AGILAB release-workflow reruns, use the `ThalesGroup/agilab`
  repository only. Do not spend `thales_agilab` Actions quota for PyPI
  cleanup.
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
- The AGILAB release workflow is fail-closed for retention. If stale releases
  remain, report the exact residual package/version set instead of saying the
  cleanup completed.
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

When PyPI requests unrecognized-login confirmation on GitHub Actions, prefer the
direct web deletion path so the email confirmation belongs to the same session
that opens and submits the delete form:

```bash
uv --preview-features extra-build-dependencies run python tools/pypi_release_retention.py \
  --repo pypi \
  --packages "agilab" \
  --protect-version 2026.5.21.post1 \
  --confirm-delete \
  --direct-web-only \
  --json \
  --github-confirm-login-repository ThalesGroup/agilab \
  --github-confirm-login-variable PYPI_CONFIRM_LOGIN_URL \
  --github-confirm-login-timeout 1800
```

Do not work around PyPI cleanup failures by storing credentials in the repo,
weakening the protected-release check, or reusing an old confirmation URL.

For the release workflow path, dispatch only from the public AGILAB repository:

```bash
gh workflow run pypi-publish.yaml \
  -R ThalesGroup/agilab \
  --ref main \
  -f release_tag=v2026.05.26
```

If the retention job logs that it is waiting for
`PYPI_CONFIRM_LOGIN_URL`, set the fresh URL from the PyPI email immediately:

```bash
gh variable set PYPI_CONFIRM_LOGIN_URL \
  -R ThalesGroup/agilab \
  --body 'https://pypi.org/account/confirm-login/?token=FRESH_TOKEN_FROM_EMAIL'
```

After the run, clear the temporary handoff variable:

```bash
printf 'y\n' | gh variable delete PYPI_CONFIRM_LOGIN_URL -R ThalesGroup/agilab
```

## Retention Retry Lessons

When retention cleanup runs from GitHub Actions against many split packages:

- PyPI may require an unrecognized-login confirmation URL from the same runner
  IP before the delete form can be opened. Clear any stale
  `PYPI_CONFIRM_LOGIN_URL` first, then set only the fresh URL from the email
  generated by the active direct-web cleanup run.
- `pypi-cleanup` can fail to parse PyPI's release delete form with `No CSFR`
  / `No CSRF`. It can also generate a confirmation email for a throwaway
  `pypi-cleanup` login session, which does not help the later in-process delete
  session. Use `--direct-web-only` when confirmation handoff is involved.
- When PyPI 2FA uses TOTP, do not reuse the same generated code across package
  deletions. Wait for a fresh TOTP window before each deletion, otherwise a
  later package can fail with an invalid authentication code.
- After the workflow reports success, verify public PyPI JSON again with
  cache-busting headers before declaring cleanup complete; immediately after
  deletion, stale versions can appear briefly due to PyPI/cache propagation.
- PyPI can return `404 Not Found` from the manage release page after a deletion
  already succeeded. Current retention code treats that as success only after
  public PyPI JSON confirms the exact stale version is absent. If an older
  checkout fails on this race, update the retention tool before retrying.
- Remove temporary confirmation handoff variables or short-lived reader tokens
  after the run. Keep only the normal release-prune credentials that are part
  of the repository maintenance contract.
- If the user explicitly says to move forward with a known residual stale
  package, stop spending Actions minutes, cancel any extra cleanup workflow, and
  report the exact residual package/version as not blocked but not cleaned.

## Deprecated Package Cleanup

Use this when a stale PyPI project remains visible after a package rename or
package-split cleanup, for example an old page package whose source path no
longer exists in the current repository.

First prove the package is really deprecated:

- check the current release plan and package split contract;
- verify the PyPI project metadata live, especially `project_urls.Source`;
- confirm the source path referenced by PyPI no longer exists or is no longer a
  publish target;
- identify the replacement package name, if any.

Do not confuse a deprecated package with a package that is expected but missing
from PyPI. For example, if the release plan expects `agi-app-...` but PyPI
returns 404 for it, that package needs publication, not deletion.

Current-matrix cleanup wrappers such as `tools/pypi_publish.py --packages ...`
only accept packages that still belong to the current release plan. If the stale
PyPI project is no longer in the matrix, use `tools/pypi_release_retention.py`
or `pypi-cleanup` directly against the exact legacy PyPI project name.

For a stale package with several releases, prefer this sequence:

1. Query the exact visible releases from live PyPI JSON.
2. Run a `pypi-cleanup --query-only` dry-run with exact version regexes.
3. Delete older releases one exact version at a time, protecting the latest
   temporarily if using the retention workflow.
4. Verify live PyPI JSON after every successful deletion.

Deleting the final remaining release is effectively PyPI project removal. Treat
that as a separate owner action: do not use `--delete-project` from automation
unless the operator explicitly confirms the package name, understands that the
project reservation may be affected, and has valid PyPI web credentials.

If cleanup is blocked:

- local `pypi-cleanup` login failure means local web credentials are invalid or
  PyPI is rejecting that device/session;
- GitHub Actions failure after `No CSFR` / `No CSRF` plus a login redirect means
  PyPI likely needs an unrecognized-login confirmation URL for the active delete
  session;
- retry with `--direct-web-only`, clear stale handoff state, fetch the URL from
  the PyPI email generated by that retry, then set it while the run is waiting:

```bash
gh variable delete PYPI_CONFIRM_LOGIN_URL --repo ThalesGroup/agilab || true
gh variable set PYPI_CONFIRM_LOGIN_URL --repo ThalesGroup/agilab --body '<pypi-confirm-login-url>'
```

After the workflow consumes the URL, remove or rotate the variable so future
cleanup runs do not reuse an expired confirmation link.

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
