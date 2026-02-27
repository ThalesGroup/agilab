# Changelog

## v2026.02.27-2 (2026-02-27)

### Packaging note
- `v2026.02.27-2` is a Git patch tag only.
- Python package version remains `2026.02.27` (no PyPI republish for this patch tag).

### Added
- Service health checker now supports SLA thresholds loaded from per-app
  `app_settings.toml` (`[cluster.service_health]`) with CLI overrides.
- Service health checker now supports Prometheus output format via
  `--format prometheus`.
- ORCHESTRATE service mode now includes a one-click `HEALTH gate` action and
  persists SLA thresholds per app.
- Built-in and template apps now ship default `cluster.service_health`
  thresholds:
  - `allow_idle = false`
  - `max_unhealthy = 0`
  - `max_restart_rate = 0.25`

### Fixed
- CI `tests (3.13)` now writes a dedicated coverage artifact for service health
  smoke tests (`.coverage.service-health`).
- CI now validates coverage artifacts explicitly before `coverage combine` and
  combines using robust file discovery, preventing regressions where tests pass
  but coverage merge fails.
