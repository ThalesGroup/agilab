from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import plistlib
import shlex
import sys
import xml.etree.ElementTree as ET

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "generate_agilab_xcode_project.py"
SPEC = importlib.util.spec_from_file_location("generate_agilab_xcode_project_test_module", MODULE_PATH)
assert SPEC and SPEC.loader
xcode = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = xcode
sys.path.insert(0, str(MODULE_PATH.parent))
try:
    SPEC.loader.exec_module(xcode)
finally:
    sys.path.pop(0)


def configuration(
    *,
    name: str = "example run",
    options: dict[str, str] | None = None,
    env: dict[str, str] | None = None,
    workdir: str = "$PROJECT_DIR$",
    config_type: str = "PythonConfigurationType",
    factory_name: str = "Python",
) -> xcode.RunConfiguration:
    values = {"SCRIPT_NAME": "$PROJECT_DIR$/tools/example.py", "WORKING_DIRECTORY": workdir}
    values.update(options or {})
    return xcode.RunConfiguration(
        name=name,
        config_type=config_type,
        factory_name=factory_name,
        options=values,
        env_map=env or {},
        workdir=workdir,
        group="agilab",
    )


def write_configuration(root: Path, filename: str, config: xcode.RunConfiguration) -> None:
    destination = root / ".idea" / "runConfigurations" / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    component = ET.Element("component", name="ProjectRunConfigurationManager")
    element = ET.SubElement(
        component,
        "configuration",
        name=config.name,
        type=config.config_type,
        factoryName=config.factory_name,
    )
    for key, value in config.options.items():
        ET.SubElement(element, "option", name=key, value=value)
    envs = ET.SubElement(element, "envs")
    for key, value in config.env_map.items():
        ET.SubElement(envs, "env", name=key, value=value)
    ET.ElementTree(component).write(destination, encoding="unicode")


def python_arguments(plan: object) -> list[str]:
    argv = plan.argv
    return argv[argv.index("python") + 1 :]


def test_launch_preserves_macro_arguments_and_clears_inherited_uv_state(tmp_path: Path) -> None:
    root = tmp_path / "AGILAB with spaces"
    root.mkdir()
    answer = "two words 'quoted'; $(touch unexpected) & value"
    config = configuration(
        options={
            "SCRIPT_NAME": "$PROJECT_DIR$/tools/a script.py",
            "PARAMETERS": '--input $PROJECT_DIR$/data/file.csv --label $Prompt:Archive label:demo$ --empty ""',
        },
        env={
            "VIRTUAL_ENV": "/also/stale",
            "PYTHONUNBUFFERED": "1",
            "UV_NO_SYNC": "1",
            "STREAMLIT_CONFIG_FILE": "$PROJECT_DIR$/src/agilab/resources/config.toml",
        },
    )
    environment = {
        "PATH": "/custom/bin",
        "VIRTUAL_ENV": "/stale/venv",
        "UV_RUN_RECURSION_DEPTH": "3",
        "UV_PROJECT_ENVIRONMENT": "/wrong/project/.venv",
        "PYTHONUNBUFFERED": "0",
        "AGILAB_XCODE_INPUT_ARCHIVE_LABEL": answer,
    }

    plan = xcode.build_launch(config, root, "/opt/uv tools/uv", environment)

    assert plan.argv[:9] == [
        "/opt/uv tools/uv",
        "--preview-features",
        "extra-build-dependencies",
        "run",
        "--no-sync",
        "--project",
        str(root),
        "--python",
        str(root / ".venv" / "bin" / "python"),
    ]
    assert python_arguments(plan) == [
        str(root / "tools" / "a script.py"),
        "--input",
        str(root / "data" / "file.csv"),
        "--label",
        answer,
        "--empty",
        "",
    ]
    assert plan.cwd == root
    assert "VIRTUAL_ENV" not in plan.env
    assert "UV_RUN_RECURSION_DEPTH" not in plan.env
    assert plan.env["UV_PROJECT_ENVIRONMENT"] == str(root / ".venv")
    assert plan.env["PYTHONUNBUFFERED"] == "1"
    assert plan.env["UV_NO_SYNC"] == "1"
    assert plan.env["PATH"] == "/custom/bin"
    assert plan.env["STREAMLIT_CONFIG_FILE"] == str(root / "src/agilab/resources/config.toml")
    assert environment["VIRTUAL_ENV"] == "/stale/venv"


