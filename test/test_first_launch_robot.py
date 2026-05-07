from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


MODULE_PATH = Path("tools/first_launch_robot.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "first_launch_robot_test_module",
        MODULE_PATH,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_first_launch_robot_passes_static_first_surface(tmp_path: Path) -> None:
    module = _load_module()

    report = module.build_report(target_seconds=90.0, timeout=90.0)

    assert report["schema"] == "agilab.first_launch_robot.v1"
    assert report["status"] == "pass"
    assert report["success"] is True
    assert report["within_target"] is True
    assert report["summary"]["check_count"] == 7
    checks = {check["id"]: check for check in report["checks"]}
    assert checks["first_launch_no_exceptions"]["status"] == "pass"
    assert checks["first_launch_env_initialized"]["status"] == "pass"
    assert checks["first_launch_first_proof_signal"]["status"] == "pass"
    docs_menu = checks["first_launch_docs_action"]["details"]["menu_items"]
    assert docs_menu["Get help"] == "https://thalesgroup.github.io/agilab/agilab-help.html"

    output = tmp_path / "first-launch-robot.json"
    assert module.main(["--target-seconds", "90", "--timeout", "90", "--output", str(output), "--json"]) == 0
    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted["status"] == "pass"
