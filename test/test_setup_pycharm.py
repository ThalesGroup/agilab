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


def _make_agilab_source_root(path: Path) -> Path:
    (path / "src" / "agilab").mkdir(parents=True)
    (path / "src" / "agilab" / "About_agilab.py").write_text("", encoding="utf-8")
    (path / "pyproject.toml").write_text("[project]\nname = \"agilab\"\n", encoding="utf-8")
    return path


def _jdk_table_with_agilab_sdk(path: Path, project_root: Path) -> Path:
    jdk_table = path / "jdk.table.xml"
    jdk_table.write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<application>
    <component name="ProjectJdkTable">
        <jdk version="2">
            <name value="uv (agilab)" />
            <type value="Python SDK" />
            <homePath value="{project_root / ".venv" / "bin" / "python"}" />
            <additional ASSOCIATED_PROJECT_PATH="{project_root}" IS_UV="true" UV_WORKING_DIR="{project_root}">
                <setting name="FLAVOR_ID" value="UvSdkFlavor" />
                <setting name="FLAVOR_DATA" value="{{}}" />
            </additional>
        </jdk>
    </component>
</application>
""",
        encoding="utf-8",
    )
    return jdk_table


def test_jdk_table_detects_conflicting_agilab_source_root(tmp_path: Path) -> None:
    current_root = _make_agilab_source_root(tmp_path / "current")
    other_root = _make_agilab_source_root(tmp_path / "other")
    jdk_table = _jdk_table_with_agilab_sdk(tmp_path, other_root)

    table = setup_pycharm.JdkTable.__new__(setup_pycharm.JdkTable)
    table.sdk_type = "Python SDK"
    table.jdk_tables = [jdk_table]

    assert table.conflicting_source_roots("uv (agilab)", current_root) == [other_root.resolve()]


def test_jdk_table_allows_same_agilab_source_root(tmp_path: Path) -> None:
    current_root = _make_agilab_source_root(tmp_path / "current")
    jdk_table = _jdk_table_with_agilab_sdk(tmp_path, current_root)

    table = setup_pycharm.JdkTable.__new__(setup_pycharm.JdkTable)
    table.sdk_type = "Python SDK"
    table.jdk_tables = [jdk_table]

    assert table.conflicting_source_roots("uv (agilab)", current_root) == []


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


def test_tracked_run_configs_use_explicit_uv_sdks() -> None:
    if Path(".git").exists():
        tracked = subprocess.run(
            ["git", "ls-files", "--", ".idea/runConfigurations/*.xml"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    else:
        tracked = [
            str(path)
            for path in sorted(Path(".idea/runConfigurations").glob("*.xml"))
            if not path.name.startswith("_")
        ]

    problems: list[str] = []
    for rel_path in tracked:
        path = Path(rel_path)
        if path.name == "folders.xml":
            continue
        config = ET.parse(path).getroot().find("configuration")
        if config is None:
            continue
        options = {opt.get("name"): opt.get("value", "") for opt in config.findall("option")}
        option_values = "\n".join(options.values())
        if not options.get("SDK_NAME"):
            problems.append(f"{path.name}: missing SDK_NAME")
        if options.get("IS_MODULE_SDK") != "false":
            problems.append(f"{path.name}: IS_MODULE_SDK={options.get('IS_MODULE_SDK')!r}")
        if "wenv/builtin" in option_values:
            problems.append(f"{path.name}: stale builtin worker path")

    assert problems == []
