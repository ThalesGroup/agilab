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


pipeline_stages = _import_agilab_module("agilab.pipeline_stages")


def test_normalize_runtime_path_prefers_existing_app(monkeypatch, tmp_path):
    apps_root = tmp_path / "apps"
    apps_root.mkdir()
    app_dir = apps_root / "flight_telemetry_project"
    app_dir.mkdir()

    fake_st = SimpleNamespace(session_state={})
    monkeypatch.setattr(pipeline_stages, "st", fake_st)

    env = SimpleNamespace(apps_path=apps_root)
    normalized = pipeline_stages.normalize_runtime_path("flight_telemetry_project", env=env)

    assert normalized == str(app_dir)


def test_module_key_normalization_and_sequence_roundtrip(monkeypatch, tmp_path):
    export_root = tmp_path / "export"
    module_dir = export_root / "flight_telemetry_project"
    module_dir.mkdir(parents=True)
    stages_file = tmp_path / "lab_stages.toml"
    absolute_key = str(module_dir.resolve())
    stages_file.write_text(
        f'[[ "{absolute_key}" ]]\n'
        'Q = "First stage"\n'
        'C = "print(1)"\n',
        encoding="utf-8",
    )

    fake_st = SimpleNamespace(session_state={})
    monkeypatch.setattr(pipeline_stages, "st", fake_st)
    env = SimpleNamespace(home_abs=tmp_path, AGILAB_EXPORT_ABS=export_root, envars={})

    pipeline_stages.ensure_primary_module_key(module_dir, stages_file, env=env)
    pipeline_stages.persist_sequence_preferences(module_dir, stages_file, [2, 0, 1], env=env)

    data = tomllib.loads(stages_file.read_text(encoding="utf-8"))
    assert "flight_telemetry_project" in data
    assert absolute_key not in data
    assert data["__meta__"]["schema"] == "agilab.lab_stages.v1"
    assert data["__meta__"]["version"] == 1
    assert pipeline_stages.load_sequence_preferences(module_dir, stages_file, env=env) == [2, 0, 1]


def test_restore_missing_export_stages_from_project_source(monkeypatch, tmp_path):
    apps_root = tmp_path / "apps"
    source_app = apps_root / "sb3_trainer_project"
    source_app.mkdir(parents=True)
    source_stages = source_app / "lab_stages.toml"
    source_stages.write_text(
        'sb3_trainer_project = [{ Q = "Train policy", C = "print(1)" }]\n',
        encoding="utf-8",
    )
    export_root = tmp_path / "export"
    target_stages = export_root / "sb3_trainer" / "lab_stages.toml"
    fake_st = SimpleNamespace(session_state={})
    monkeypatch.setattr(pipeline_stages, "st", fake_st)
    env = SimpleNamespace(
        home_abs=tmp_path,
        AGILAB_EXPORT_ABS=export_root,
        envars={},
        apps_path=apps_root,
        active_app=source_app,
        target="sb3_trainer_project",
        app="sb3_trainer_project",
    )

    restored = pipeline_stages.restore_missing_export_stages(Path("sb3_trainer"), target_stages, env=env)

    assert restored == source_stages
    data = tomllib.loads(target_stages.read_text(encoding="utf-8"))
    assert data["sb3_trainer"][0]["Q"] == "Train policy"
    assert "sb3_trainer_project" not in data
    assert data["__meta__"]["schema"] == "agilab.lab_stages.v1"
    assert data["__meta__"]["version"] == 1


def test_restore_missing_export_stages_handles_empty_file(monkeypatch, tmp_path):
    apps_root = tmp_path / "apps"
    source_app = apps_root / "flight_telemetry_project"
    source_app.mkdir(parents=True)
    source_stages = source_app / "lab_stages.toml"
    source_stages.write_text('flight = [{ Q = "Run", C = "print(1)" }]\n', encoding="utf-8")
    export_root = tmp_path / "export"
    target_stages = export_root / "flight" / "lab_stages.toml"
    target_stages.parent.mkdir(parents=True)
    target_stages.write_text("", encoding="utf-8")
    fake_st = SimpleNamespace(session_state={})
    monkeypatch.setattr(pipeline_stages, "st", fake_st)
    env = SimpleNamespace(
        home_abs=tmp_path,
        AGILAB_EXPORT_ABS=export_root,
        envars={},
        apps_path=apps_root,
        active_app=source_app,
        target="flight_telemetry_project",
        app="flight_telemetry_project",
    )

    restored = pipeline_stages.restore_missing_export_stages(Path("flight"), target_stages, env=env)

    assert restored == source_stages
    data = tomllib.loads(target_stages.read_text(encoding="utf-8"))
    assert data["flight"][0]["Q"] == "Run"
    assert data["__meta__"]["schema"] == "agilab.lab_stages.v1"


