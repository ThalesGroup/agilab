# Changelog

All notable changes to this project will be documented in this file.

The format loosely follows Keep a Changelog. Dates are in YYYY-MM-DD.

## 0.7.12 — 2025-10-07

### Added
- Streamlit UI banner when no `OPENAI_API_KEY` is present (non-blocking, informational).
- EXPERIMENT page prompts for missing OpenAI API key with an option to save to `~/.agilab/.env`.
- PyPI/TestPyPI publisher improvements:
  - Unified Twine auth flags: `--twine-username`, `--twine-password` (prompt once if omitted).
  - Batch metadata check and single `twine upload` for all artifacts to reduce prompts and network roundtrips.
  - `--dry-run` now builds artifacts and prints the exact upload command (password masked) and artifact list.
- README and Quick Start docs updated:
  - `uvx -p 3.13 agilab` quick-run flow.
  - Managed workspace steps (without API key requirement in examples).
  - Publish instructions for TestPyPI/PyPI (dry-run, unified auth, batch upload).

### Changed
- CLI (`agilab` entry): SSH credentials and OpenAI API key are optional at launch. Flags are passed through when provided.
- Streamlit entrypoint (`AGILAB.py`): OpenAI API key help text clarifies that it is optional and can be provided via `OPENAI_API_KEY`.
- Docs generator (external docs repo): hardened to skip missing app directories, use project venv for Sphinx, and tolerate missing optional extensions.

### Removed
- Hard failure on missing `OPENAI_API_KEY` at app launch.
- Legacy per-package upload loop in publisher in favor of one batched upload.

### Notes / Migration
- Some pages (e.g., EXPERIMENT) still require an OpenAI API key to function. They now prompt inline rather than failing.
- The installer still accepts `--openai-api-key`; its behavior is unchanged unless explicitly requested.
- For publishing, you can continue to rely on `~/.pypirc`. The new auth flags override it when provided.
