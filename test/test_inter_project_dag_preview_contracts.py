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


def test_packaged_layout_keeps_prior_symlink_context_when_package_changes(
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
    second = preview.planning_repo_root()
    assert second != first
    assert (
        second / "src/agilab/apps/builtin/example_project/README.md"
    ).read_text() == str(packages[1])
    assert adapter.resolve() == packages[0] / "apps"
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
    selected = preview._ensure_packaged_layout_adapter(package)
    assert (selected / "src/agilab/apps/builtin").is_dir()
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


@pytest.mark.parametrize(
    "layout", ["source", "source-link", "nested-wheel", "unrelated-copy", "shallow"]
)
def test_inter_project_module_identity_controls_source_classification(
    tmp_path, isolated_home, monkeypatch, layout
):
    module = preview
    checkout = tmp_path / "checkout"
    package = checkout / "src/agilab"
    (package / "apps/builtin").mkdir(parents=True)
    expected = None
    if layout in {"source", "source-link"}:
        script = package / "examples/inter_project_dag/preview_inter_project_dag.py"
        expected = checkout
    elif layout == "nested-wheel":
        script = (
            checkout
            / ".venv/lib/python3.13/site-packages/agilab/examples/inter_project_dag/preview_inter_project_dag.py"
        )
    elif layout == "shallow":
        script = Path(tmp_path.anchor) / "preview.py"
    else:
        script = checkout / "scratch/preview.py"
    if layout != "shallow":
        script.parent.mkdir(parents=True, exist_ok=True)
        script.touch()
    if layout == "source-link":
        alias = tmp_path / "preview-link.py"
        alias.symlink_to(script)
        script = alias
    monkeypatch.setattr(module, "__file__", str(script))
    assert module._source_checkout_root_from_file() == expected


@pytest.mark.parametrize(
    "layout",
    ["source", "source-link", "nested-wheel", "wheel-link", "other-package", "shallow"],
)
def test_inter_project_package_identity_controls_marker_source_classification(
    tmp_path, isolated_home, monkeypatch, layout
):
    module = preview
    checkout = tmp_path / "checkout"
    package = checkout / "src/agilab"
    (package / "apps/builtin").mkdir(parents=True)
    expected = checkout
    if layout == "source-link":
        alias = tmp_path / "source-package-link"
        alias.symlink_to(package, target_is_directory=True)
        package = alias
    elif layout in {"nested-wheel", "wheel-link"}:
        package = checkout / ".venv/lib/python3.13/site-packages/agilab"
        (package / "apps/builtin").mkdir(parents=True)
        expected = None
        if layout == "wheel-link":
            alias = tmp_path / "apparent-checkout/src/agilab"
            alias.parent.mkdir(parents=True)
            alias.symlink_to(package, target_is_directory=True)
            package = alias
    elif layout == "other-package":
        package = checkout / "src/other"
        package.mkdir()
        expected = None
    elif layout == "shallow":
        package = Path(tmp_path.anchor)
        expected = None
    assert module._source_checkout_root_from_package(package) == expected


@pytest.mark.parametrize(
    "source_package", [False, True], ids=["wheel-link", "source-link"]
)
def test_inter_project_planning_follows_resolved_package_marker(
    tmp_path, isolated_home, monkeypatch, source_package
):
    module, home = preview, isolated_home
    checkout = tmp_path / "checkout"
    (checkout / "src/agilab/apps/builtin").mkdir(parents=True)
    package = checkout / (
        "src/agilab" if source_package else ".venv/site-packages/agilab"
    )
    (package / "apps/builtin").mkdir(parents=True, exist_ok=True)
    alias = tmp_path / "marker-package"
    alias.symlink_to(package, target_is_directory=True)
    monkeypatch.setattr(module, "_source_checkout_root_from_file", lambda: None)
    write_marker(home, alias)
    selected = module.planning_repo_root()
    if source_package:
        assert selected == checkout
    else:
        assert selected != checkout
        assert (selected / "src/agilab/apps").resolve() == package / "apps"


def test_inter_project_copy_first_adapter_refreshes_a_different_package(
    tmp_path, isolated_home, monkeypatch
):
    module = preview
    old, new = (tmp_path / name / "agilab" for name in ("old", "new"))
    for package in (old, new):
        (package / "apps/builtin").mkdir(parents=True)
        (package / "apps/builtin/package.txt").write_text(package.parent.name)
    (old / "apps/builtin/obsolete.txt").write_text("old package only")

    def deny_link(*_args, **_kwargs):
        raise OSError("symlinks unavailable")

    monkeypatch.setattr(Path, "symlink_to", deny_link)
    first = module._ensure_packaged_layout_adapter(old)
    assert not (first / "src/agilab/apps").is_symlink()
    refreshed = module._ensure_packaged_layout_adapter(new)
    assert (refreshed / "src/agilab/apps/builtin/package.txt").read_text() == "new"
    assert not (refreshed / "src/agilab/apps/builtin/obsolete.txt").exists()
    assert (old / "apps/builtin/package.txt").read_text() == "old"
    assert (new / "apps/builtin/package.txt").read_text() == "new"
    assert module._ensure_packaged_layout_adapter(new) == refreshed
    assert module._ensure_packaged_layout_adapter(old) == first


def test_inter_project_adapter_preserves_an_unproven_directory(
    tmp_path, isolated_home, monkeypatch
):
    module, home = preview, isolated_home
    package = tmp_path / "wheel/agilab"
    (package / "apps/builtin").mkdir(parents=True)
    adapter = home / ".cache/agilab/inter_project_dag_layout/src/agilab/apps"
    (adapter / "builtin").mkdir(parents=True)
    owned = adapter / "builtin/user-owned.txt"
    owned.write_text("retain this directory")
    selected = module._ensure_packaged_layout_adapter(package)
    assert (selected / "src/agilab/apps/builtin").is_dir()
    assert not (selected / "src/agilab/apps/builtin/user-owned.txt").exists()
    assert owned.read_text() == "retain this directory"
    assert (package / "apps/builtin").is_dir()


def test_inter_project_adapter_can_retry_after_copy_denial(
    tmp_path, isolated_home, monkeypatch
):
    module = preview
    package = tmp_path / "wheel/agilab"
    (package / "apps/builtin").mkdir(parents=True)
    (package / "apps/builtin/recovery.txt").write_text("ready")
    copytree = module.shutil.copytree

    def deny_link(*_args, **_kwargs):
        raise OSError("symlinks unavailable")

    def deny_copy(_source, destination, **_kwargs):
        partial = Path(destination) / "partial.txt"
        partial.parent.mkdir(parents=True)
        partial.write_text("incomplete copy")
        raise OSError("copy unavailable")

    monkeypatch.setattr(Path, "symlink_to", deny_link)
    monkeypatch.setattr(module.shutil, "copytree", deny_copy)
    with pytest.raises(OSError, match="copy unavailable"):
        module._ensure_packaged_layout_adapter(package)
    monkeypatch.setattr(module.shutil, "copytree", copytree)
    selected = module._ensure_packaged_layout_adapter(package)
    assert (selected / "src/agilab/apps/builtin/recovery.txt").read_text() == "ready"