def test_restore_missing_export_stages_does_not_overwrite_existing_export(monkeypatch, tmp_path):
    apps_root = tmp_path / "apps"
    source_app = apps_root / "flight_telemetry_project"
    source_app.mkdir(parents=True)
    (source_app / "lab_stages.toml").write_text(
        'flight = [{ Q = "Source", C = "print(1)" }]\n',
        encoding="utf-8",
    )
    export_root = tmp_path / "export"
    target_stages = export_root / "flight" / "lab_stages.toml"
    target_stages.parent.mkdir(parents=True)
    target_stages.write_text('flight = [{ Q = "User edit", C = "print(2)" }]\n', encoding="utf-8")
    original = target_stages.read_text(encoding="utf-8")
    fake_st = SimpleNamespace(session_state={})
    monkeypatch.setattr(pipeline_stages, "st", fake_st)
    env = SimpleNamespace(
        home_abs=tmp_path,
        AGILAB_EXPORT_ABS=export_root,
        envars={},
        apps_path=apps_root,
        active_app=source_app,
        target="flight_telemetry_project",
        app="flight_telemetry_project",
    )

    restored = pipeline_stages.restore_missing_export_stages(Path("flight"), target_stages, env=env)

    assert restored is None
    assert target_stages.read_text(encoding="utf-8") == original


def test_get_available_virtualenvs_discovers_direct_and_nested_envs(monkeypatch, tmp_path):
    active_app = tmp_path / "apps" / "flight_telemetry_project"
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

    pipeline_stages._cached_virtualenvs.clear()
    discovered = pipeline_stages.get_available_virtualenvs(env)

    assert direct.resolve() in discovered
    assert nested_venv.resolve() in discovered


def test_orchestrate_lock_helpers_cover_bool_and_question_forms():
    locked = {
        pipeline_stages.ORCHESTRATE_LOCKED_STAGE_KEY: "yes",
        pipeline_stages.ORCHESTRATE_LOCKED_SOURCE_KEY: "AGI_run.py",
    }
    inferred = {"Q": "Imported snippet: generated_stage.py"}

    assert pipeline_stages.is_orchestrate_locked_stage(locked) is True
    assert pipeline_stages.orchestrate_snippet_source(locked) == "AGI_run.py"
    assert pipeline_stages.is_orchestrate_locked_stage(inferred) is True
    assert pipeline_stages.orchestrate_snippet_source(inferred) == "generated_stage.py"


def test_stage_project_name_prefers_app_name_from_snippet():
    entry = {
        "C": (
            "import asyncio\n"
            'APP = "sb3_trainer_project"\n'
            "print('run')\n"
        ),
        "E": "/tmp/other_project",
    }

    assert pipeline_stages.stage_project_name(entry) == "sb3_trainer_project"


def test_stage_label_for_multiselect_includes_project_name_from_runtime(monkeypatch, tmp_path):
    apps_root = tmp_path / "apps"
    apps_root.mkdir()
    network_sim = apps_root / "network_sim_project"
    network_sim.mkdir()

    fake_st = SimpleNamespace(session_state={})
    monkeypatch.setattr(pipeline_stages, "st", fake_st)
    env = SimpleNamespace(apps_path=apps_root)
    entry = {"Q": "Build topology and demands", "E": "network_sim_project"}

    label = pipeline_stages.stage_label_for_multiselect(2, entry, env=env)

    assert label == "Stage 3: [network_sim_project] Build topology and demands"


def test_prune_invalid_entries_keeps_requested_index():
    entries = [
        {"Q": "Visible"},
        {"Q": "", "C": ""},
        {"C": "print('ok')"},
    ]

    pruned = pipeline_stages.prune_invalid_entries(entries, keep_index=1)

    assert pruned == entries


