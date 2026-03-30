from __future__ import annotations

import importlib
from pathlib import Path
import sys
from types import SimpleNamespace

import tomllib
import types


def _import_agilab_module(module_name: str):
    src_root = Path(__file__).resolve().parents[1] / "src"
    package_root = src_root / "agilab"
    src_root_str = str(src_root)
    package_root_str = str(package_root)
    if src_root_str not in sys.path:
        sys.path.insert(0, src_root_str)
    pkg = sys.modules.get("agilab")
    if pkg is None or not hasattr(pkg, "__path__"):
        pkg = types.ModuleType("agilab")
        pkg.__path__ = [package_root_str]
        sys.modules["agilab"] = pkg
    else:
        package_path = list(pkg.__path__)
        if package_root_str not in package_path:
            pkg.__path__ = [package_root_str, *package_path]
    importlib.invalidate_caches()
    return importlib.import_module(module_name)


pipeline_steps = _import_agilab_module("agilab.pipeline_steps")


def test_normalize_runtime_path_prefers_existing_app(monkeypatch, tmp_path):
    apps_root = tmp_path / "apps"
    apps_root.mkdir()
    app_dir = apps_root / "flight_project"
    app_dir.mkdir()

    fake_st = SimpleNamespace(session_state={})
    monkeypatch.setattr(pipeline_steps, "st", fake_st)

    env = SimpleNamespace(apps_path=apps_root)
    normalized = pipeline_steps.normalize_runtime_path("flight_project", env=env)

    assert normalized == str(app_dir)


def test_module_key_normalization_and_sequence_roundtrip(monkeypatch, tmp_path):
    export_root = tmp_path / "export"
    module_dir = export_root / "flight_project"
    module_dir.mkdir(parents=True)
    steps_file = tmp_path / "lab_steps.toml"
    absolute_key = str(module_dir.resolve())
    steps_file.write_text(
        f'[[ "{absolute_key}" ]]\n'
        'Q = "First step"\n'
        'C = "print(1)"\n',
        encoding="utf-8",
    )

    fake_st = SimpleNamespace(session_state={})
    monkeypatch.setattr(pipeline_steps, "st", fake_st)
    env = SimpleNamespace(home_abs=tmp_path, AGILAB_EXPORT_ABS=export_root, envars={})

    pipeline_steps.ensure_primary_module_key(module_dir, steps_file, env=env)
    pipeline_steps.persist_sequence_preferences(module_dir, steps_file, [2, 0, 1], env=env)

    data = tomllib.loads(steps_file.read_text(encoding="utf-8"))
    assert "flight_project" in data
    assert absolute_key not in data
    assert pipeline_steps.load_sequence_preferences(module_dir, steps_file, env=env) == [2, 0, 1]


def test_get_available_virtualenvs_discovers_direct_and_nested_envs(monkeypatch, tmp_path):
    active_app = tmp_path / "apps" / "flight_project"
    apps_path = tmp_path / "apps"
    runenv = tmp_path / "runenv"
    direct = active_app / ".venv"
    nested = runenv / "worker_a"
    nested_venv = nested / ".venv"
    for path in (direct, nested_venv):
        path.mkdir(parents=True)
        (path / "pyvenv.cfg").write_text("home = /tmp/python\n", encoding="utf-8")

    env = SimpleNamespace(
        active_app=active_app,
        apps_path=apps_path,
        runenv=runenv,
        wenv_abs="",
        agi_env="",
    )

    pipeline_steps._cached_virtualenvs.clear()
    discovered = pipeline_steps.get_available_virtualenvs(env)

    assert direct.resolve() in discovered
    assert nested_venv.resolve() in discovered


def test_orchestrate_lock_helpers_cover_bool_and_question_forms():
    locked = {
        pipeline_steps.ORCHESTRATE_LOCKED_STEP_KEY: "yes",
        pipeline_steps.ORCHESTRATE_LOCKED_SOURCE_KEY: "AGI_run.py",
    }
    inferred = {"Q": "Imported snippet: generated_step.py"}

    assert pipeline_steps.is_orchestrate_locked_step(locked) is True
    assert pipeline_steps.orchestrate_snippet_source(locked) == "AGI_run.py"
    assert pipeline_steps.is_orchestrate_locked_step(inferred) is True
    assert pipeline_steps.orchestrate_snippet_source(inferred) == "generated_step.py"


