---
name: agilab-pypi-release-maintenance
description: Guarded AGILAB PyPI release cleanup workflow. Use when an operator needs to inspect, prune, or delete old AGILAB PyPI package releases, especially after a noisy post-release or retention audit item.
license: BSD-3-Clause (see repo LICENSE)
metadata:
  updated: 2026-05-18
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
  protected release and prune everything older for a known package set.

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

Dry-run:

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
  --protect-version 2026.05.17.post2 \
  --confirm-delete \
  --json
```

If PyPI requests unrecognized-login confirmation or interactive cleanup, report
that as an operational blocker. Do not work around it by storing credentials or
weakening the protected-release check.

## After Cleanup

Verify that PyPI now exposes the intended state:

```bash
uv --preview-features extra-build-dependencies run python tools/release_proof_report.py --check --compact
uv --preview-features extra-build-dependencies run python tools/show_dependencies.py --repo pypi
```

If cleanup changes public release history materially, update release notes or
public docs only when they currently make a false claim.
