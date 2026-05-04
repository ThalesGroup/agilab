from __future__ import annotations

import tomllib
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
SRC_PACKAGE = SRC_ROOT / "agilab"
sys.path.insert(0, str(SRC_ROOT))

import agilab as _agilab_package

if str(SRC_PACKAGE) not in _agilab_package.__path__:
    _agilab_package.__path__.insert(0, str(SRC_PACKAGE))

from agilab.app_template_registry import discover_app_templates


def _settings_files() -> list[Path]:
    templates = discover_app_templates(ROOT / "src/agilab/apps/templates", require_settings=True)
    return [
        *sorted((ROOT / "src/agilab/apps/builtin").glob("*_project/src/app_settings.toml")),
        *(template.settings_path for template in templates if template.settings_path is not None),
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