def test_prune_invalid_entries_keeps_requested_index():
    entries = [
        {"Q": "Visible"},
        {"Q": "", "C": ""},
        {"C": "print('ok')"},
    ]

    pruned = pipeline_steps.prune_invalid_entries(entries, keep_index=1)

    assert pruned == entries


def test_upgrade_exported_steps_rewrites_legacy_apps_dir_scaffold(monkeypatch, tmp_path):
    export_root = tmp_path / "export"
    module_dir = export_root / "sb3_trainer_project"
    module_dir.mkdir(parents=True)
    steps_file = tmp_path / "lab_steps.toml"
    steps_file.write_text(
        '[[sb3_trainer_project]]\n'
        'Q = "Legacy step"\n'
        'C = """from pathlib import Path\n'
        'import agilab\n'
        'from agi_env import AgiEnv\n'
        '\n'
        'APP = "sb3_trainer_project"\n'
        'APPS_DIR = Path(agilab.__file__).resolve().parent / "apps"\n'
        'PROJECT_SRC = APPS_DIR / APP / "src"\n'
        'env = AgiEnv(apps_dir=APPS_DIR, app=APP, verbose=1)\n'
        '"""\n',
        encoding="utf-8",
    )

    fake_st = SimpleNamespace(session_state={})
    monkeypatch.setattr(pipeline_steps, "st", fake_st)
    env = SimpleNamespace(home_abs=tmp_path, AGILAB_EXPORT_ABS=export_root, envars={})

    changed = pipeline_steps.upgrade_exported_steps(module_dir, steps_file, env=env)

    assert changed is True
    data = tomllib.loads(steps_file.read_text(encoding="utf-8"))
    code = data["sb3_trainer_project"][0]["C"]
    assert "import agilab" not in code
    assert "APPS_DIR" not in code
    assert "APPS_ROOT" not in code
    assert "apps_dir=APPS_DIR" not in code
    assert "import os" in code
    assert 'APPS_PATH_RAW = os.environ.get("APPS_PATH", "").strip()' in code
    assert 'APPS_PATH = Path(APPS_PATH_RAW).expanduser()' in code
    assert 'APP_ROOT = APPS_PATH / APP' in code
    assert 'PROJECT_SRC = APP_ROOT / "src"' in code
    assert "AgiEnv(apps_path=APPS_PATH, app=APP, verbose=1)" in code


def test_upgrade_exported_steps_rewrites_parenthesized_apps_dir_and_runtime(monkeypatch, tmp_path):
    export_root = tmp_path / "export"
    module_dir = export_root / "sb3_trainer_project"
    module_dir.mkdir(parents=True)
    steps_file = tmp_path / "lab_steps.toml"
    steps_file.write_text(
        '[[sb3_trainer_project]]\n'
        'R = "agi.install"\n'
        'E = "Refresh worker before running."\n'
        'C = """import asyncio\n'
        'from pathlib import Path\n'
        'from agi_cluster.agi_distributor import AGI\n'
        'from agi_env import AgiEnv\n'
        '\n'
        'APP = "flight_trajectory_project"\n'
        'APPS_DIR = (Path(agilab.__file__).resolve().parent / "apps").resolve()\n'
        '\n'
        'async def main():\n'
        '    env = AgiEnv(apps_path=APPS_PATH, app=APP, verbose=1)\n'
        '    return await AGI.install(env)\n'
        '"""\n',
        encoding="utf-8",
    )

    fake_st = SimpleNamespace(session_state={})
    monkeypatch.setattr(pipeline_steps, "st", fake_st)
    env = SimpleNamespace(home_abs=tmp_path, AGILAB_EXPORT_ABS=export_root, envars={})

    changed = pipeline_steps.upgrade_exported_steps(module_dir, steps_file, env=env)

    assert changed is True
    data = tomllib.loads(steps_file.read_text(encoding="utf-8"))
    entry = data["sb3_trainer_project"][0]
    assert entry["E"] == "flight_trajectory_project"
    assert "agilab.__file__" not in entry["C"]
    assert "import os" in entry["C"]
    assert 'APPS_PATH_RAW = os.environ.get("APPS_PATH", "").strip()' in entry["C"]
    assert 'APP_ROOT = APPS_PATH / APP' in entry["C"]
    assert entry["C"].index('APP = "flight_trajectory_project"') < entry["C"].index(
        "APP_ROOT = APPS_PATH / APP"
    )


def test_upgrade_legacy_step_runtime_treats_prose_with_slash_as_non_runtime():
    upgraded = pipeline_steps.upgrade_legacy_step_runtime(
        "Refresh network_sim worker before building topology/demands.",
        engine="agi.install",
        app_name="network_sim_project",
    )

    assert upgraded == "network_sim_project"