def test_upgrade_exported_stages_is_noop_and_preserves_file(monkeypatch, tmp_path):
    export_root = tmp_path / "export"
    module_dir = export_root / "sb3_trainer_project"
    module_dir.mkdir(parents=True)
    stages_file = tmp_path / "lab_stages.toml"
    original = (
        '[[sb3_trainer_project]]\n'
        'Q = "Legacy stage"\n'
        'C = """from pathlib import Path\n'
        'import agilab\n'
        'from agi_env import AgiEnv\n'
        '\n'
        'APP = "sb3_trainer_project"\n'
        'APPS_DIR = Path(agilab.__file__).resolve().parent / "apps"\n'
        'PROJECT_SRC = APPS_DIR / APP / "src"\n'
        'env = AgiEnv(apps_dir=APPS_DIR, app=APP, verbose=1)\n'
        '"""\n'
    )
    stages_file.write_text(original, encoding="utf-8")

    fake_st = SimpleNamespace(session_state={})
    monkeypatch.setattr(pipeline_stages, "st", fake_st)
    env = SimpleNamespace(home_abs=tmp_path, AGILAB_EXPORT_ABS=export_root, envars={})

    changed = pipeline_stages.upgrade_exported_stages(module_dir, stages_file, env=env)

    assert changed is False
    assert stages_file.read_text(encoding="utf-8") == original


def test_upgrade_stages_file_reports_scan_without_rewriting(tmp_path):
    stages_file = tmp_path / "lab_stages.toml"
    original = (
        '[[alpha]]\n'
        'C = """from pathlib import Path\nimport agilab\nAPP = "alpha"\nAPPS_DIR = Path(agilab.__file__).resolve().parent / "apps"\n"""\n'
        '[[beta]]\n'
        'C = """print(1)"""\n'
    )
    stages_file.write_text(original, encoding="utf-8")

    result = pipeline_stages.upgrade_stages_file(stages_file)

    assert result == {"files": 1, "changed_stages": 0, "scanned_stages": 2}
    assert stages_file.read_text(encoding="utf-8") == original


def test_upgrade_legacy_helpers_are_noop():
    code = (
        "from pathlib import Path\n"
        "import agilab\n"
        'APP = "network_sim_project"\n'
        'APPS_DIR = Path(agilab.__file__).resolve().parent / "apps"\n'
    )
    assert pipeline_stages.upgrade_legacy_stage_code(code) == code
    assert pipeline_stages.upgrade_legacy_stage_runtime(
        "Refresh network_sim worker before building topology/demands.",
        engine="agi.install",
        app_name="network_sim_project",
    ) == "Refresh network_sim worker before building topology/demands."
    assert pipeline_stages.upgrade_legacy_stage_entry({"C": code, "E": "legacy text", "R": "agi.run"}) is False


def test_legacy_agi_run_detector_flags_removed_keyword_api_only():
    legacy_code = (
        "from agi_cluster.agi_distributor import AGI\n"
        'APP = "flight_trajectory_project"\n'
        "async def main(app_env):\n"
        "    return await AGI.run(app_env, mode=4, data_in='in', data_out='out')\n"
    )
    wrapper_code = (
        "from agi_cluster.agi_distributor import AGI, RunRequest\n"
        "async def agi_run(app_env, **kwargs):\n"
        "    request = RunRequest(params=kwargs)\n"
        "    return await AGI.run(app_env, request=request)\n"
        "res = await agi_run(app_env, mode=4, data_in='in')\n"
    )
    positional_request_code = (
        "from agi_cluster.agi_distributor import AGI, RunRequest\n"
        "request = RunRequest(mode=4)\n"
        "res = await AGI.run(app_env, request)\n"
    )
    kwargs_code = "res = await AGI.run(app_env, **payload)\n"

    legacy_lines = pipeline_stages.legacy_agi_run_call_lines(legacy_code)

    assert legacy_lines == [4]
    assert pipeline_stages.legacy_agi_run_call_lines(wrapper_code) == []
    assert pipeline_stages.legacy_agi_run_call_lines(positional_request_code) == []
    assert pipeline_stages.legacy_agi_run_call_lines(kwargs_code) == [1]


def test_find_legacy_agi_run_stages_reports_selected_stage_metadata():
    stages = [
        {"Q": "Install", "C": "print('ok')"},
        {
            "Q": "Generate flight trajectories",
            "C": (
                'APP = "flight_trajectory_project"\n'
                "async def main(app_env):\n"
                "    return await AGI.run(app_env, mode=4)\n"
            ),
        },
    ]

    stale = pipeline_stages.find_legacy_agi_run_stages(stages, [1])

    assert stale == [
        {
            "index": 1,
            "stage": 2,
            "line": 3,
            "lines": [3],
            "summary": "Generate flight trajectories",
            "project": "flight_trajectory_project",
        }
    ]