@pytest.mark.parametrize("explicit_sdk_home", [False, True])
def test_launch_never_synchronizes_dependencies_into_prepared_sdk(tmp_path: Path, explicit_sdk_home: bool) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    sdk_environment = tmp_path / "foreign prepared sdk" / ".venv" if explicit_sdk_home else root / ".venv"
    python = sdk_environment / "bin/python"
    options = {"SDK_HOME": str(python)} if explicit_sdk_home else {}
    config = configuration(options=options)

    plan = xcode.build_launch(config, root, "/usr/local/bin/uv", {"UV_NO_SYNC": "0"})

    assert plan.argv[plan.argv.index("run") + 1] == "--no-sync"
    assert plan.argv[plan.argv.index("--python") + 1] == str(python)
    assert plan.env["UV_PROJECT_ENVIRONMENT"] == str(sdk_environment)


@pytest.mark.parametrize(
    ("sdk_name", "relative_project"),
    [
        ("agi-cluster", "src/agilab/core/agi-cluster"),
        ("agi-env", "src/agilab/core/agi-env"),
        ("agi-node", "src/agilab/core/agi-node"),
        ("agi-core", "src/agilab/core/agi-core"),
        ("custom_project", "src/agilab/apps/custom_project"),
        ("minimal_app_project", "src/agilab/apps/builtin/minimal_app_project"),
    ],
)
def test_sdk_environment_selection_is_independent_of_working_directory(
    tmp_path: Path, sdk_name: str, relative_project: str
) -> None:
    root = tmp_path / "repo"
    project = root / relative_project
    project.mkdir(parents=True)
    (project / "pyproject.toml").write_text(f'[project]\nname = "{sdk_name}"\nversion = "0.0.0"\n', encoding="utf-8")
    config = configuration(options={"SDK_NAME": f"uv ({sdk_name})"}, workdir="")

    plan = xcode.build_launch(config, root, "/usr/local/bin/uv", {})

    assert plan.argv[plan.argv.index("--project") + 1] == str(project)
    assert plan.argv[plan.argv.index("--python") + 1] == str(project / ".venv/bin/python")
    assert plan.env["UV_PROJECT_ENVIRONMENT"] == str(project / ".venv")
    assert plan.cwd == root


@pytest.mark.parametrize("checkout_name", ["agilab-src", "AGILAB source.v2"])
def test_renamed_checkout_sdk_selects_its_own_root_environment(tmp_path: Path, checkout_name: str) -> None:
    root = tmp_path / checkout_name
    root.mkdir()
    config = configuration(options={"SDK_NAME": f"uv ({root.name})"})

    plan = xcode.build_launch(config, root, "/usr/local/bin/uv", {})

    assert plan.argv[plan.argv.index("--project") + 1] == str(root)
    assert plan.argv[plan.argv.index("--python") + 1] == str(root / ".venv/bin/python")
    assert plan.env["UV_PROJECT_ENVIRONMENT"] == str(root / ".venv")
    assert plan.cwd == root


def test_worker_environment_and_home_script_use_selected_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    user_home = tmp_path / "user home"
    project = user_home / "wenv/minimal_app_worker"
    project.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(user_home))
    config = configuration(
        options={
            "SDK_NAME": "uv (minimal_app_worker)",
            "SCRIPT_NAME": "$USER_HOME$/log/execute/minimal_app/AGI_run_minimal_app.py",
        }
    )

    plan = xcode.build_launch(config, root, "/usr/local/bin/uv", {"HOME": str(user_home)})

    assert plan.argv[plan.argv.index("--project") + 1] == str(project)
    assert python_arguments(plan) == [str(user_home / "log/execute/minimal_app/AGI_run_minimal_app.py")]
    assert plan.cwd == root


@pytest.mark.parametrize(
    ("options", "module_name"),
    [
        ({"MODULE_NAME": "example.cli", "SCRIPT_NAME": "ignored"}, "example.cli"),
        ({"SCRIPT_NAME": "example.cli"}, "example.cli"),
        ({"SCRIPT_NAME": "streamlit"}, "streamlit"),
    ],
)
def test_python_module_mode_and_interpreter_options(
    tmp_path: Path, options: dict[str, str], module_name: str
) -> None:
    config = configuration(
        options={
            **options,
            "MODULE_MODE": "true",
            "INTERPRETER_OPTIONS": '-X dev -W "ignore::DeprecationWarning"',
            "PARAMETERS": '--message "hello world"',
        }
    )

    plan = xcode.build_launch(config, tmp_path, "/usr/local/bin/uv", {})

    assert python_arguments(plan) == [
        "-X",
        "dev",
        "-W",
        "ignore::DeprecationWarning",
        "-m",
        module_name,
        "--message",
        "hello world",
    ]


