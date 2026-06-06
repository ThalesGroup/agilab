from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "worker_env_reuse.py"


def _load_module():
    sys.path.insert(0, str(ROOT / "tools"))
    spec = importlib.util.spec_from_file_location(
        "worker_env_reuse_test_module", MODULE_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_worker_env_reuse_reports_marker_missing_then_reuse(tmp_path: Path) -> None:
    module = _load_module()
    worker_pyproject = tmp_path / "worker" / "pyproject.toml"
    worker_copy = tmp_path / "wenv" / "demo_worker"
    worker_pyproject.parent.mkdir()
    worker_pyproject.write_text(
        "[project]\nname='demo-worker'\nversion='1'\n", encoding="utf-8"
    )

    missing = module.worker_env_reuse_report(
        worker_pyproject=worker_pyproject,
        worker_copy=worker_copy,
    )
    assert missing["status"] == "rebuild"
    assert missing["reason"] == "marker-missing"

    marker = module.write_marker(missing)
    assert marker.is_file()

    reuse = module.worker_env_reuse_report(
        worker_pyproject=worker_pyproject,
        worker_copy=worker_copy,
    )
    assert reuse["status"] == "reuse"
    assert reuse["reason"] == "manifest-unchanged"


def test_worker_env_reuse_detects_manifest_change_and_json_cli(
    tmp_path: Path, capsys
) -> None:
    module = _load_module()
    worker_pyproject = tmp_path / "worker" / "pyproject.toml"
    worker_copy = tmp_path / "wenv" / "demo_worker"
    worker_pyproject.parent.mkdir()
    worker_pyproject.write_text(
        "[project]\nname='demo-worker'\nversion='1'\n", encoding="utf-8"
    )
    module.write_marker(
        module.worker_env_reuse_report(
            worker_pyproject=worker_pyproject,
            worker_copy=worker_copy,
        )
    )

    worker_pyproject.write_text(
        "[project]\nname='demo-worker'\nversion='2'\n", encoding="utf-8"
    )
    changed = module.worker_env_reuse_report(
        worker_pyproject=worker_pyproject,
        worker_copy=worker_copy,
    )
    assert changed["status"] == "rebuild"
    assert changed["reason"] == "manifest-changed"

    assert (
        module.main(
            [
                "--worker-pyproject",
                str(worker_pyproject),
                "--worker-copy",
                str(worker_copy),
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == module.SCHEMA_VERSION
