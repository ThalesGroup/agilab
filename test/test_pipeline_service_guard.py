from __future__ import annotations

import importlib.util
import os
import time
from pathlib import Path
from types import SimpleNamespace


def _load_pipeline_module():
    module_path = Path("src/agilab/pages/3_▶️ PIPELINE.py")
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
        app="flight_project",
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
    steps_file = tmp_path / "lab_steps.toml"
    steps_file.write_text("", encoding="utf-8")
    template_path = tmp_path / "AGI_serve_safe_start_template.py"
    manual_content = "# custom user template\nprint('manual')\n"
    template_path.write_text(manual_content, encoding="utf-8")

    env = SimpleNamespace(
        app_settings_file=tmp_path / "app_settings.toml",
        apps_path=tmp_path / "apps",
        app="flight_project",
    )
    env.app_settings_file.write_text("", encoding="utf-8")

    written_path = module.ensure_safe_service_template(
        env,
        steps_file,
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
        app = "flight_project"
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