def test_normalize_imported_orchestrate_snippet_keeps_sb3_worker_snippet_unchanged():
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

    normalized, engine, runtime = pipeline_stages.normalize_imported_orchestrate_snippet(
        code,
        default_runtime="sb3_trainer_project",
    )

    assert normalized == code
    assert engine == "runpy"
    assert runtime == "sb3_trainer_project"


def test_normalize_imported_orchestrate_snippet_infers_agi_runtime_without_rewrite():
    code = (
        "import asyncio\n"
        "from agi_cluster.agi_distributor import AGI\n"
        "from agi_env import AgiEnv\n"
        'APP = "flight_trajectory_project"\n'
    )

    normalized, engine, runtime = pipeline_stages.normalize_imported_orchestrate_snippet(
        code,
        default_runtime="network_sim_project",
    )

    assert normalized == code
    assert engine == "agi.run"
    assert runtime == "flight_trajectory_project"


def test_normalize_runtime_path_handles_blank_fallback_and_dot_venv(monkeypatch, tmp_path):
    apps_root = tmp_path / "apps"
    apps_root.mkdir()
    fallback_app = apps_root / "flight_telemetry_project"
    fallback_app.mkdir()
    venv_dir = fallback_app / ".venv"
    venv_dir.mkdir()

    fake_st = SimpleNamespace(session_state={})
    monkeypatch.setattr(pipeline_stages, "st", fake_st)
    env = SimpleNamespace(apps_path=apps_root)

    assert pipeline_stages.normalize_runtime_path("   ", env=env) == ""
    assert pipeline_stages.normalize_runtime_path("nested/flight_telemetry_project", env=env) == str(fallback_app)
    assert pipeline_stages.normalize_runtime_path(venv_dir, env=env) == str(fallback_app)


def test_stage_helpers_and_runtime_reference_edge_cases(monkeypatch):
    fake_st = SimpleNamespace(session_state={})
    monkeypatch.setattr(pipeline_stages, "st", fake_st)

    assert pipeline_stages.stage_label_for_multiselect(0, None) == "Stage 1"

    monkeypatch.setattr(pipeline_stages, "normalize_runtime_path", lambda *_args, **_kwargs: "/")
    assert pipeline_stages.stage_project_name({"E": "ignored"}) == ""

    assert pipeline_stages.looks_like_runtime_reference("") is False
    assert pipeline_stages.looks_like_runtime_reference(r"C:\work\demo") is True
    assert pipeline_stages.looks_like_runtime_reference("folder/sub") is True
    assert pipeline_stages.looks_like_runtime_reference(".venv") is True
    assert pipeline_stages.looks_like_runtime_reference("flight_telemetry_project") is True
    assert pipeline_stages.is_runnable_stage({}) is False
    assert pipeline_stages.looks_like_stage("bad") is False
    assert pipeline_stages.is_orchestrate_locked_stage(None) is False
    assert pipeline_stages.orchestrate_snippet_source(None) == ""


def test_upgrade_stages_file_and_pipeline_export_root_edge_paths(monkeypatch, tmp_path):
    missing_result = pipeline_stages.upgrade_stages_file(tmp_path / "missing.toml")
    assert missing_result == {"files": 0, "changed_stages": 0, "scanned_stages": 0}

    bad_file = tmp_path / "bad.toml"
    bad_file.write_text("[", encoding="utf-8")
    assert pipeline_stages.upgrade_stages_file(bad_file) == {"files": 0, "changed_stages": 0, "scanned_stages": 0}

    fake_st = SimpleNamespace(session_state={"AGI_EXPORT_DIR": "."})
    monkeypatch.setattr(pipeline_stages, "st", fake_st)
    env = SimpleNamespace(home_abs=tmp_path, AGILAB_EXPORT_ABS=None, envars={"AGI_EXPORT_DIR": ""})
    assert pipeline_stages.pipeline_export_root(env) == (tmp_path / "export").resolve()


def test_pipeline_stages_cover_runtime_name_and_hidden_entry_edges(monkeypatch, tmp_path):
    class BrokenRuntime:
        def __fspath__(self):
            raise RuntimeError("boom")

        def __str__(self):
            return str(tmp_path / "demo_project" / ".venv")

    monkeypatch.setattr(pipeline_stages, "normalize_runtime_path", lambda *_args, **_kwargs: BrokenRuntime())
    assert pipeline_stages.stage_project_name({"E": "ignored"}) == "demo_project"
    assert pipeline_stages.stage_label_for_multiselect(0, {"E": "ignored"}) == "Stage 1: [demo_project]"
    assert pipeline_stages.is_displayable_stage({}) is False


