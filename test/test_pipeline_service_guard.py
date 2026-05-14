from __future__ import annotations

import importlib.util
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace


def _ensure_agilab_package_path() -> None:
    src_path = str(Path("src").resolve())
    package_root = Path("src/agilab").resolve()
    if src_path not in sys.path:
        sys.path.insert(0, src_path)
    package_spec = importlib.util.spec_from_file_location(
        "agilab",
        package_root / "__init__.py",
        submodule_search_locations=[str(package_root)],
    )
    package = sys.modules.get("agilab")
    if package is None:
        assert package_spec is not None and package_spec.loader is not None
        package = importlib.util.module_from_spec(package_spec)
        sys.modules["agilab"] = package
        package_spec.loader.exec_module(package)
        return
    package_paths = list(getattr(package, "__path__", []) or [])
    package_root_text = str(package_root)
    if package_root_text not in package_paths:
        package.__path__ = [package_root_text, *package_paths]
    package.__spec__ = package_spec
    package.__file__ = str(package_root / "__init__.py")
    package.__package__ = "agilab"


def _load_pipeline_module():
    _ensure_agilab_package_path()
    module_path = Path("src/agilab/pages/3_WORKFLOW.py")
    spec = importlib.util.spec_from_file_location("agilab_pipeline_page_tests", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_runtime_module():
    module_path = Path("src/agilab/pipeline_runtime.py")
    spec = importlib.util.spec_from_file_location("agilab_pipeline_runtime_tests", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_safe_service_template_contains_guarded_start(tmp_path):
    module = _load_runtime_module()
    settings_path = tmp_path / "app_settings.toml"
    settings_path.write_text(
        """
[cluster]
cluster_enabled = true
pool = false
cython = true
rapids = false
scheduler = "127.0.0.1:8786"
verbose = 2

[cluster.workers]
"127.0.0.1" = 1

[args]
data_in = "in.csv"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    env = SimpleNamespace(
        app_settings_file=settings_path,
        apps_path=tmp_path / "apps",
        app="flight_telemetry_project",
    )

    content = module.safe_service_start_template(
        env,
        "# AGILAB_AUTO_GENERATED_PIPELINE_SNIPPET: SAFE_SERVICE_START",
    )
    assert "action=\"status\"" in content
    assert "state in {\"running\", \"degraded\"}" in content
    assert "action=\"stop\"" in content
    assert "action=\"start\"" in content
    assert "MODE = 6" in content
    assert "RUN_ARGS = {'data_in': 'in.csv'}" in content


def test_ensure_safe_service_template_preserves_manual_file(tmp_path):
    module = _load_runtime_module()
    stages_file = tmp_path / "lab_stages.toml"
    stages_file.write_text("", encoding="utf-8")
    template_path = tmp_path / "AGI_serve_safe_start_template.py"
    manual_content = "# custom user template\nprint('manual')\n"
    template_path.write_text(manual_content, encoding="utf-8")

    env = SimpleNamespace(
        app_settings_file=tmp_path / "app_settings.toml",
        apps_path=tmp_path / "apps",
        app="flight_telemetry_project",
    )
    env.app_settings_file.write_text("", encoding="utf-8")

    written_path = module.ensure_safe_service_template(
        env,
        stages_file,
        template_filename="AGI_serve_safe_start_template.py",
        marker="# AGILAB_AUTO_GENERATED_PIPELINE_SNIPPET: SAFE_SERVICE_START",
        debug_log=lambda *args, **kwargs: None,
    )
    assert written_path == template_path
    assert template_path.read_text(encoding="utf-8") == manual_content


def test_pipeline_lock_rejects_parallel_and_recycles_stale(tmp_path, monkeypatch):
    module = _load_pipeline_module()
    monkeypatch.setattr(module, "_push_run_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(module.st, "warning", lambda *args, **kwargs: None)
    monkeypatch.setattr(module.st, "error", lambda *args, **kwargs: None)
    monkeypatch.setenv("AGILAB_PIPELINE_LOCK_TTL_SEC", "60")

    class DummyEnv:
        app = "flight_telemetry_project"
        target = "flight"
        home_abs = tmp_path

        def resolve_share_path(self, relative: Path) -> Path:
            return tmp_path / relative

    env = DummyEnv()

    first = module._acquire_pipeline_run_lock(env, "idx")
    assert first is not None
    lock_path = Path(first["path"])
    assert lock_path == tmp_path / ".control" / "pipeline" / "flight" / "pipeline_run.lock"
    assert lock_path.exists()

    blocked = module._acquire_pipeline_run_lock(env, "idx")
    assert blocked is None

    stale_time = time.time() - 3600
    os.utime(lock_path, (stale_time, stale_time))
    monkeypatch.setenv("AGILAB_PIPELINE_LOCK_TTL_SEC", "1")

    recycled = module._acquire_pipeline_run_lock(env, "idx")
    assert recycled is not None
    assert recycled["token"] != first["token"]
    assert Path(recycled["path"]).exists()

    # Releasing the previous owner token must not delete the new lock.
    module._release_pipeline_run_lock(first, "idx")
    assert Path(recycled["path"]).exists()

    module._release_pipeline_run_lock(recycled, "idx")
    assert not Path(recycled["path"]).exists()


def test_pipeline_lock_ttl_seconds_falls_back_on_invalid_env(monkeypatch):
    module = _load_pipeline_module()
    monkeypatch.setenv("AGILAB_PIPELINE_LOCK_TTL_SEC", "not-a-number")

    assert module._pipeline_lock_ttl_seconds() == module.PIPELINE_LOCK_DEFAULT_TTL_SEC


def test_read_pipeline_lock_payload_returns_empty_dict_on_invalid_json(tmp_path):
    module = _load_pipeline_module()
    bad_lock = tmp_path / "pipeline_run.lock"
    bad_lock.write_text("{broken", encoding="utf-8")

    assert module._read_pipeline_lock_payload(bad_lock) == {}
