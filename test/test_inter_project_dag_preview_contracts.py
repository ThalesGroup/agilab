"""Installed-layout and local preview contracts for the cross-project DAG example."""

import json
from pathlib import Path

import pytest

from agilab.examples.inter_project_dag import preview_inter_project_dag as preview


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "operator"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


def write_marker(home, value):
    marker = home / ".local/share/agilab/.agilab-path"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(str(value))
    return marker


def test_marker_reports_uninitialized_and_stale_installation(isolated_home):
    with pytest.raises(SystemExit, match="not initialized"):
        preview.agilab_package_path()
    write_marker(isolated_home, isolated_home / "removed-install")
    with pytest.raises(SystemExit, match="does not exist"):
        preview.agilab_package_path()
    package = isolated_home / "installed package"
    package.mkdir()
    write_marker(isolated_home, package)
    assert preview.agilab_package_path() == package


def test_source_layout_detection_does_not_depend_on_process_cwd(tmp_path, monkeypatch):
    package = tmp_path / "checkout/src/agilab"
    (package / "apps/builtin").mkdir(parents=True)
    script = package / "examples/inter_project_dag/preview_inter_project_dag.py"
    monkeypatch.setattr(preview, "__file__", str(script))
    assert preview._source_checkout_root_from_file() == tmp_path / "checkout"
    assert preview._source_checkout_root_from_package(package) == tmp_path / "checkout"
    assert preview._source_checkout_root_from_package(Path("/")) is None
    assert preview._source_checkout_root_from_package(tmp_path / "wheel/agilab") is None


def test_planning_prefers_explicit_checkout_without_install_marker(
    tmp_path, isolated_home, monkeypatch
):
    monkeypatch.setattr(
        preview,
        "_source_checkout_root_from_file",
        lambda: pytest.fail("explicit root must win"),
    )
    assert (
        preview.planning_repo_root(tmp_path / "checkout/../chosen")
        == tmp_path / "chosen"
    )


def test_planning_source_checkout_needs_no_install_marker(
    tmp_path, isolated_home, monkeypatch
):
    source = tmp_path / "checkout"
    monkeypatch.setattr(preview, "_source_checkout_root_from_file", lambda: source)
    assert preview.planning_repo_root() == source


def test_planning_uses_marker_source_checkout_when_example_is_installed(
    tmp_path, isolated_home, monkeypatch
):
    source = tmp_path / "checkout"
    package = source / "src/agilab"
    (package / "apps/builtin").mkdir(parents=True)
    monkeypatch.setattr(preview, "_source_checkout_root_from_file", lambda: None)
    write_marker(isolated_home, package)
    assert preview.planning_repo_root() == source


def test_packaged_layout_replaces_stale_symlink_without_deleting_old_apps(
    tmp_path, isolated_home, monkeypatch
):
    packages = [tmp_path / name / "agilab" for name in ("old", "new")]
    for package in packages:
        (package / "apps/builtin/example_project").mkdir(parents=True)
        (package / "apps/builtin/example_project/README.md").write_text(str(package))
    first = preview._ensure_packaged_layout_adapter(packages[0])
    adapter = first / "src/agilab/apps"
    assert adapter.resolve() == packages[0] / "apps"
    monkeypatch.setattr(preview, "_source_checkout_root_from_file", lambda: None)
    write_marker(isolated_home, packages[1])
    assert preview.planning_repo_root() == first
    assert adapter.resolve() == packages[1] / "apps"
    assert (packages[0] / "apps/builtin/example_project/README.md").read_text() == str(
        packages[0]
    )


def test_packaged_layout_copies_when_symlinks_are_unavailable(
    tmp_path, isolated_home, monkeypatch
):
    package = tmp_path / "wheel/agilab"
    payload = package / "apps/builtin/example_project/README.md"
    payload.parent.mkdir(parents=True)
    payload.write_text("packaged public example")

    def denied(*args, **kwargs):
        raise OSError("symlinks unavailable")

    monkeypatch.setattr(Path, "symlink_to", denied)
    root = preview._ensure_packaged_layout_adapter(package)
    adapter = root / "src/agilab/apps"
    assert not adapter.is_symlink()
    assert (
        adapter / "builtin/example_project/README.md"
    ).read_text() == payload.read_text()


def test_packaged_layout_rejects_missing_or_polluted_assets(tmp_path, isolated_home):
    package = tmp_path / "package"
    with pytest.raises(SystemExit, match="built-in apps"):
        preview._ensure_packaged_layout_adapter(package)
    (package / "apps/builtin").mkdir(parents=True)
    adapter = isolated_home / ".cache/agilab/inter_project_dag_layout/src/agilab/apps"
    adapter.parent.mkdir(parents=True)
    adapter.write_text("user-owned obstruction")
    with pytest.raises(SystemExit, match="Could not prepare"):
        preview._ensure_packaged_layout_adapter(package)
    assert adapter.read_text() == "user-owned obstruction"


def test_preview_cli_persists_plan_without_dispatching_apps(tmp_path, capsys):
    output = tmp_path / "inter-project-dag-runner-preview.json"
    summary = preview.main(
        [
            "--repo-root",
            str(ROOT),
            "--dag-path",
            str(preview.DAG_PATH),
            "--output",
            str(output),
        ]
    )
    assert json.loads(capsys.readouterr().out) == summary
    assert summary["dag"]["ok"] is True
    assert summary["real_app_execution"] is False
    assert summary["runner_state"]["round_trip_ok"] is True
    assert summary["after_first_dispatch"]["dispatched_unit_id"] == "flight_context"
    persisted = json.loads(output.read_text())
    assert persisted["run_id"] == preview.RUN_ID
    assert persisted["run_status"] != summary["after_first_dispatch"]["run_status"]
    assert not list(tmp_path.glob("*_project"))


def test_artifact_handoff_preview_filters_non_contract_payloads():
    units = [
        {
            "id": "producer",
            "app": "first",
            "ready": False,
            "produces": [None, {}, {"artifact": "measurements"}],
        },
        {
            "id": "consumer",
            "app": "second",
            "ready": False,
            "artifact_dependencies": [
                None,
                {"from": "producer", "artifact": "measurements"},
            ],
        },
    ]
    assert preview._unit_preview(units[0])["produces"] == ["measurements"]
    handoffs = preview._artifact_handoffs(units)
    assert len(handoffs) == 1
    assert handoffs[0]["producer_status"] == "blocked"
    assert handoffs[0]["from"] == "producer"
    assert handoffs[0]["to"] == "consumer"