def test_pipeline_stages_cover_runtime_reference_false_and_path_parse_fallback(monkeypatch):
    original_path = pipeline_stages.Path

    class BrokenPath:
        def __init__(self, *_args, **_kwargs):
            pass

        def expanduser(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(pipeline_stages, "Path", BrokenPath)
    assert pipeline_stages.normalize_runtime_path("flight_telemetry_project") == "flight_telemetry_project"
    monkeypatch.setattr(pipeline_stages, "Path", original_path)
    assert pipeline_stages.looks_like_runtime_reference("flight") is False


def test_upgrade_stages_file_and_virtualenv_helpers_cover_guard_paths(monkeypatch, tmp_path):
    stages_file = tmp_path / "lab_stages.toml"
    stages_file.write_text(
        'alpha = ["bad", { Q = "Visible" }]\n[__meta__]\nversion = 1\n',
        encoding="utf-8",
    )
    assert pipeline_stages.upgrade_stages_file(stages_file) == {"files": 1, "changed_stages": 0, "scanned_stages": 1}

    class BrokenExpand:
        def expanduser(self):
            raise RuntimeError("boom")

        def exists(self):
            return False

        def is_dir(self):
            return False

    assert pipeline_stages._normalize_venv_root(BrokenExpand()) is None

    venv_root = tmp_path / "runtime"
    venv_root.mkdir()
    (venv_root / "pyvenv.cfg").write_text("home = /tmp/python\n", encoding="utf-8")
    original_resolve = pipeline_stages.Path.resolve

    def _raise_for_runtime(self, *args, **kwargs):
        if self == venv_root:
            raise RuntimeError("boom")
        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(pipeline_stages.Path, "resolve", _raise_for_runtime, raising=False)
    assert pipeline_stages._normalize_venv_root(venv_root) == venv_root

    monkeypatch.setattr(pipeline_stages.Path, "resolve", original_resolve, raising=False)
    assert list(pipeline_stages._iter_venv_roots(venv_root)) == [venv_root.resolve()]


def test_pipeline_stages_cover_module_key_resolve_failures_and_meta_skip(monkeypatch, tmp_path):
    export_root = tmp_path / "export"
    module_abs = export_root / "flight_telemetry_project"
    module_abs.mkdir(parents=True)
    env = SimpleNamespace(home_abs=tmp_path, AGILAB_EXPORT_ABS=export_root, envars={})
    fake_st = SimpleNamespace(session_state={"env": env})
    monkeypatch.setattr(pipeline_stages, "st", fake_st)

    original_resolve = pipeline_stages.Path.resolve

    def _raise_for_absolute_module(self, *args, **kwargs):
        if self == module_abs:
            raise RuntimeError("abs resolve boom")
        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(pipeline_stages.Path, "resolve", _raise_for_absolute_module, raising=False)
    assert pipeline_stages.module_keys(module_abs, env=env)[0] == "flight_telemetry_project"

    stages_file = tmp_path / "absolute-key.toml"
    stages_file.write_text(
        f'[__meta__]\nversion = 1\n[["{module_abs}"]]\nQ = "stage"\n',
        encoding="utf-8",
    )

    relative_module = pipeline_stages.Path("flight_telemetry_project")

    def _raise_for_relative_module(self, *args, **kwargs):
        if self == relative_module:
            raise RuntimeError("relative resolve boom")
        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(pipeline_stages.Path, "resolve", _raise_for_relative_module, raising=False)
    pipeline_stages.ensure_primary_module_key("flight_telemetry_project", stages_file, env=env)

    data = tomllib.loads(stages_file.read_text(encoding="utf-8"))
    assert "__meta__" in data
    assert str(module_abs) in data


def test_ensure_primary_module_key_and_sequence_helpers_cover_guard_paths(monkeypatch, tmp_path):
    export_root = tmp_path / "export"
    module_path = export_root / "flight_telemetry_project"
    module_path.mkdir(parents=True)
    env = SimpleNamespace(home_abs=tmp_path, AGILAB_EXPORT_ABS=export_root, envars={})
    fake_st = SimpleNamespace(session_state={"env": env})
    monkeypatch.setattr(pipeline_stages, "st", fake_st)

    missing_stages = tmp_path / "missing.toml"
    pipeline_stages.ensure_primary_module_key(module_path, missing_stages, env=env)

    bad_stages = tmp_path / "bad.toml"
    bad_stages.write_text("[", encoding="utf-8")
    pipeline_stages.ensure_primary_module_key(module_path, bad_stages, env=env)

    no_match_stages = tmp_path / "no-match.toml"
    no_match_stages.write_text('[[other_project]]\nQ = "stage"\n', encoding="utf-8")
    pipeline_stages.ensure_primary_module_key(module_path, no_match_stages, env=env)
    assert "other_project" in no_match_stages.read_text(encoding="utf-8")

    primary_stages = tmp_path / "primary.toml"
    primary_stages.write_text('[[flight_telemetry_project]]\nQ = "stage"\n', encoding="utf-8")
    pipeline_stages.ensure_primary_module_key(module_path, primary_stages, env=env)
    assert "flight_telemetry_project" in primary_stages.read_text(encoding="utf-8")

    warnings: list[str] = []
    monkeypatch.setattr(pipeline_stages.logger, "warning", lambda message, *args: warnings.append(str(message)))
    monkeypatch.setattr(pipeline_stages.tomli_w, "dump", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("write boom")))

    merge_stages = tmp_path / "merge.toml"
    merge_stages.write_text(
        '[[flight_telemetry_project]]\nQ = "best"\n'
        f'[["{module_path}"]]\nQ = "other"\n',
        encoding="utf-8",
    )
    pipeline_stages.ensure_primary_module_key(module_path, merge_stages, env=env)

    assert any("Failed to normalize module keys" in warning for warning in warnings)

    assert pipeline_stages.load_sequence_preferences(module_path, tmp_path / "missing-seq.toml", env=env) == []

    bad_seq = tmp_path / "bad-seq.toml"
    bad_seq.write_text("[", encoding="utf-8")
    assert pipeline_stages.load_sequence_preferences(module_path, bad_seq, env=env) == []

    seq_stages = tmp_path / "seq.toml"
    seq_stages.write_text('[__meta__]\nflight_telemetry_project__sequence = "bad"\n', encoding="utf-8")
    assert pipeline_stages.load_sequence_preferences(module_path, seq_stages, env=env) == []


