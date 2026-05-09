from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


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