def test_upgrade_steps_file_rewrites_all_modules(tmp_path):
    steps_file = tmp_path / "lab_steps.toml"
    steps_file.write_text(
        '[[alpha]]\n'
        'C = """from pathlib import Path\nimport agilab\nAPP = "alpha"\nAPPS_DIR = Path(agilab.__file__).resolve().parent / "apps"\n"""\n'
        '[[beta]]\n'
        'C = """print(1)"""\n'
        '[[gamma]]\n'
        'C = """from pathlib import Path\nimport agilab\nfrom agi_env import AgiEnv\nAPP = "gamma"\nAPPS_DIR = Path(agilab.__file__).resolve().parent / "apps"\nenv = AgiEnv(apps_dir=APPS_DIR, app=APP)\n"""\n',
        encoding="utf-8",
    )

    result = pipeline_steps.upgrade_steps_file(steps_file)

    assert result == {"files": 1, "changed_steps": 2, "scanned_steps": 3}
    data = tomllib.loads(steps_file.read_text(encoding="utf-8"))
    assert "import agilab" not in data["alpha"][0]["C"]
    assert "apps_dir=APPS_DIR" not in data["gamma"][0]["C"]
    assert data["beta"][0]["C"] == "print(1)"


def test_upgrade_legacy_step_code_injects_explicit_network_sim_mode():
    legacy = (
        "import asyncio\n"
        "from pathlib import Path\n"
        "from agi_cluster.agi_distributor import AGI\n"
        "from agi_env import AgiEnv\n\n"
        'APP = "network_sim_project"\n\n'
        "async def main():\n"
        "    share = Path('/tmp/share')\n"
        "    res = await AGI.run(\n"
        "        app_env,\n"
        "        mode=4,\n"
        '        data_source="file",\n'
        '        data_in=str(share / "flight_trajectory/pipeline"),\n'
        '        link_results_dir=str(share / "link_sim/pipeline"),\n'
        '        data_out=str(share / "network_sim/pipeline"),\n'
        '        topology_filename="ilp_topology.gml",\n'
        "    )\n"
    )

    upgraded = pipeline_steps.upgrade_legacy_step_code(legacy)

    assert 'demand_source_mode="link_sim_synthetic"' in upgraded


def test_upgrade_legacy_step_code_rewrites_sb3_link_sim_share_inputs():
    code = (
        "import asyncio\n"
        "import os\n"
        "from pathlib import Path\n"
        "import sys\n\n"
        "from agi_cluster.agi_distributor import AGI\n"
        "from agi_env import AgiEnv\n\n"
        'APP = "link_sim_project"\n\n'
        'APPS_PATH_RAW = os.environ.get("APPS_PATH", "").strip()\n\n'
        "APPS_PATH = Path(APPS_PATH_RAW).expanduser()\n\n"
        "APP_ROOT = APPS_PATH / APP\n"
        "async def main():\n"
        "    app_env = AgiEnv(apps_path=APPS_PATH, app=APP, verbose=1)\n"
        "    share = app_env.share_root_path()\n"
        '    dataset_root = share / "link_sim/dataset"\n'
        "    res = await AGI.run(\n"
        "        app_env,\n"
        "        mode=4,\n"
        "        data_in=str(dataset_root),\n"
        '        data_flight="flights",\n'
        '        data_sat="sat",\n'
        '        data_out=str(share / "link_sim/pipeline"),\n'
        '        output_format="parquet",\n'
        "    )\n"
        "    print(res)\n"
        "    return res\n"
    )

    upgraded = pipeline_steps.upgrade_legacy_step_code(code)

    assert 'data_flight=str(share / "flight_trajectory/pipeline")' in upgraded
    assert 'data_sat=str(share / "sat_trajectory/pipeline/Trajectory")' in upgraded
    assert 'data_flight="flights"' not in upgraded
    assert 'data_sat="sat"' not in upgraded


