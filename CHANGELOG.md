# Changelog

This changelog has been reset to reflect the new tag convention.

Starting 2025‑10‑08, Git tags follow the format `YYYY.MM.DD` (UTC). Package
versions (PEP 440) remain unchanged and may continue to use semantic versions.

## 2025.10.08
- Switch to date‑based Git tags (`YYYY.MM.DD` in UTC), with automatic de‑dupe (`-2`, `-3`, …) if the same day is tagged multiple times.
- PyPI publish: only remove top‑level app/page symlinks during umbrella build; restore them afterwards; skip removal in `--dry-run`.
- Docs: Sphinx site built in `agilab-apps` and committed under `agilab/docs/html`; Pages deploy serves committed content.
- CI: tests/coverage decoupled from docs deploy; badges use GitHub Actions and Codecov.