def test_ensure_primary_module_key_ignores_candidate_resolve_failures(monkeypatch, tmp_path):
    export_root = tmp_path / "export"
    module_path = export_root / "flight_telemetry_project"
    module_path.mkdir(parents=True)
    env = SimpleNamespace(home_abs=tmp_path, AGILAB_EXPORT_ABS=export_root, envars={})
    fake_st = SimpleNamespace(session_state={"env": env})
    monkeypatch.setattr(pipeline_stages, "st", fake_st)

    stages_file = tmp_path / "bad-candidate.toml"
    stages_file.write_text('[[bad_entry]]\nQ = "stage"\n', encoding="utf-8")

    original_resolve = pipeline_stages.Path.resolve

    def _patched_resolve(self, *args, **kwargs):
        if self == export_root / "bad_entry":
            raise RuntimeError("candidate resolve boom")
        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(pipeline_stages.Path, "resolve", _patched_resolve, raising=False)
    pipeline_stages.ensure_primary_module_key(module_path, stages_file, env=env)

    assert "bad_entry" in stages_file.read_text(encoding="utf-8")


def test_persist_sequence_preferences_and_venv_helpers_cover_failures(monkeypatch, tmp_path):
    errors: list[str] = []
    monkeypatch.setattr(pipeline_stages.logger, "error", lambda message, *args: errors.append(str(message)))

    bad_stages = tmp_path / "bad-sequence-write.toml"
    bad_stages.write_text("[", encoding="utf-8")
    pipeline_stages.persist_sequence_preferences(tmp_path / "flight_telemetry_project", bad_stages, [1, 2, 3])
    assert any("Failed to load stages while saving sequence metadata" in message for message in errors)

    errors.clear()
    monkeypatch.setattr(pipeline_stages.tomli_w, "dump", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("persist boom")))
    pipeline_stages.persist_sequence_preferences(tmp_path / "flight_telemetry_project", tmp_path / "new-sequence.toml", [1, 2, 3])
    assert any("Failed to persist execution sequence" in message for message in errors)

    original_iterdir = pipeline_stages.Path.iterdir

    def _broken_iterdir(self):
        if self == tmp_path / "broken":
            raise OSError("iterdir boom")
        return original_iterdir(self)

    monkeypatch.setattr(pipeline_stages.Path, "iterdir", _broken_iterdir)
    assert list(pipeline_stages._iter_venv_roots(tmp_path / "broken")) == []
    assert pipeline_stages._cached_virtualenvs(("", str(tmp_path / "missing-dir"))) == []


