from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import xml.etree.ElementTree as ET


MODULE_PATH = Path("pycharm/setup_pycharm.py")
SPEC = importlib.util.spec_from_file_location("setup_pycharm_test_module", MODULE_PATH)
assert SPEC and SPEC.loader
setup_pycharm = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = setup_pycharm
SPEC.loader.exec_module(setup_pycharm)


def test_set_project_sdk_writes_project_root_manager_and_black(tmp_path: Path) -> None:
    cfg = setup_pycharm.Config(root=tmp_path)
    cfg.create_directories()
    project = setup_pycharm.Project(cfg)

    project.set_project_sdk("uv (agilab)")

    tree = ET.parse(cfg.MISC)
    root = tree.getroot()

    project_root_manager = root.find("./component[@name='ProjectRootManager']")
    assert project_root_manager is not None
    assert project_root_manager.get("project-jdk-name") == "uv (agilab)"
    assert project_root_manager.get("project-jdk-type") == "Python SDK"

    black_component = root.find("./component[@name='Black']")
    assert black_component is not None
    black_sdk = black_component.find("./option[@name='sdkName']")
    assert black_sdk is not None
    assert black_sdk.get("value") == "uv (agilab)"
