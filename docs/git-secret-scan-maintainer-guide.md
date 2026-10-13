# Local staged-secret protection

The hooks scan complete staged contents of added, modified, copied and renamed
files. A clean working copy cannot conceal a credential that is still in the
index. Deleted files and gitlinks add no parent-repository file contents.
UTF-16 and UTF-32 text with a byte-order mark is decoded in the temporary scan
copy, so Windows configuration files receive the same detection as UTF-8.

The scanner is Gitleaks 8.30.1. Its official release archives and extracted binaries
are pinned by SHA-256 for macOS, Linux and Windows, on arm64 and x64. Source:
https://github.com/gitleaks/gitleaks/releases/tag/v8.30.1 (MIT license).

Install the scanner once:

```sh
python3 tools/security/git_secret_scan_guard.py install
git config core.hooksPath .githooks
```

Installation downloads only the pinned scanner. Subsequent scans work offline and
never send repository contents to GitGuardian or another service.

`pre-commit` remains active for ordinary commits. The supplementary
`prepare-commit-msg` hook scans before Git creates automatic merge commits,
cherry-picks and commits replayed by the rebase merge backend. `pre-applypatch`
delegates to `pre-commit` for `git am` and the rebase apply backend. Ordinary
commits consequently scan at both pre-commit and message preparation, protecting
the index checked at each stage.

These hooks cover the tested Git commit paths when `.githooks` is enabled. A
fast-forward reuses existing commits; `git apply` changes files or the index
without creating a commit, whose later ordinary commit is checked. They do not
cover every object-creation mechanism, such as `git commit-tree` or
`git fast-import`, or replace server-side controls.
See the [Git hook reference](https://git-scm.com/docs/githooks),
[merge implementation](https://github.com/git/git/blob/v2.56.0/builtin/merge.c),
[sequencer implementation](https://github.com/git/git/blob/v2.56.0/sequencer.c)
and [apply implementation](https://github.com/git/git/blob/v2.56.0/builtin/am.c)
for these entry points.

Run the same check explicitly:

```sh
python3 tools/security/git_secret_scan_guard.py staged --root .
```

A missing or modified scanner, an invalid report, a scan failure, merge conflicts,
or an index that changes during the scan blocks the commit. Diagnostics include
only detector, filename and line; credential values and scanner logs are not
printed. The existing provenance checks remain active.
`AGILAB_SKIP_LOCAL_GUARDS` does not skip the secret check.

Each scanner process has a 130-second external deadline. Exceeding it blocks the
commit even if an empty or partial report has already been written. The scanner's
native `--timeout` is deliberately omitted because it can stop before scanning
all staged content while returning success with an empty report.

Use explicit placeholders such as `EXAMPLE_ONLY_NOT_A_REAL_KEY` in examples.
Credential-shaped values remain blocked in tests and IDE configurations.
Inline `gitleaks:allow` comments, staged ignore files and inherited Gitleaks
configuration do not disable this gate. The pinned scanner's default detectors
and built-in allowlists apply; this is pattern detection, not a provider validity
check or proof that every possible secret format is covered.

The authoritative script and regression tests are maintained in AGILAB and mirrored
without behavioral changes into the private apps repository.
