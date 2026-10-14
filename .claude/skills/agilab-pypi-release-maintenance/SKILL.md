---
name: agilab-pypi-release-maintenance
description: Plan and review exact AGILAB PyPI release deletions, archive verified distributions, and validate local cleanup without mixing it with publication. Use for an explicit package and version cleanup request or a release-retention review.
license: BSD-3-Clause (see repo LICENSE)
metadata:
  updated: 2026-10-14
---

# AGILAB PyPI Release Maintenance

Use the current procedure in `docs/pypi-cleanup-maintainer-guide.md` and inspect
`tools/pypi_release_retention.py` before maintenance. This skill covers exact
`package==version` selections, review evidence, verified distribution backups,
and local deletion of an explicitly approved release.

Publication never runs cleanup. Release publication belongs to
`agilab-release-verification`. The manual `pypi-release-retention` GitHub
workflow only creates a read-only plan from an explicit target list; it does
not receive PyPI credentials or delete releases. Additional visible historical
versions do not establish a cleanup failure or authorize deleting them.

## Review the exact selection

1. Read the current package versions, first-party dependency pins, public PyPI
   state, and the operator's requested targets. Do not infer targets from a date,
   a release plan, an older session, or the number of visible releases.
2. Review consumers of each version and obtain explicit approval for the exact
   targets before deletion. An audit or publication request authorizes inspection,
   not destructive maintenance.
3. Keep current project versions, exact first-party dependency pins, the latest
   published release, and every unselected release protected. The helper checks
   these protections; do not bypass a rejection.
4. Record the reviewed targets and create complete verified distribution backups.
   PyPI deletion is irreversible: the backups preserve local artifacts, but they
   cannot restore a deleted release or allow the same files to be re-uploaded.

## Plan, archive, then confirm locally

Use a current AGILAB checkout. Replace `<reviewed-version>` with an existing,
approved old version and keep the target quoted. Never execute the placeholder
literally. Repeat `--delete-release` for each additional exact reviewed target.
Wildcards, implicit package selections, duplicate canonical targets, unknown
first-party packages or versions, and protected versions are rejected.

Preview the selection without authentication or deletion:

```bash
uv --preview-features extra-build-dependencies run python tools/pypi_release_retention.py \
  --delete-release 'agi-gui==<reviewed-version>' --json
```

Create a new backup directory for the same selection:

```bash
uv --preview-features extra-build-dependencies run python tools/pypi_release_retention.py \
  --delete-release 'agi-gui==<reviewed-version>' \
  --backup-dir /absolute/path/agi-gui-reviewed-version-pypi-backup --json
```

The backup contains every official distribution and
`agilab_pypi_explicit_cleanup_backup_manifest.json`, with file sizes and SHA-256
hashes. Existing backups are never silently replaced. A failed download leaves
an incomplete directory; resolve the failure and use a new backup directory.

Only after target approval and backup verification, confirm the local operation:

```bash
uv --preview-features extra-build-dependencies run python tools/pypi_release_retention.py \
  --delete-release 'agi-gui==<reviewed-version>' \
  --backup-dir /absolute/path/agi-gui-reviewed-version-pypi-backup \
  --confirm-delete --direct-web-only --json
```

The helper rechecks protected versions, the complete current file set, and saved
hashes after authentication, immediately before each destructive POST. All CLI
deletion uses the guarded in-process web flow; external cleanup subprocesses
are disabled. A missing or changed backup, protection conflict, authentication
failure, or verification failure stops deletion.

## Credentials and session failures

PyPI upload uses Trusted Publishing/OIDC; release deletion needs web-management
credentials. The local helper reads the private `pypi_cleanup` section of
`~/.pypirc` or its explicit credential options. API upload tokens cannot
authorize deletion.

Never print or commit passwords, TOTP secrets, recovery codes, cookies, browser
profiles, or login-confirmation URLs. Keep credentials on the maintainer's
machine and outside GitHub workflow inputs, issues, PRs, and plan artifacts.

Password/TOTP authentication can require confirmation of the exact HTTP session.
A signed-in browser and the CLI have separate sessions. Do not retry a rejected
CLI session through a hosted workflow or treat a confirmation for another
session as authorization. Follow the maintainer guide's device-confirmed
browser procedure only after the same target review and complete backup.

## Retired procedures and close-out

The publisher's legacy deletion and purge options fail with guidance. Do not
append cleanup to publication, derive package-wide pruning from a release plan,
invoke an external cleanup tool, or delete an entire project. Unknown or
deprecated package names require a separate owner review; do not bypass the
first-party selection guard with an unrestricted fallback.

After cleanup, verify the exact deleted version is absent and the latest and
unselected releases remain available. Preserve the reviewed target list,
complete backup, hashes, and terminal verification evidence together. Report a
partial or interrupted deletion accurately and leave it unverified until the
helper's final checks complete.
