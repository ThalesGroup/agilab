"""Built-in DAG preview remains read-only across installed and source layouts."""

import importlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def preview(tmp_path, monkeypatch):
    package_root = ROOT / "src/agilab/apps/builtin/multi_app_dag_project/src"
    monkeypatch.syspath_prepend(str(package_root))
    names = ("multi_app_dag", "multi_app_dag.preview_multi_app_dag")
    for name in reversed(names):
        monkeypatch.delitem(sys.modules, name, raising=False)
    module = importlib.import_module(names[1])
    home = tmp_path / "operator"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    yield module, home
    for name in reversed(names):
        monkeypatch.delitem(sys.modules, name, raising=False)


def marker(home, package):
    path = home / ".local/share/agilab/.agilab-path"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(package))


def test_multi_app_preview_cli_round_trips_state_without_executing_apps(
    preview, tmp_path, capsys
):
    module, _ = preview
    output = tmp_path / "multi-app-state.json"
    result = module.main(
        [
            "--repo-root",
            str(ROOT),
            "--dag-path",
            str(module.DAG_PATH),
            "--output",
            str(output),
        ]
    )
    assert json.loads(capsys.readouterr().out) == result
    assert result["dag"]["ok"] is True
    assert result["real_app_execution"] is False
    assert result["runner_state"]["round_trip_ok"] is True
    state = json.loads(output.read_text())
    assert state["run_id"] == module.RUN_ID
    assert state["run_status"] != result["after_first_dispatch"]["run_status"]
    assert result["after_first_dispatch"]["dispatched_unit_id"] == "flight_context"
    assert not list(tmp_path.glob("*_project"))


def test_multi_app_install_marker_rejects_uninitialized_or_removed_package(preview):
    module, home = preview
    with pytest.raises(SystemExit, match="not initialized"):
        module.agilab_package_path()
    marker(home, home / "removed")
    with pytest.raises(SystemExit, match="does not exist"):
        module.agilab_package_path()


@pytest.mark.parametrize("layout", ["explicit", "source", "marker-source", "installed"])
def test_multi_app_planning_selects_authoritative_layout(
    preview, tmp_path, monkeypatch, layout
):
    module, home = preview
    source = tmp_path / "checkout"
    package = source / "src/agilab"
    (package / "apps/builtin").mkdir(parents=True)
    if layout == "explicit":
        assert module.planning_repo_root(source / "../checkout") == source
    elif layout == "source":
        monkeypatch.setattr(module, "_SOURCE_ROOT", source)
        assert module.planning_repo_root() == source
    else:
        monkeypatch.setattr(module, "_SOURCE_ROOT", None)
        if layout == "installed":
            package = tmp_path / "site-packages/agilab"
            (package / "apps/builtin").mkdir(parents=True)
        marker(home, package)
        root = module.planning_repo_root()
        assert (root / "src/agilab/apps/builtin").is_dir()
        if layout == "marker-source":
            assert root == source
        else:
            assert root == home / ".cache/agilab/multi_app_dag_layout"


def test_multi_app_source_detection_handles_shallow_or_unrelated_layout(
    preview, tmp_path, monkeypatch
):
    module, _ = preview
    assert module._source_checkout_root_from_package(Path("/")) is None
    assert module._source_checkout_root_from_package(tmp_path / "wheel/agilab") is None
    monkeypatch.setattr(module, "__file__", str(tmp_path / "wheel/preview.py"))
    assert module._repo_root_from_file() is None
    package = tmp_path / "source/src/agilab"
    (package / "apps/builtin").mkdir(parents=True)
    monkeypatch.setattr(module, "__file__", str(package / "preview.py"))
    assert module._repo_root_from_file() == tmp_path / "source"


@pytest.mark.parametrize("copy_fallback", [False, True])
def test_multi_app_layout_adapter_updates_stale_install_without_deleting_original(
    preview, tmp_path, monkeypatch, copy_fallback
):
    module, _ = preview
    old = tmp_path / "old/agilab"
    new = tmp_path / "new/agilab"
    for package in (old, new):
        (package / "apps/builtin").mkdir(parents=True)
        (package / "apps/builtin/marker.txt").write_text(package.parent.name)
    root = module._ensure_packaged_layout_adapter(old)
    if copy_fallback:

        def deny_link(*args, **kwargs):
            raise OSError("symlinks unavailable")

        monkeypatch.setattr(Path, "symlink_to", deny_link)
    assert module._ensure_packaged_layout_adapter(new) == root
    assert (root / "src/agilab/apps/builtin/marker.txt").read_text() == "new"
    assert (old / "apps/builtin/marker.txt").read_text() == "old"


def test_multi_app_layout_adapter_reports_missing_assets_and_polluted_target(
    preview, tmp_path
):
    module, home = preview
    package = tmp_path / "package"
    with pytest.raises(SystemExit, match="built-in apps"):
        module._ensure_packaged_layout_adapter(package)
    (package / "apps/builtin").mkdir(parents=True)
    adapter = home / ".cache/agilab/multi_app_dag_layout/src/agilab/apps"
    adapter.parent.mkdir(parents=True)
    adapter.write_text("user-owned")
    with pytest.raises(SystemExit, match="Could not prepare"):
        module._ensure_packaged_layout_adapter(package)
    assert adapter.read_text() == "user-owned"


def test_multi_app_handoff_does_not_promote_missing_or_blocked_producers(preview):
    module, _ = preview
    units = [
        {
            "id": "first",
            "app": "producer",
            "ready": False,
            "produces": [None, {}, {"artifact": "result"}],
        },
        {
            "id": "second",
            "app": "consumer",
            "artifact_dependencies": [
                None,
                {"from": "first", "artifact": "result"},
                {"from": "missing", "artifact": "unavailable"},
            ],
        },
    ]
    assert module._unit_preview(units[0])["produces"] == ["result"]
    handoffs = module._artifact_handoffs(units)
    assert len(handoffs) == 2
    assert all(item["producer_status"] == "blocked" for item in handoffs)
    assert {item["artifact"] for item in handoffs} == {"result", "unavailable"}