def test_upgrade_legacy_step_code_rewrites_sb3_sat_pipeline_targets():
    code = (
        "import asyncio\n"
        "import os\n"
        "from pathlib import Path\n"
        "import sys\n\n"
        "from agi_cluster.agi_distributor import AGI\n"
        "from agi_env import AgiEnv\n\n"
        'APP = "sat_trajectory_project"\n\n'
        'APPS_PATH_RAW = os.environ.get("APPS_PATH", "").strip()\n\n'
        "APPS_PATH = Path(APPS_PATH_RAW).expanduser()\n\n"
        "APP_ROOT = APPS_PATH / APP\n"
        "async def main():\n"
        "    app_env = AgiEnv(apps_path=APPS_PATH, app=APP, verbose=1)\n"
        "    share = app_env.share_root_path()\n"
        "    res = await AGI.run(\n"
        "        app_env,\n"
        "        mode=15,\n"
        '        data_in=str(share / "sat_trajectory/dataset"),\n'
        "        duration_s=86400,\n"
        "        step_s=1,\n"
        "        number_of_sat=4,\n"
        '        input_TLE="TLE",\n'
        '        input_antenna="antenna_conf.json",\n'
        '        input_sat="sat.json",\n'
        "    )\n"
        "    print(res)\n"
        "    return res\n"
    )

    upgraded = pipeline_steps.upgrade_legacy_step_code(code)

    assert 'data_out=str(share / "sat_trajectory/pipeline")' in upgraded


def test_upgrade_legacy_step_code_rewrites_sb3_satellite_glob():
    code = 'args = {"sat_trajectories_glob": "sat_trajectory/pipeline/*.parquet"}\n'

    upgraded = pipeline_steps.upgrade_legacy_step_code(code)

    assert '"sat_trajectories_glob": "sat_trajectory/pipeline/Trajectory/*.csv"' in upgraded


def test_upgrade_legacy_step_code_rewrites_sb3_flight_globs():
    code = (
        'args = {"trajectories_glob": "flight_trajectory/pipeline/*.parquet"}\n'
        'args = {"trajectories_glob": "flight_trajectory/dataframe/*.csv"}\n'
        'args = {"trajectories_glob": "flight_trajectory/dataframe/flight_simulation/*.parquet"}\n'
    )

    upgraded = pipeline_steps.upgrade_legacy_step_code(code)

    assert 'flight_trajectory/pipeline/*.parquet' not in upgraded
    assert 'flight_trajectory/dataframe/*.csv' not in upgraded
    assert 'flight_trajectory/dataframe/flight_simulation/*.parquet' not in upgraded
    assert upgraded.count('"trajectories_glob": "flight_trajectory/pipeline/*"') == 3


def test_normalize_imported_orchestrate_snippet_rewrites_sb3_ilp_stepper():
    code = (
        "import os\n"
        "from pathlib import Path\n"
        "import sys\n\n"
        "from agi_env import AgiEnv\n\n"
        'APP = "sb3_trainer_project"\n\n'
        'APPS_PATH_RAW = os.environ.get("APPS_PATH", "").strip()\n\n'
        "APPS_PATH = Path(APPS_PATH_RAW).expanduser()\n\n"
        "APP_ROOT = APPS_PATH / APP\n"
        'PROJECT_SRC = APP_ROOT / "src"\n'
        "if str(PROJECT_SRC) not in sys.path:\n"
        "    sys.path.insert(0, str(PROJECT_SRC))\n\n"
        "from sb3_trainer_worker.sb3_trainer_worker import Sb3TrainerWorker\n\n"
        "env = AgiEnv(apps_path=APPS_PATH, app=APP, verbose=1)\n"
        "worker = Sb3TrainerWorker()\n"
        "worker.env = env\n"
        "res = worker.trainer_ilp_stepper({}, None)\n"
        "print(res)\n"
    )

    normalized, engine, runtime = pipeline_steps.normalize_imported_orchestrate_snippet(
        code,
        default_runtime="sb3_trainer_project",
    )

    assert engine == "agi.run"
    assert runtime == "sb3_trainer_project"
    assert 'from agi_cluster.agi_distributor import AGI' in normalized
    assert '"name": "ilp_stepper"' in normalized
    assert '"trajectories_glob": "flight_trajectory/pipeline/*"' in normalized
    assert '"sat_trajectories_glob": "sat_trajectory/pipeline/Trajectory/*.csv"' in normalized
    assert "Sb3TrainerWorker" not in normalized


def test_normalize_imported_orchestrate_snippet_marks_network_summary_runpy():
    code = (
        "import os\n"
        "import pandas as pd\n"
        "from agi_env import AgiEnv\n"
        'SUMMARY_PARQUET = DATA_ROOT / "link_level_summary.parquet"\n'
        "df = pd.read_parquet(path)\n"
    )

    normalized, engine, runtime = pipeline_steps.normalize_imported_orchestrate_snippet(
        code,
        default_runtime="network_sim_project",
    )

    assert normalized == code
    assert engine == "runpy"
    assert runtime == ""
