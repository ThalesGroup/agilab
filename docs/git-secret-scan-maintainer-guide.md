# Local staged-secret protection

The pre-commit hook scans complete staged contents of added, modified, copied and
renamed files. A clean working copy cannot conceal a credential that is still in
the index. Deleted files and gitlinks add no parent-repository file contents.
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

Run the same check explicitly:

```sh
python3 tools/security/git_secret_scan_guard.py staged --root .
```

A missing or modified scanner, an invalid report, a scan failure, merge conflicts,
or an index that changes during the scan blocks the commit. Diagnostics include
only detector, filename and line; credential values and scanner logs are not
printed. The existing provenance checks remain active.
`AGILAB_SKIP_LOCAL_GUARDS` does not skip the secret check.

Use explicit placeholders such as `EXAMPLE_ONLY_NOT_A_REAL_KEY` in examples.
Credential-shaped values remain blocked in tests and IDE configurations.
Inline `gitleaks:allow` comments, staged ignore files and inherited Gitleaks
configuration do not disable this gate. The pinned scanner's default detectors
and built-in allowlists apply; this is pattern detection, not a provider validity
check or proof that every possible secret format is covered.

The authoritative script and regression tests are maintained in AGILAB and mirrored
without behavioral changes into the private apps repository.