def test_pipeline_stages_helper_utilities_cover_runtime_and_summary_branches(monkeypatch, tmp_path):
    fake_st = SimpleNamespace(session_state={"AGI_EXPORT_DIR": "relative-export"})
    monkeypatch.setattr(pipeline_stages, "st", fake_st)

    env = SimpleNamespace(
        home_abs=tmp_path,
        AGILAB_EXPORT_ABS=tmp_path,
        envars={"AGI_EXPORT_DIR": ""},
    )

    assert pipeline_stages.normalize_imported_orchestrate_snippet(None, default_runtime="demo") == (None, "agi.run", "demo")
    assert pipeline_stages._convert_paths_to_strings({"path": Path("demo"), "items": [Path("/tmp/x")]}) == {
        "path": "demo",
        "items": ["/tmp/x"],
    }
    assert pipeline_stages.stage_summary({"Q": "   long   question text   "}, width=20) == "long question text"
    assert pipeline_stages.stage_summary({"C": "print('hello world')\nprint('again')"}, width=18) == "print('hello…"
    assert pipeline_stages.stage_button_label(1, 7, {"Q": ""}) == "2. Stage 8"
    assert pipeline_stages.looks_like_runtime_reference("/tmp/demo") is True
    assert pipeline_stages.looks_like_runtime_reference("demo_project") is True
    assert pipeline_stages.looks_like_runtime_reference("not a runtime") is False
    assert pipeline_stages.pipeline_export_root(env) == (tmp_path / "export")
    assert pipeline_stages.pipeline_export_root(SimpleNamespace(home_abs=tmp_path, AGILAB_EXPORT_ABS=None, envars={})) == (
        tmp_path / "relative-export"
    )


def test_pipeline_stages_module_keys_and_sequence_error_branches(monkeypatch, tmp_path):
    fake_st = SimpleNamespace(session_state={})
    monkeypatch.setattr(pipeline_stages, "st", fake_st)

    export_root = tmp_path / "export"
    export_root.mkdir()
    env = SimpleNamespace(home_abs=tmp_path, AGILAB_EXPORT_ABS=export_root, envars={})
    module_dir = export_root / "demo_project"
    module_dir.mkdir()

    keys = pipeline_stages.module_keys(module_dir, env=env)
    assert keys[0] == "demo_project"
    assert keys[1] == str(module_dir)

    missing = pipeline_stages.load_sequence_preferences(module_dir, tmp_path / "missing.toml", env=env)
    assert missing == []

    broken_file = tmp_path / "broken.toml"
    broken_file.write_text("[[broken]\n", encoding="utf-8")
    assert pipeline_stages.load_sequence_preferences(module_dir, broken_file, env=env) == []

    same_sequence_file = tmp_path / "same_sequence.toml"
    same_sequence_file.write_text(
        '[__meta__]\n"demo_project__sequence" = [0, 2]\n',
        encoding="utf-8",
    )
    before = same_sequence_file.read_text(encoding="utf-8")
    pipeline_stages.persist_sequence_preferences(module_dir, same_sequence_file, [0, 2], env=env)
    assert same_sequence_file.read_text(encoding="utf-8") == before


def test_pipeline_stages_virtualenv_helpers_and_guidance(tmp_path):
    env_root = tmp_path / "env_a"
    env_root.mkdir()
    (env_root / "pyvenv.cfg").write_text("home=/tmp/python\n", encoding="utf-8")
    child = tmp_path / "child"
    child.mkdir()
    (child / ".venv").mkdir()
    ((child / ".venv") / "pyvenv.cfg").write_text("home=/tmp/python\n", encoding="utf-8")

    roots = list(pipeline_stages._iter_venv_roots(tmp_path))

    assert env_root.resolve() in roots
    assert (child / ".venv").resolve() in roots
    assert pipeline_stages._normalize_venv_root(tmp_path / "missing") is None
    assert "Run INSTALL" in pipeline_stages.snippet_source_guidance(False, "flight_telemetry_project")
    assert "Snippets are refreshed" in pipeline_stages.snippet_source_guidance(True, "flight_telemetry_project")


