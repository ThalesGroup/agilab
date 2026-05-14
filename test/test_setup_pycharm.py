from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import xml.etree.ElementTree as ET


MODULE_PATH = Path("pycharm/setup_pycharm.py")
SPEC = importlib.util.spec_from_file_location("setup_pycharm_test_module", MODULE_PATH)
assert SPEC and SPEC.loader
setup_pycharm = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = setup_pycharm
SPEC.loader.exec_module(setup_pycharm)


def _make_agilab_source_root(path: Path) -> Path:
    (path / "src" / "agilab").mkdir(parents=True)
    (path / "src" / "agilab" / "main_page.py").write_text("", encoding="utf-8")
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


def test_jdk_table_discovers_pycharm_community_sdk_table(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / "home"
    ce_options = (
        home
        / "Library"
        / "Application Support"
        / "JetBrains"
        / "PyCharmCE2026.1"
        / "options"
    )
    ce_options.mkdir(parents=True)
    monkeypatch.setattr(setup_pycharm.Path, "home", lambda: home)
    monkeypatch.setattr(setup_pycharm.sys, "platform", "darwin")

    table = setup_pycharm.JdkTable("Python SDK")

    assert table.jdk_tables == [ce_options / "jdk.table.xml"]


def test_jdk_table_warns_when_no_pycharm_sdk_target_exists(
    tmp_path: Path,
    monkeypatch,
    caplog,
) -> None:
    monkeypatch.setattr(setup_pycharm.Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(setup_pycharm.sys, "platform", "darwin")

    with caplog.at_level(logging.WARNING):
        table = setup_pycharm.JdkTable("Python SDK")

    assert table.jdk_tables == []
    assert "Open PyCharm or PyCharm Community Edition once" in caplog.text


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


def test_jdk_table_rewrites_stale_uv_venv_path(tmp_path: Path) -> None:
    current_root = _make_agilab_source_root(tmp_path / "current")
    old_root = _make_agilab_source_root(tmp_path / "old")
    current_python = current_root / ".venv" / "bin" / "python"
    current_python.parent.mkdir(parents=True)
    current_python.write_text("", encoding="utf-8")
    jdk_table = _jdk_table_with_agilab_sdk(tmp_path, current_root)
    text = jdk_table.read_text(encoding="utf-8")
    text = text.replace(
        f'UV_WORKING_DIR="{current_root}"',
        f'UV_WORKING_DIR="{current_root}" UV_VENV_PATH="{old_root / ".venv"}"',
    )
    jdk_table.write_text(text, encoding="utf-8")

    table = setup_pycharm.JdkTable.__new__(setup_pycharm.JdkTable)
    table.sdk_type = "Python SDK"
    table.jdk_tables = [jdk_table]

    table.add_jdk("uv (agilab)", current_python)

    root = ET.parse(jdk_table).getroot()
    additional = root.find("./component[@name='ProjectJdkTable']/jdk/additional")
    assert additional is not None
    assert additional.get("UV_VENV_PATH") == str(current_root / ".venv")


def test_ensure_agilab_path_marker_rewrites_stale_checkout_marker(
    tmp_path: Path,
    monkeypatch,
) -> None:
    current_root = _make_agilab_source_root(tmp_path / "current")
    old_root = _make_agilab_source_root(tmp_path / "old")
    marker = tmp_path / "home" / ".local" / "share" / "agilab" / ".agilab-path"
    marker.parent.mkdir(parents=True)
    marker.write_text(f"{old_root / 'src' / 'agilab'}\n", encoding="utf-8")
    monkeypatch.setattr(
        setup_pycharm,
        "agilab_installation_marker_path",
        lambda: marker,
    )
    cfg = setup_pycharm.Config(root=current_root)

    assert setup_pycharm.ensure_agilab_path_marker(cfg)
    assert marker.read_text(encoding="utf-8") == f"{current_root / 'src' / 'agilab'}\n"


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


def test_ensure_project_sdk_binding_reapplies_root_sdk(tmp_path: Path) -> None:
    root = tmp_path / "agilab"
    root.mkdir()
    cfg = setup_pycharm.Config(root=root)
    root_python = root / ".venv" / "bin" / "python"
    root_python.parent.mkdir(parents=True)
    root_python.write_text("", encoding="utf-8")
    root_iml = root / ".idea" / "modules" / "agilab.iml"
    calls = SimpleNamespace(jdk=[], project=[], module=[])

    class FakeJdkTable:
        def add_jdk(self, name: str, home: Path) -> None:
            calls.jdk.append((name, home))

    class FakeProject:
        def set_project_sdk(self, name: str) -> None:
            calls.project.append(name)

        def set_module_sdk(self, path: Path, name: str) -> None:
            calls.module.append((path, name))

    assert setup_pycharm.ensure_project_sdk_binding(
        cfg,
        FakeJdkTable(),
        FakeProject(),
        root_iml,
    )
    assert calls.jdk == [("uv (agilab)", root_python.absolute())]
    assert calls.project == ["uv (agilab)"]
    assert calls.module == [(root_iml, "uv (agilab)")]


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


def test_content_url_for_resolves_relative_paths_from_project_root(tmp_path: Path) -> None:
    cfg = setup_pycharm.Config(root=tmp_path)

    assert setup_pycharm.content_url_for(cfg, Path("demo/src")) == (
        "file://$MODULE_DIR$/../../demo/src"
    )


def test_content_url_for_keeps_project_macro_for_symlinked_app_path(tmp_path: Path) -> None:
    cfg = setup_pycharm.Config(root=tmp_path / "agilab")
    cfg.ROOT.mkdir()
    external = tmp_path / "apps_repo" / "demo_project"
    external.mkdir(parents=True)
    link = cfg.ROOT / "src" / "agilab" / "apps" / "demo_project"
    link.parent.mkdir(parents=True)
    try:
        link.symlink_to(external, target_is_directory=True)
    except OSError:
        return

    assert setup_pycharm.content_url_for(cfg, link / "src") == (
        "file://$MODULE_DIR$/../../src/agilab/apps/demo_project/src"
    )


def test_ensure_source_folders_preserves_existing_exclude_order(tmp_path: Path) -> None:
    cfg = setup_pycharm.Config(root=tmp_path)
    project = setup_pycharm.Project(cfg)
    app = tmp_path / "demo"
    (app / "src").mkdir(parents=True)
    content = ET.Element(
        "content",
        {"url": "file://$MODULE_DIR$/../../demo"},
    )
    for name in (".venv", "build", "dist"):
        ET.SubElement(content, "excludeFolder", {"url": f"file://$MODULE_DIR$/../../demo/{name}"})

    assert project._ensure_source_folders(content, Path("demo"), ("src",))

    children = [(child.tag, child.get("url")) for child in list(content)]
    assert children == [
        ("sourceFolder", "file://$MODULE_DIR$/../../demo/src"),
        ("excludeFolder", "file://$MODULE_DIR$/../../demo/.venv"),
        ("excludeFolder", "file://$MODULE_DIR$/../../demo/build"),
        ("excludeFolder", "file://$MODULE_DIR$/../../demo/dist"),
    ]


def test_clean_modules_xml_prunes_local_stale_duplicates_and_keeps_external(tmp_path: Path) -> None:
    cfg = setup_pycharm.Config(root=tmp_path)
    cfg.create_directories()
    project = setup_pycharm.Project(cfg)
    allowed = cfg.MODULES_DIR / "agilab.iml"
    allowed.parent.mkdir(parents=True, exist_ok=True)
    allowed.write_text("<module />", encoding="utf-8")
    external = tmp_path.parent / "external.iml"

    cfg.MODULES.write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<project version="4">
  <component name="ProjectModuleManager">
    <modules>
      <module fileurl="file://$PROJECT_DIR$/.idea/agilab@1.iml" filepath="$PROJECT_DIR$/.idea/agilab@1.iml" />
      <module fileurl="file://$PROJECT_DIR$/.idea/modules/agilab.iml" filepath="$PROJECT_DIR$/.idea/modules/agilab.iml" />
      <module fileurl="file://$PROJECT_DIR$/.idea/modules/agilab.iml" filepath="$PROJECT_DIR$/.idea/modules/agilab.iml" />
      <module fileurl="file://{external}" filepath="{external}" />
    </modules>
  </component>
</project>
""",
        encoding="utf-8",
    )

    project.clean_modules_xml([allowed])

    tree = ET.parse(cfg.MODULES)
    modules = tree.getroot().findall("./component[@name='ProjectModuleManager']/modules/module")
    entries = [(module.get("fileurl"), module.get("filepath")) for module in modules]
    assert entries == [
        ("file://$PROJECT_DIR$/.idea/modules/agilab.iml", "$PROJECT_DIR$/.idea/modules/agilab.iml"),
        (f"file://{external}", str(external)),
    ]


def test_clean_stale_module_files_removes_root_and_numbered_copies(tmp_path: Path) -> None:
    cfg = setup_pycharm.Config(root=tmp_path)
    cfg.create_directories()
    project = setup_pycharm.Project(cfg)
    allowed = cfg.MODULES_DIR / "agilab.iml"
    unknown = cfg.MODULES_DIR / "custom_project.iml"
    stale_root = cfg.IDEA_DIR / "agilab@1.iml"
    stale_numbered = cfg.MODULES_DIR / "agi-page-geospatial-map@2.iml"
    stale_previous = cfg.MODULES_DIR / "view_maps.previous.20260501222857.iml"

    for path in (allowed, unknown, stale_root, stale_numbered, stale_previous):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<module />", encoding="utf-8")

    project.clean_stale_module_files([allowed])

    assert allowed.exists()
    assert unknown.exists()
    assert not stale_root.exists()
    assert not stale_numbered.exists()
    assert not stale_previous.exists()


def test_select_run_config_apps_skips_local_private_folders(tmp_path: Path) -> None:
    cfg = setup_pycharm.Config(root=tmp_path)
    cfg.create_directories()
    project = setup_pycharm.Project(cfg)
    folders_xml = cfg.RUN_CONFIGS_DIR / "folders.xml"
    folders_xml.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<component name="RunManager">
  <folder name="flight_telemetry_project" />
  <folder name="builtin/mycode_project" />
</component>
""",
        encoding="utf-8",
    )

    selected = setup_pycharm.select_run_config_apps(
        project,
        [
            Path("flight_telemetry_project"),
            Path("flowsynth_project"),
            Path("builtin/mycode_project"),
        ],
    )

    assert selected == [Path("flight_telemetry_project"), Path("builtin/mycode_project")]


def test_disable_pyproject_auto_import_turns_off_pyproject_module_sync(tmp_path: Path) -> None:
    cfg = setup_pycharm.Config(root=tmp_path)
    cfg.create_directories()
    project = setup_pycharm.Project(cfg)
    cfg.PY_PROJECT_MODEL.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<project version="4">
  <component name="PyProjectModelSettings">
    <option name="showConfigurationNotification" value="false" />
    <option name="usePyprojectToml" value="true" />
  </component>
</project>
""",
        encoding="utf-8",
    )

    project.disable_pyproject_auto_import()

    tree = ET.parse(cfg.PY_PROJECT_MODEL)
    option = tree.getroot().find(
        "./component[@name='PyProjectModelSettings']/option[@name='usePyprojectToml']"
    )
    assert option is not None
    assert option.get("value") == "false"


def test_rebinds_root_run_configs_to_checkout_sdk(tmp_path: Path) -> None:
    root = tmp_path / "agilab-src"
    root.mkdir()
    cfg = setup_pycharm.Config(root=root)
    cfg.create_directories()
    project = setup_pycharm.Project(cfg)

    root_config = cfg.RUN_CONFIGS_DIR / "agilab_run__dev_.xml"
    root_config.write_text(
        """<component name="ProjectRunConfigurationManager">
  <configuration default="false" name="agilab run (dev)" type="PythonConfigurationType" factoryName="Python">
    <module name="agilab" />
    <option name="SDK_HOME" value="" />
    <option name="IS_MODULE_SDK" value="true" />
    <option name="SCRIPT_NAME" value="streamlit" />
  </configuration>
</component>
""",
        encoding="utf-8",
    )
    fixed_root_config = cfg.RUN_CONFIGS_DIR / "publish_dry_run.xml"
    fixed_root_config.write_text(
        """<component name="ProjectRunConfigurationManager">
  <configuration default="false" name="publish dry run" type="PythonConfigurationType" factoryName="Python">
    <module name="agilab" />
    <option name="SDK_HOME" value="" />
    <option name="SDK_NAME" value="uv (agilab)" />
    <option name="IS_MODULE_SDK" value="false" />
  </configuration>
</component>
""",
        encoding="utf-8",
    )
    app_config = cfg.RUN_CONFIGS_DIR / "builtin_flight_run.xml"
    app_config.write_text(
        """<component name="ProjectRunConfigurationManager">
  <configuration default="false" name="builtin flight run" type="PythonConfigurationType" factoryName="Python">
    <module name="flight_telemetry_project" />
    <option name="SDK_HOME" value="" />
    <option name="SDK_NAME" value="uv (flight_telemetry_project)" />
    <option name="IS_MODULE_SDK" value="false" />
  </configuration>
</component>
""",
        encoding="utf-8",
    )

    assert project.ensure_root_run_config_sdk_bindings() == 2

    dev = _read_generated_config(root, "agilab_run__dev_.xml")
    assert dev.find("module").get("name") == "agilab-src"
    assert _option(dev, "SDK_NAME") == "uv (agilab-src)"
    assert _option(dev, "IS_MODULE_SDK") == "false"

    publish = _read_generated_config(root, "publish_dry_run.xml")
    assert publish.find("module").get("name") == "agilab-src"
    assert _option(publish, "SDK_NAME") == "uv (agilab-src)"
    assert _option(publish, "IS_MODULE_SDK") == "false"

    app = _read_generated_config(root, "builtin_flight_run.xml")
    assert app.find("module").get("name") == "flight_telemetry_project"
    assert _option(app, "SDK_NAME") == "uv (flight_telemetry_project)"


def test_ensure_project_ui_environment_syncs_missing_dev_ui_extra(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "agilab-src"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        """
[project]
name = "agilab"

[project.optional-dependencies]
mlflow = ["mlflow"]
ui = ["agi-gui", "streamlit", "tomli_w"]
""",
        encoding="utf-8",
    )
    python_path = root / ".venv" / "bin" / "python"
    python_path.parent.mkdir(parents=True)
    python_path.write_text("", encoding="utf-8")
    cfg = setup_pycharm.Config(root=root)
    calls: list[tuple[list[str], Path, bool]] = []

    monkeypatch.setattr(
        setup_pycharm,
        "venv_python_for",
        lambda project_dir: python_path if project_dir == root else None,
    )
    monkeypatch.setattr(setup_pycharm, "_find_uv_binary", lambda: "/usr/bin/uv")
    monkeypatch.setattr(setup_pycharm, "_missing_import_modules", lambda _python, _modules: ["mlflow"])

    def fake_run(argv, cwd, check):
        calls.append((argv, cwd, check))
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(setup_pycharm.subprocess, "run", fake_run)

    assert setup_pycharm.ensure_project_ui_environment(cfg) == python_path
    assert calls == [
        (
            [
                "/usr/bin/uv",
                "sync",
                "--project",
                ".",
                "--extra",
                "ui",
                "--extra",
                "mlflow",
                "--preview-features",
                "python-upgrade",
            ],
            root,
            True,
        )
    ]


def test_ensure_project_ui_environment_skips_when_ui_modules_import(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "agilab-src"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        """
[project]
name = "agilab"

[project.optional-dependencies]
mlflow = ["mlflow"]
ui = ["agi-gui", "streamlit", "tomli_w"]
""",
        encoding="utf-8",
    )
    python_path = root / ".venv" / "bin" / "python"
    python_path.parent.mkdir(parents=True)
    python_path.write_text("", encoding="utf-8")
    cfg = setup_pycharm.Config(root=root)

    monkeypatch.setattr(
        setup_pycharm,
        "venv_python_for",
        lambda project_dir: python_path if project_dir == root else None,
    )
    monkeypatch.setattr(setup_pycharm, "_missing_import_modules", lambda _python, _modules: [])
    monkeypatch.setattr(
        setup_pycharm.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected sync")),
    )

    assert setup_pycharm.ensure_project_ui_environment(cfg) == python_path


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
        [sys.executable, str(script), "builtin/flight_telemetry_project"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    run_config = _read_generated_config(tmp_path, "_flight_telemetry_run.xml")
    run_module = run_config.find("module")
    assert run_module is not None
    assert run_module.get("name") == "flight_telemetry_project"
    assert _option(run_config, "SDK_NAME") == "uv (flight_telemetry_project)"
    assert _option(run_config, "IS_MODULE_SDK") == "false"
    assert _option(run_config, "WORKING_DIRECTORY") == "$ProjectFileDir$/src/agilab/apps/builtin/flight_telemetry_project"

    worker_config = _read_generated_config(tmp_path, "_flight_telemetry_lib_worker.xml")
    assert _option(worker_config, "SDK_NAME") == "uv (flight_worker)"
    assert _option(worker_config, "WORKING_DIRECTORY") == "$USER_HOME$/wenv/flight_worker"
    assert "$USER_HOME$/wenv/flight_worker" in _option(worker_config, "PARAMETERS")
    assert "wenv/builtin" not in _option(worker_config, "PARAMETERS")

    install_config = _read_generated_config(tmp_path, "_flight_telemetry_install.xml")
    install_module = install_config.find("module")
    assert install_module is not None
    assert install_module.get("name") == "agi-cluster"
    assert _option(install_config, "SDK_NAME") == "uv (agi-cluster)"

    preinstall_config = _read_generated_config(tmp_path, "_flight_telemetry_preinstall_manager.xml")
    assert "$USER_HOME$/wenv/flight_worker/src/flight_worker/flight_worker.py" in _option(
        preinstall_config,
        "PARAMETERS",
    )

    manager_test = _read_generated_config(tmp_path, "_flight_telemetry_test_manager.xml")
    assert _option(manager_test, "SCRIPT_NAME").endswith("/test/test_flight_manager.py")


def test_tracked_run_configs_use_valid_uv_sdk_bindings() -> None:
    if Path(".git").exists():
        tracked = subprocess.run(
            ["git", "ls-files", "--", ".idea/runConfigurations/*.xml"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        tracked = [rel_path for rel_path in tracked if Path(rel_path).exists()]
        seen = set(tracked)
        for path in sorted(Path(".idea/runConfigurations").glob("*.xml")):
            rel_path = path.as_posix()
            if rel_path not in seen and not path.name.startswith("_"):
                tracked.append(rel_path)
                seen.add(rel_path)
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
        envs = {env.get("name"): env.get("value", "") for env in config.findall("./envs/env")}
        option_values = "\n".join(options.values())
        module_sdk = options.get("IS_MODULE_SDK") == "true"
        fixed_sdk = options.get("IS_MODULE_SDK") == "false"
        if module_sdk:
            if options.get("SDK_NAME"):
                problems.append(f"{path.name}: module SDK config should not hard-code SDK_NAME")
            if config.find("module") is None:
                problems.append(f"{path.name}: module SDK config has no module binding")
        elif fixed_sdk:
            if not options.get("SDK_NAME"):
                problems.append(f"{path.name}: fixed SDK config missing SDK_NAME")
        else:
            problems.append(f"{path.name}: IS_MODULE_SDK={options.get('IS_MODULE_SDK')!r}")
        if config.get("type") == "PythonConfigurationType" and envs.get("VIRTUAL_ENV") != "":
            problems.append(f"{path.name}: VIRTUAL_ENV must be cleared for uv run")
        if "wenv/builtin" in option_values:
            problems.append(f"{path.name}: stale builtin worker path")

    assert problems == []
