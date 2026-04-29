from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
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


def test_write_module_minimal_can_declare_source_root(tmp_path: Path) -> None:
    cfg = setup_pycharm.Config(root=tmp_path)
    cfg.create_directories()
    project = setup_pycharm.Project(cfg)

    module_dir = tmp_path / "src" / "agilab" / "core" / "agi-env"
    (module_dir / "src").mkdir(parents=True, exist_ok=True)

    iml_path = project.write_module_minimal("agi-env", module_dir, source_roots=("src",))

    tree = ET.parse(iml_path)
    root = tree.getroot()
    source_folder = root.find(
        "./component[@name='NewModuleRootManager']/content/sourceFolder[@url='file://$MODULE_DIR$/../../src/agilab/core/agi-env/src']"
    )

    assert source_folder is not None
    assert source_folder.get("isTestSource") == "false"


def _read_generated_config(tmp_path: Path, name: str) -> ET.Element:
    tree = ET.parse(tmp_path / ".idea" / "runConfigurations" / name)
    config = tree.getroot().find("configuration")
    assert config is not None
    return config


def _option(config: ET.Element, name: str) -> str:
    option = config.find(f"./option[@name='{name}']")
    assert option is not None
    return option.get("value", "")


def test_gen_app_script_preserves_builtin_app_venv_bindings(tmp_path: Path) -> None:
    script = Path.cwd() / "pycharm" / "gen_app_script.py"

    subprocess.run(
        [sys.executable, str(script), "builtin/flight_project"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    run_config = _read_generated_config(tmp_path, "_flight_run.xml")
    run_module = run_config.find("module")
    assert run_module is not None
    assert run_module.get("name") == "flight_project"
    assert _option(run_config, "SDK_NAME") == "uv (flight_project)"
    assert _option(run_config, "IS_MODULE_SDK") == "false"
    assert _option(run_config, "WORKING_DIRECTORY") == "$ProjectFileDir$/src/agilab/apps/builtin/flight_project"

    worker_config = _read_generated_config(tmp_path, "_flight_lib_worker.xml")
    assert _option(worker_config, "SDK_NAME") == "uv (flight_worker)"
    assert _option(worker_config, "WORKING_DIRECTORY") == "$USER_HOME$/wenv/flight_worker"
    assert "$USER_HOME$/wenv/flight_worker" in _option(worker_config, "PARAMETERS")
    assert "wenv/builtin" not in _option(worker_config, "PARAMETERS")

    install_config = _read_generated_config(tmp_path, "_flight_install.xml")
    install_module = install_config.find("module")
    assert install_module is not None
    assert install_module.get("name") == "agi-cluster"
    assert _option(install_config, "SDK_NAME") == "uv (agi-cluster)"

    preinstall_config = _read_generated_config(tmp_path, "_flight_preinstall_manager.xml")
    assert "$USER_HOME$/wenv/flight_worker/src/flight_worker/flight_worker.py" in _option(
        preinstall_config,
        "PARAMETERS",
    )

    manager_test = _read_generated_config(tmp_path, "_flight_test_manager.xml")
    assert _option(manager_test, "SCRIPT_NAME").endswith("/test/test_flight_manager.py")
