from __future__ import annotations

import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


MODULE_PATH = Path("tools/generate_runconfig_scripts.py")
SPEC = importlib.util.spec_from_file_location("generate_runconfig_scripts_test_module", MODULE_PATH)
assert SPEC and SPEC.loader
generate_runconfig_scripts = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = generate_runconfig_scripts
SPEC.loader.exec_module(generate_runconfig_scripts)


def test_generated_runconfig_scripts_clear_stale_virtual_env(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    runconfig_dir = repo_root / ".idea" / "runConfigurations"
    out_dir = repo_root / "tools" / "run_configs"
    runconfig_dir.mkdir(parents=True)

    (runconfig_dir / "streamlit.xml").write_text(
        """<component name="ProjectRunConfigurationManager">
  <configuration name="agilab run (dev)" type="PythonConfigurationType" factoryName="Python">
    <option name="MODULE_MODE" value="true" />
    <option name="SCRIPT_NAME" value="streamlit" />
    <option name="PARAMETERS" value="run $PROJECT_DIR$/src/agilab/main_page.py" />
    <option name="WORKING_DIRECTORY" value="$PROJECT_DIR$" />
    <envs>
      <env name="PYTHONUNBUFFERED" value="1" />
      <env name="UV_NO_SYNC" value="1" />
      <env name="VIRTUAL_ENV" value="" />
    </envs>
  </configuration>
</component>
""",
        encoding="utf-8",
    )

    generate_runconfig_scripts.generate_scripts(runconfig_dir, out_dir, repo_root)

    script = (out_dir / "agilab" / "agilab-run-dev.sh").read_text(encoding="utf-8")
    lines = script.splitlines()
    unset_index = lines.index("unset VIRTUAL_ENV")
    uv_index = next(index for index, line in enumerate(lines) if line.startswith("uv run "))

    assert "# Let uv select the run-config project .venv instead of a stale activated shell." in lines
    assert "export VIRTUAL_ENV=\"\"" not in lines
    assert unset_index < uv_index


def _run_generated_wrapper_with_stub(
    tmp_path: Path,
    monkeypatch,
    *,
    script: str,
    parameters: str,
    module_mode: bool = False,
    module_name: str = "",
    inputs: dict[str, str] | None = None,
):
    root = tmp_path / "AGILAB repo with spaces"
    runconfig_dir = root / ".idea" / "runConfigurations"
    runconfig_dir.mkdir(parents=True)
    component = ET.Element("component", name="ProjectRunConfigurationManager")
    configuration = ET.SubElement(
        component, "configuration", name="argv preservation",
        type="PythonConfigurationType", factoryName="Python",
    )
    for name, value in {
        "MODULE_MODE": str(module_mode).lower(),
        "MODULE_NAME": module_name,
        "SCRIPT_NAME": script,
        "PARAMETERS": parameters,
        "WORKING_DIRECTORY": "$PROJECT_DIR$",
    }.items():
        ET.SubElement(configuration, "option", name=name, value=value)
    envs = ET.SubElement(configuration, "envs")
    ET.SubElement(envs, "env", name="VIRTUAL_ENV", value="/configured/stale")
    ET.ElementTree(component).write(runconfig_dir / "argv.xml", encoding="unicode")
    monkeypatch.setattr(
        generate_runconfig_scripts,
        "tracked_runconfigs",
        lambda _root, directory: sorted(directory.glob("*.xml")),
    )
    out_dir = root / "tools" / "run_configs"
    generate_runconfig_scripts.generate_scripts(runconfig_dir, out_dir, root)
    wrappers = sorted(out_dir.rglob("*.sh"))
    assert len(wrappers) == 1

    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("Generated Bash wrapper execution requires Bash")
    stub_dir = tmp_path / "stub bin"
    stub_dir.mkdir()
    capture_path = tmp_path / "agilab-runconfig-argv-capture.json"
    capture_code = (
        "import json,os,sys; from pathlib import Path; "
        "Path(os.environ['AGILAB_RUNCONFIG_CAPTURE']).write_text("
        "json.dumps({'argv':sys.argv[1:],'cwd':os.getcwd(),"
        "'virtual_env':os.environ.get('VIRTUAL_ENV')}))"
    )
    stub = stub_dir / "uv"
    stub.write_text(
        "#!/bin/sh\nexec " + shlex.quote(sys.executable)
        + " -c " + shlex.quote(capture_code) + ' "$@"\n',
        encoding="utf-8",
    )
    stub.chmod(0o755)
    home = tmp_path / "home with spaces"
    environment = {
        "PATH": str(stub_dir) + os.pathsep + os.defpath,
        "HOME": str(home),
        "VIRTUAL_ENV": "/inherited/stale",
        "AGILAB_RUNCONFIG_CAPTURE": str(capture_path),
        **(inputs or {}),
    }
    process = subprocess.run(
        [bash, str(wrappers[0])], cwd=tmp_path, env=environment,
        text=True, capture_output=True, check=False,
    )
    captured = json.loads(capture_path.read_text()) if capture_path.exists() else None
    return process, captured, root, home


@pytest.mark.parametrize("mode", ["script", "module", "command"])
def test_generated_wrapper_preserves_argv_under_paths_with_spaces(
    tmp_path: Path, monkeypatch, mode: str
) -> None:
    script = '$ProjectFileDir$/tools/a "quoted"; $literal.py'
    expected_prefix = ["run", "python"]
    if mode == "module":
        script = "ignored.py"
        expected_prefix += ["-m", "package.module"]
    elif mode == "command":
        script = "streamlit"
        expected_prefix = ["run", "streamlit"]
    shell_text = "two words 'quoted'; $(touch unexpected) & value"
    backtick_text = chr(96) + "touch unexpected" + chr(96)
    parameters = (
        '--input $PROJECT_DIR$/data/input.csv '
        '--home "$USER_HOME$/data/a file.csv" '
        '--module-dir $MODULE_DIR$/config.json '
        + '--label "' + shell_text + '" '
        + '--backticks "' + backtick_text + '" --empty "" --glob "*"'
    )
    process, captured, root, home = _run_generated_wrapper_with_stub(
        tmp_path, monkeypatch, script=script, parameters=parameters,
        module_mode=mode != "script",
        module_name="package.module" if mode == "module" else "",
    )
    assert process.returncode == 0, process.stderr
    assert captured is not None
    if mode == "script":
        expected_prefix.append(str(root / 'tools/a "quoted"; $literal.py'))
    assert captured["argv"] == expected_prefix + [
        "--input", str(root / "data/input.csv"),
        "--home", str(home / "data/a file.csv"),
        "--module-dir", str(root / ".idea/modules/config.json"),
        "--label", shell_text,
        "--backticks", backtick_text,
        "--empty", "",
        "--glob", "*",
    ]
    assert captured["cwd"] == str(root)
    assert captured["virtual_env"] is None
    assert not (root / "unexpected").exists()


@pytest.mark.parametrize("override", [False, True])
def test_generated_wrapper_keeps_prompt_values_in_single_arguments(
    tmp_path: Path, monkeypatch, override: bool
) -> None:
    default = "two words default"
    answer = "two words 'quoted'; $(touch unexpected) & value"
    selected_file = str(tmp_path / "input with spaces;literal.csv")
    inputs = {"AGILAB_RUNCONFIG_INPUT_FILE_PROMPT": selected_file}
    if override:
        inputs["AGILAB_RUNCONFIG_INPUT_ARCHIVE_LABEL"] = answer
    process, captured, root, _home = _run_generated_wrapper_with_stub(
        tmp_path, monkeypatch,
        script="$PROJECT_DIR$/tools/argv.py",
        parameters=(
            "--label $Prompt:Archive label:two words default$ "
            "--embedded prefix:$Prompt:Archive label:two words default$:suffix "
            "--file $FilePrompt$"
        ),
        inputs=inputs,
    )
    assert process.returncode == 0, process.stderr
    assert captured is not None
    value = answer if override else default
    assert captured["argv"] == [
        "run", "python", str(root / "tools/argv.py"),
        "--label", value,
        "--embedded", "prefix:" + value + ":suffix",
        "--file", selected_file,
    ]
    assert not (root / "unexpected").exists()


def test_generated_wrapper_requires_file_prompt_before_uv_launch(
    tmp_path: Path, monkeypatch
) -> None:
    process, captured, _root, _home = _run_generated_wrapper_with_stub(
        tmp_path, monkeypatch, script="$PROJECT_DIR$/tools/argv.py",
        parameters="--file $FilePrompt$",
    )
    assert process.returncode == 2
    assert "AGILAB_RUNCONFIG_INPUT_FILE_PROMPT" in process.stderr
    assert captured is None


@pytest.mark.parametrize(
    "parameters, environment_name",
    [
        (
            "--first $Prompt:Archive label:first default$ "
            "--second $Prompt:Archive-label:second default$",
            "AGILAB_RUNCONFIG_INPUT_ARCHIVE_LABEL",
        ),
        (
            "--label $Prompt:file_prompt:first default$ --file $FilePrompt$",
            "AGILAB_RUNCONFIG_INPUT_FILE_PROMPT",
        ),
        (
            "--first $Prompt:Archive label:first default$ "
            "--second $Prompt:Archive label:second default$",
            "AGILAB_RUNCONFIG_INPUT_ARCHIVE_LABEL",
        ),
    ],
)
def test_generated_wrapper_rejects_ambiguous_prompt_overrides(
    tmp_path: Path, monkeypatch, parameters: str, environment_name: str
) -> None:
    with pytest.raises(ValueError, match="Ambiguous PyCharm input labels") as error:
        _run_generated_wrapper_with_stub(
            tmp_path, monkeypatch, script="$PROJECT_DIR$/tools/argv.py",
            parameters=parameters,
        )
    assert environment_name in str(error.value)
    assert "rename one prompt label" in str(error.value)
    assert not (tmp_path / "agilab-runconfig-argv-capture.json").exists()


@pytest.mark.parametrize(
    "parameters, error",
    [
        (
            "--first $Prompt:Archive label:first default$ "
            "--second $Prompt:Archive-label:second default$",
            "Ambiguous PyCharm input labels",
        ),
        ('--label "unterminated', "invalid PARAMETERS"),
    ],
    ids=["ambiguous-input", "invalid-parameters"],
)
def test_generation_preserves_existing_wrappers_when_later_validation_fails(
    tmp_path: Path, monkeypatch, parameters: str, error: str
) -> None:
    root = tmp_path / "AGILAB repo with spaces"
    runconfig_dir = root / ".idea" / "runConfigurations"
    runconfig_dir.mkdir(parents=True)
    configs = []
    for name, value in [("first valid config", "--label healthy"), ("later invalid config", parameters)]:
        component = ET.Element("component", name="ProjectRunConfigurationManager")
        configuration = ET.SubElement(
            component, "configuration", name=name, type="PythonConfigurationType",
            factoryName="Python",
        )
        for option, option_value in {
            "SCRIPT_NAME": "$PROJECT_DIR$/tools/argv.py",
            "PARAMETERS": value,
            "WORKING_DIRECTORY": "$PROJECT_DIR$",
        }.items():
            ET.SubElement(configuration, "option", name=option, value=option_value)
        path = runconfig_dir / f"{len(configs)}.xml"
        ET.ElementTree(component).write(path, encoding="unicode")
        configs.append(path)
    monkeypatch.setattr(
        generate_runconfig_scripts, "tracked_runconfigs",
        lambda _root, _directory: configs,
    )
    out_dir = root / "tools" / "run_configs"
    previous = out_dir / "agilab" / "previously-working-wrapper.sh"
    previous.parent.mkdir(parents=True)
    previous.write_bytes(b"#!/usr/bin/env bash\nexit 0\n")
    previous.chmod(0o755)
    (out_dir / "generated-wrapper-custody.txt").write_text("existing output metadata\n")

    def snapshot():
        return {
            str(path.relative_to(out_dir)): (
                path.is_dir(),
                None if path.is_dir() else path.read_bytes(),
                path.stat().st_mode,
            )
            for path in out_dir.rglob("*")
        }

    before = snapshot()
    with pytest.raises(ValueError, match=error):
        generate_runconfig_scripts.generate_scripts(runconfig_dir, out_dir, root)
    assert snapshot() == before
