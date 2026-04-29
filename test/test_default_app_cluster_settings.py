from __future__ import annotations

import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _settings_files() -> list[Path]:
    return [
        *sorted((ROOT / "src/agilab/apps/builtin").glob("*_project/src/app_settings.toml")),
        *sorted((ROOT / "src/agilab/apps/templates").glob("*_template/src/app_settings.toml")),
    ]


def test_default_apps_seed_two_local_dask_workers() -> None:
    settings_files = _settings_files()
    assert settings_files

    for settings_file in settings_files:
        payload = tomllib.loads(settings_file.read_text(encoding="utf-8"))
        cluster = payload.get("cluster")

        assert isinstance(cluster, dict), settings_file
        assert cluster.get("cluster_enabled") is False, settings_file
        assert cluster.get("scheduler") == "127.0.0.1:8786", settings_file
        assert cluster.get("workers") == {"127.0.0.1": 2}, settings_file