@pytest.mark.parametrize("module_mode", [False, True])
def test_pdb_launch_preserves_script_or_module_target(tmp_path: Path, module_mode: bool) -> None:
    config = configuration(
        options={
            "SCRIPT_NAME": "example.cli" if module_mode else "$PROJECT_DIR$/tools/example.py",
            "MODULE_MODE": str(module_mode).lower(),
            "INTERPRETER_OPTIONS": "-X dev",
            "PARAMETERS": '--message "hello world"',
        }
    )

    plan = xcode.build_launch(config, tmp_path, "/usr/local/bin/uv", {}, pdb=True)

    target = ["-m", "example.cli"] if module_mode else [str(tmp_path / "tools/example.py")]
    assert python_arguments(plan) == ["-X", "dev", "-m", "pdb", *target, "--message", "hello world"]


def test_pytest_json_escaped_options_and_keywords_are_preserved(tmp_path: Path) -> None:
    root = tmp_path / "repo with spaces"
    root.mkdir()
    config = configuration(
        config_type="tests",
        factory_name="py.test",
        options={
            "_new_target": json.dumps("$PROJECT_DIR$/test/test_example.py"),
            "_new_targetType": json.dumps("PATH"),
            "_new_keywords": json.dumps("status and not slow"),
            "_new_parameters": json.dumps("-q"),
            "_new_additionalArguments": '"--cov\\u003dagi_env"',
        },
    )

    plan = xcode.build_launch(config, root, "/usr/local/bin/uv", {})

    assert python_arguments(plan) == [
        "-m",
        "pytest",
        "-k",
        "status and not slow",
        "-q",
        "--cov=agi_env",
        str(root / "test/test_example.py"),
    ]


def test_pytest_legacy_class_and_method_target(tmp_path: Path) -> None:
    config = configuration(
        config_type="tests",
        factory_name="py.test",
        options={
            "SCRIPT_NAME": "$PROJECT_DIR$/test/test_example.py",
            "CLASS_NAME": "TestExample",
            "METHOD_NAME": "test_value",
            "USE_PATTERN": "true",
            "PATTERN": "value and not slow",
            "PARAMS": "-q",
            "ADDITIONAL_ARGS": "--maxfail=1",
        },
    )

    plan = xcode.build_launch(config, tmp_path, "/usr/local/bin/uv", {})

    assert python_arguments(plan) == [
        "-m",
        "pytest",
        "-k",
        "value and not slow",
        "-q",
        "--maxfail=1",
        str(tmp_path / "test/test_example.py") + "::TestExample::test_value",
    ]


def test_prompt_defaults_and_file_prompt_values_remain_single_arguments(tmp_path: Path) -> None:
    config = configuration(
        options={
            "SCRIPT_NAME": "$PROJECT_DIR$/apps/$Prompt:App path:builtin/example$/run.py",
            "PARAMETERS": "--file $FilePrompt$ --label $Prompt:Archive label:two words$",
        }
    )
    file_path = str(tmp_path / "input with spaces;literal.csv")

    plan = xcode.build_launch(config, tmp_path, "/usr/local/bin/uv", {"AGILAB_XCODE_FILE": file_path})

    assert xcode.prompt_key("Archive label") == "AGILAB_XCODE_INPUT_ARCHIVE_LABEL"
    assert python_arguments(plan) == [
        str(tmp_path / "apps/builtin/example/run.py"),
        "--file",
        file_path,
        "--label",
        "two words",
    ]


@pytest.mark.parametrize("prompt", ["$Prompt:Required answer$", "$FilePrompt$"])
def test_missing_required_prompt_fails_before_launch(tmp_path: Path, prompt: str) -> None:
    config = configuration(options={"PARAMETERS": f"--input {prompt}"})

    with pytest.raises(ValueError):
        xcode.build_launch(config, tmp_path, "/usr/local/bin/uv", {})


@pytest.mark.parametrize("malformed", [True, False])
def test_configuration_collection_rejects_invalid_or_unsupported_source(tmp_path: Path, malformed: bool) -> None:
    write_configuration(tmp_path, "example.xml", configuration())
    if malformed:
        (tmp_path / ".idea/runConfigurations/example.xml").write_text("<component><configuration", encoding="utf-8")
    else:
        write_configuration(tmp_path, "example.xml", configuration(config_type="JarApplication"))

    with pytest.raises(ValueError):
        xcode.collect_configurations(tmp_path)


