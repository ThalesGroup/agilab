from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys


MODULE_PATH = Path("tools/generate_vscode_tasks.py")
SPEC = importlib.util.spec_from_file_location("generate_vscode_tasks_test_module", MODULE_PATH)
assert SPEC and SPEC.loader
generate_vscode_tasks = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = generate_vscode_tasks
SPEC.loader.exec_module(generate_vscode_tasks)


def test_generate_vscode_configs_build_shell_tasks_launches_and_inputs(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    runconfig_dir = repo_root / ".idea" / "runConfigurations"
    runconfig_dir.mkdir(parents=True)

    (runconfig_dir / "streamlit.xml").write_text(
        """<component name="ProjectRunConfigurationManager">
  <configuration name="agilab run (dev)" type="PythonConfigurationType" factoryName="Python">
    <option name="MODULE_MODE" value="true" />
    <option name="SCRIPT_NAME" value="streamlit" />
    <option name="PARAMETERS" value="run $PROJECT_DIR$/src/agilab/main_page.py -- --openai-api-key &quot;your-key&quot;" />
    <option name="WORKING_DIRECTORY" value="$PROJECT_DIR$" />
    <envs>
      <env name="PYTHONUNBUFFERED" value="1" />
      <env name="UV_NO_SYNC" value="1" />
    </envs>
  </configuration>
</component>
""",
        encoding="utf-8",
    )
    (runconfig_dir / "prompt.xml").write_text(
        """<component name="ProjectRunConfigurationManager">
  <configuration name="zip_all" type="PythonConfigurationType" factoryName="Python">
    <option name="SCRIPT_NAME" value="$PROJECT_DIR$/tools/zip_all.py" />
    <option name="PARAMETERS" value="--dir2zip $FilePrompt$ --label $Prompt:Archive label:demo$" />
    <option name="WORKING_DIRECTORY" value="$PROJECT_DIR$" />
  </configuration>
</component>
""",
        encoding="utf-8",
    )
    (runconfig_dir / "pytest.xml").write_text(
        """<component name="ProjectRunConfigurationManager">
  <configuration name="test agi_distributor" type="tests" factoryName="py.test">
    <option name="WORKING_DIRECTORY" value="$PROJECT_DIR$/src/agilab/core/agi-cluster" />
    <option name="_new_keywords" value="&quot;status and not slow&quot;" />
    <option name="_new_parameters" value="&quot;-q&quot;" />
    <option name="_new_additionalArguments" value="&quot;--maxfail=1&quot;" />
    <option name="_new_target" value="&quot;$PROJECT_DIR$/src/agilab/core/test/test_agi_distributor.py&quot;" />
    <option name="_new_targetType" value="&quot;PATH&quot;" />
  </configuration>
</component>
""",
        encoding="utf-8",
    )

    runconfigs = generate_vscode_tasks.collect_runconfigs(repo_root, runconfig_dir)
    tasks_payload = generate_vscode_tasks.build_tasks_payload(runconfigs)
    launch_payload = generate_vscode_tasks.build_launch_payload(runconfigs)

    assert tasks_payload["version"] == "2.0.0"
    tasks = tasks_payload["tasks"]
    assert len(tasks) == 3

    streamlit_task = next(task for task in tasks if task["label"] == "agilab run (dev)")
    assert streamlit_task["command"].startswith("uv run streamlit run ${workspaceFolder}/src/agilab/main_page.py")
    assert streamlit_task["options"]["cwd"] == "${workspaceFolder}"
    assert streamlit_task["options"]["env"]["PYTHONUNBUFFERED"] == "1"

    zip_task = next(task for task in tasks if task["label"] == "zip_all")
    assert zip_task["command"] == (
        "uv run python ${workspaceFolder}/tools/zip_all.py "
        "--dir2zip ${input:file_prompt} --label ${input:prompt_archive_label}"
    )

    pytest_task = next(task for task in tasks if task["label"] == "test agi_distributor")
    assert pytest_task["command"] == (
        "uv run pytest -k 'status and not slow' -q --maxfail=1 "
        "${workspaceFolder}/src/agilab/core/test/test_agi_distributor.py"
    )
    assert pytest_task["options"]["cwd"] == "${workspaceFolder}/src/agilab/core/agi-cluster"

    task_inputs = {item["id"]: item for item in tasks_payload["inputs"]}
    assert task_inputs["file_prompt"]["type"] == "promptString"
    assert task_inputs["prompt_archive_label"]["default"] == "demo"

    assert launch_payload["version"] == "0.2.0"
    launches = launch_payload["configurations"]
    assert len(launches) == 3

    streamlit_launch = next(item for item in launches if item["name"] == "agilab run (dev)")
    assert streamlit_launch["module"] == "streamlit"
    assert streamlit_launch["args"] == [
        "run",
        "${workspaceFolder}/src/agilab/main_page.py",
        "--",
        "--openai-api-key",
        "your-key",
    ]
    assert streamlit_launch["env"]["UV_NO_SYNC"] == "1"

    zip_launch = next(item for item in launches if item["name"] == "zip_all")
    assert zip_launch["program"] == "${workspaceFolder}/tools/zip_all.py"
    assert zip_launch["args"] == [
        "--dir2zip",
        "${input:file_prompt}",
        "--label",
        "${input:prompt_archive_label}",
    ]

    pytest_launch = next(item for item in launches if item["name"] == "test agi_distributor")
    assert pytest_launch["module"] == "pytest"
    assert pytest_launch["args"] == [
        "-k",
        "status and not slow",
        "-q",
        "--maxfail=1",
        "${workspaceFolder}/src/agilab/core/test/test_agi_distributor.py",
    ]


def test_generate_vscode_configs_writes_tasks_and_launch_json(tmp_path: Path) -> None:
    tasks_out = tmp_path / ".vscode" / "tasks.json"
    launch_out = tmp_path / ".vscode" / "launch.json"
    tasks_payload = {
        "version": "2.0.0",
        "tasks": [{"label": "demo", "type": "shell", "command": "echo demo"}],
    }
    launch_payload = {
        "version": "0.2.0",
        "configurations": [{"name": "demo", "type": "debugpy", "request": "launch", "program": "demo.py"}],
    }

    generate_vscode_tasks.write_json(tasks_payload, tasks_out)
    generate_vscode_tasks.write_json(launch_payload, launch_out)

    assert json.loads(tasks_out.read_text(encoding="utf-8")) == tasks_payload
    assert json.loads(launch_out.read_text(encoding="utf-8")) == launch_payload
