import os
from pathlib import Path
from types import SimpleNamespace

from agi_node.agi_dispatcher import build as build_mod


def _stub_build_logger():
    return SimpleNamespace(
        info=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
        error=lambda *args, **kwargs: None,
        debug=lambda *args, **kwargs: None,
    )


def test_purge_worker_venv_artifacts_removes_nested_worker_envs(tmp_path):
    app_root = tmp_path / "demo_project"
    src_venv = app_root / "src" / "demo_worker" / ".venv"
    build_venv = app_root / "build" / "lib" / "demo_worker" / ".venv"
    bdist_venv = app_root / "build" / "bdist.test" / "egg" / "demo_worker" / ".venv"

    for path in (src_venv, build_venv, bdist_venv):
        (path / "nested").mkdir(parents=True, exist_ok=True)
        (path / "nested" / "marker.txt").write_text("x", encoding="utf-8")

    if os.name != "nt":
        os.chmod(src_venv, 0)

    build_mod.AgiEnv.logger = _stub_build_logger()
    removed = build_mod._purge_worker_venv_artifacts(app_root, "demo_worker")

    removed_set = {path.relative_to(app_root).as_posix() for path in removed}
    assert removed_set == {
        "src/demo_worker/.venv",
        "build/lib/demo_worker/.venv",
        "build/bdist.test/egg/demo_worker/.venv",
    }
    assert not src_venv.exists()
    assert not build_venv.exists()
    assert not bdist_venv.exists()
