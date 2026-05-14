from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "lightning_studio_demo.py"
MODULE_SPEC = importlib.util.spec_from_file_location("tools.lightning_studio_demo", MODULE_PATH)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
lightning_demo = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = lightning_demo
MODULE_SPEC.loader.exec_module(lightning_demo)


def test_find_repo_root_discovers_checkout_from_nested_path(tmp_path: Path) -> None:
    repo_root = tmp_path / "agilab"
    nested = repo_root / "examples" / "demo"
    (repo_root / "src" / "agilab").mkdir(parents=True)
    (repo_root / "src" / "agilab" / "main_page.py").write_text("pass\n", encoding="utf-8")
    (repo_root / "pyproject.toml").write_text("[project]\nname='agilab'\n", encoding="utf-8")
    nested.mkdir(parents=True)

    assert lightning_demo.find_repo_root(nested) == repo_root.resolve()


def test_build_demo_env_forces_local_only_runtime(tmp_path: Path) -> None:
    repo_root = tmp_path / "agilab"
    runtime_dir = repo_root / ".lightning_studio_runtime"
    env = lightning_demo.build_demo_env(
        repo_root,
        runtime_dir,
        environ={
            "IS_SOURCE_ENV": "0",
            "IS_WORKER_ENV": "1",
            "AGI_CLUSTER_ENABLED": "1",
        },
    )

    assert env["IS_SOURCE_ENV"] == "1"
    assert env["AGI_CLUSTER_ENABLED"] == "0"
    assert "IS_WORKER_ENV" not in env
    assert env["AGI_LOG_DIR"] == str(runtime_dir / "log")
    assert env["AGI_EXPORT_DIR"] == str(runtime_dir / "export")
    assert env["AGI_LOCAL_SHARE"] == str(runtime_dir / "localshare")
    assert env["MLFLOW_TRACKING_DIR"] == str(runtime_dir / "mlflow")
    assert env["APPS_PATH"] == str((repo_root / "src" / "agilab" / "apps").resolve())


def test_build_streamlit_command_targets_about_page_and_default_app(tmp_path: Path) -> None:
    repo_root = tmp_path / "agilab"

    cmd = lightning_demo.build_streamlit_command(repo_root, active_app="flight_telemetry_project", port=8601)

    assert cmd[:6] == [
        "uv",
        "--preview-features",
        "extra-build-dependencies",
        "run",
        "streamlit",
        "run",
    ]
    assert cmd[6] == str((repo_root / "src" / "agilab" / "main_page.py").resolve())
    assert "--server.address" in cmd
    assert "0.0.0.0" in cmd
    assert "--server.port" in cmd
    assert "8601" in cmd
    assert cmd[-4:] == [
        "--apps-path",
        str((repo_root / "src" / "agilab" / "apps").resolve()),
        "--active-app",
        "flight_telemetry_project",
    ]