def test_generated_project_is_deterministic_and_publish_build_only_checks(tmp_path: Path) -> None:
    write_configuration(tmp_path, "dev.xml", configuration(name="agilab run (dev)"))
    write_configuration(
        tmp_path,
        "publish.xml",
        configuration(
            name="pypi publish",
            options={
                "SCRIPT_NAME": "$PROJECT_DIR$/tools/pypi_publish.py",
                "PARAMETERS": "--repo pypi --git-tag --git-commit-version",
            },
        ),
    )
    payload = xcode.generate_project(tmp_path, "/usr/local/bin/uv")

    assert payload == xcode.generate_project(tmp_path, "/usr/local/bin/uv")
    assert not (tmp_path / "AGILAB.xcodeproj").exists()
    project = plistlib.loads(payload["project.pbxproj"].encode("utf-8"))
    objects = project["objects"]
    build_commands = [
        entry.get("shellScript", entry.get("buildArgumentsString", ""))
        for entry in objects.values()
        if entry.get("isa") in {"PBXShellScriptBuildPhase", "PBXLegacyTarget"}
    ]
    assert build_commands
    assert any("--check" in command for command in build_commands)
    assert all("--run" not in command and "pypi_publish.py" not in command for command in build_commands)
    schemes = [
        ET.fromstring(content)
        for path, content in payload.items()
        if path.startswith("xcshareddata/xcschemes/") and path.endswith(".xcscheme")
    ]
    assert len(schemes) == 2
    selected_names = set()
    build_targets = set()
    for scheme in schemes:
        launch = scheme.find("LaunchAction")
        assert launch is not None
        arguments = [
            argument
            for entry in launch.findall("./CommandLineArguments/CommandLineArgument")
            for argument in shlex.split(entry.attrib["argument"])
        ]
        selected_names.add(arguments[arguments.index("--run") + 1])
        for reference in scheme.findall("./BuildAction/BuildActionEntries/BuildActionEntry/BuildableReference"):
            build_targets.add(reference.attrib["BlueprintIdentifier"])
    assert selected_names == {"agilab run (dev)", "pypi publish"}
    assert len(build_targets) == 1
    assert build_targets <= objects.keys()


def test_canonical_prompt_default_change_requires_regeneration(tmp_path: Path) -> None:
    config = configuration(options={"PARAMETERS": "--app $Prompt:App path:old_project$"})
    write_configuration(tmp_path, "example.xml", config)
    xcode.write_project(tmp_path, xcode.generate_project(tmp_path, "/usr/local/bin/uv"))
    xcode.check_project_freshness(tmp_path)

    write_configuration(
        tmp_path,
        "example.xml",
        configuration(options={"PARAMETERS": "--app $Prompt:App path:new_project$"}),
    )

    with pytest.raises(ValueError, match="stale"):
        xcode.check_project_freshness(tmp_path)

    xcode.write_project(tmp_path, xcode.generate_project(tmp_path, "/usr/local/bin/uv"))
    xcode.check_project_freshness(tmp_path)


def test_regeneration_removes_owned_stale_schemes_and_preserves_user_state(tmp_path: Path) -> None:
    write_configuration(tmp_path, "example.xml", configuration(name="old run"))
    original = xcode.generate_project(tmp_path, "/usr/local/bin/uv")
    project = xcode.write_project(tmp_path, original)
    old_schemes = {path for path in original if path.endswith(".xcscheme")}
    user_state = project / "xcuserdata/reviewer.xcuserdatad/UserInterfaceState.xcuserstate"
    user_state.parent.mkdir(parents=True)
    user_state.write_bytes(b"user interface state\x00preserve")
    user_scheme = project / "xcshareddata/xcschemes/personal scheme.xcscheme"
    user_scheme.write_text('<Scheme version="1.3" />', encoding="utf-8")
    write_configuration(tmp_path, "example.xml", configuration(name="renamed run"))

    updated = xcode.generate_project(tmp_path, "/usr/local/bin/uv")
    xcode.write_project(tmp_path, updated)

    new_schemes = {path for path in updated if path.endswith(".xcscheme")}
    assert old_schemes.isdisjoint(new_schemes)
    assert all(not (project / path).exists() for path in old_schemes)
    assert all((project / path).is_file() for path in new_schemes)
    assert user_state.read_bytes() == b"user interface state\x00preserve"
    assert user_scheme.read_text(encoding="utf-8") == '<Scheme version="1.3" />'
    manifest = json.loads((project / xcode.MANIFEST).read_text(encoding="utf-8"))
    assert set(manifest["files"]) == set(updated)
    xcode.check_project_freshness(tmp_path)
