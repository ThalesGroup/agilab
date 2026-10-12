# Exact PyPI release cleanup

Publication does not delete historical releases. The manual
`pypi-release-retention` GitHub workflow creates a plan from an explicit list of
`package==version` targets, one per line. It never receives PyPI credentials or
deletes releases.

From a current AGILAB checkout, replace `<reviewed-version>` with an existing
old version whose deletion was reviewed and approved, then preview that target.
Keep the argument quoted; do not copy the placeholder as a real version:

```sh
uv --preview-features extra-build-dependencies run python tools/pypi_release_retention.py \
  --delete-release 'agi-gui==<reviewed-version>' --json
```

Repeat `--delete-release` for additional exact targets. Wildcards, implicit
package selections, duplicate canonical targets, unknown first-party packages
or versions, current project versions, exact first-party dependency pins and
the latest published release are rejected. A publication command cannot run
`--purge-before`, `--purge-after`, `--cleanup-only`, `--delete-project` or
`--delete-pypi-release`; use this separate cleanup command.

Review consumers before deleting a version. Create a new backup directory:

```sh
uv --preview-features extra-build-dependencies run python tools/pypi_release_retention.py \
  --delete-release 'agi-gui==<reviewed-version>' \
  --backup-dir /absolute/path/agi-gui-reviewed-version-pypi-backup --json
```

The backup contains every official distribution file and
`agilab_pypi_explicit_cleanup_backup_manifest.json`, with file sizes and SHA-256
hashes. A failed download leaves an incomplete directory; use a new directory
after resolving the error. Existing backups are never silently replaced.

For automated local deletion, use the same exact selection and saved backup:

```sh
uv --preview-features extra-build-dependencies run python tools/pypi_release_retention.py \
  --delete-release 'agi-gui==<reviewed-version>' \
  --backup-dir /absolute/path/agi-gui-reviewed-version-pypi-backup \
  --confirm-delete --direct-web-only --json
```

The command reads web-login credentials from the existing `pypi_cleanup`
section of the maintainer's private `~/.pypirc` or its explicit credential
options. API upload tokens do not authorize deletion. Enter credentials only
on your machine, never in a GitHub issue, pull request or plan artifact.
All CLI deletions use the in-process web flow so protections, the complete
current file set and saved hashes are checked after authentication, immediately
before each destructive POST. External cleanup subprocesses are disabled.
Password/TOTP authentication may require confirmation of the exact HTTP
session; failure stops deletion and is never converted to success. A signed-in
browser and the CLI have separate sessions.

For a device-confirmed browser, first run the plan and archive steps above.
Open the selected project's exact release management page, check its project,
version and complete file list against the saved plan, then delete that release
only. A passkey or WebAuthn security key avoids PyPI's additional unknown-device
email check used with TOTP, as described in the [PyPI login policy](https://blog.pypi.org/posts/2025-11-14-login-verification/). Do not delete the entire project. Confirm the exact
version endpoint returns 404 and that the latest and other unselected releases
remain available; the CLI's confirmed route performs these checks itself.

PyPI deletion is irreversible. Backups preserve the artifacts for local use,
but the deleted release cannot be restored or its files re-uploaded ([PyPI deletion policy](https://pypi.org/help/#deletion)). Keep the
reviewed target list and verified backup with the maintenance evidence.