def test_normalize_imported_orchestrate_snippet_keeps_runpy_runtime():
    code = (
        "import os\n"
        "import pandas as pd\n"
        "from agi_env import AgiEnv\n"
        'SUMMARY_PARQUET = DATA_ROOT / "link_level_summary.parquet"\n'
        "df = pd.read_parquet(path)\n"
    )

    normalized, engine, runtime = pipeline_stages.normalize_imported_orchestrate_snippet(
        code,
        default_runtime="network_sim_project",
    )

    assert normalized == code
    assert engine == "runpy"
    assert runtime == "network_sim_project"


def test_pipeline_export_root_and_module_keys_handle_home_fallback(monkeypatch, tmp_path):
    fake_st = SimpleNamespace(session_state={"AGI_EXPORT_DIR": ""})
    monkeypatch.setattr(pipeline_stages, "st", fake_st)
    env = SimpleNamespace(home_abs=tmp_path, AGILAB_EXPORT_ABS=tmp_path, envars={})

    export_root = pipeline_stages.pipeline_export_root(env)
    module_dir = export_root / "network_sim_project"

    assert export_root == (tmp_path / "export")
    assert pipeline_stages.module_keys(module_dir, env=env)[0] == "network_sim_project"


def test_stage_helper_labels_and_runtime_reference_flags():
    entry = {"Q": "  Build topology   and   demands  ", "C": "print('fallback')", "R": "runpy"}

    assert pipeline_stages.stage_summary(entry, width=18) == "Build topology…"
    assert pipeline_stages.stage_button_label(2, 4, entry) == "3. Build topology and demands"
    assert pipeline_stages.stage_button_label(0, 2, {}) == "1. Stage 3"
    assert pipeline_stages.looks_like_runtime_reference("demo_project") is True
    assert pipeline_stages.looks_like_runtime_reference("just words here") is False
    assert pipeline_stages.is_displayable_stage({"Q": "go"}) is True
    assert pipeline_stages.is_displayable_stage({"C": "print(1)"}) is True
    assert pipeline_stages.is_displayable_stage({"Q": "   ", "C": ""}) is False
    assert pipeline_stages.is_runnable_stage({"C": "print(1)"}) is True
    assert pipeline_stages.is_runnable_stage({"C": "  "}) is False
    assert pipeline_stages.looks_like_stage("4") is True
    assert pipeline_stages.looks_like_stage("-1") is False


def test_sequence_preferences_and_guidance_ignore_invalid_metadata(tmp_path):
    stages_file = tmp_path / "lab_stages.toml"
    stages_file.write_text(
        "[__meta__]\n"
        'demo_project__sequence = [2, -1, "bad", 0]\n',
        encoding="utf-8",
    )

    assert pipeline_stages.load_sequence_preferences("demo_project", stages_file) == [2, 0]
    assert "latest ORCHESTRATE run" in pipeline_stages.snippet_source_guidance(True, "demo_project")
    assert "No ORCHESTRATE-generated snippet" in pipeline_stages.snippet_source_guidance(False, "demo_project")


def test_lab_stages_contract_metadata_and_refusal_paths() -> None:
    data = {"demo_project": [{"Q": "Run", "C": "print(1)"}]}

    prepared = pipeline_stages.prepare_lab_stages_for_write(data)

    assert prepared is data
    assert prepared["__meta__"] == {
        "schema": "agilab.lab_stages.v1",
        "version": 1,
    }
    assert pipeline_stages.lab_stages_contract_error({"__meta__": {"version": 999}}).startswith(
        "Unsupported lab_stages.toml schema version 999"
    )
    assert pipeline_stages.lab_stages_contract_error({"__meta__": "bad"}) == (
        "lab_stages.toml __meta__ must be a TOML table."
    )


def test_pipeline_stages_misc_helpers_cover_path_conversion_and_locked_source():
    converted = pipeline_stages._convert_paths_to_strings({"items": [Path("/tmp/demo"), {"path": Path("x")}]})
    assert converted == {"items": ["/tmp/demo", {"path": "x"}]}

    assert pipeline_stages.extract_stage_app_name('APP = "flight_telemetry_project"\nprint(1)\n') == "flight_telemetry_project"
    assert pipeline_stages.extract_stage_app_name("print(1)") == ""
    assert pipeline_stages.orchestrate_snippet_source({"Q": "Imported snippet: AGI_run_demo.py"}) == "AGI_run_demo.py"
