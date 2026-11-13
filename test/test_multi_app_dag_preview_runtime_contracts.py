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
    monkeypatch.setattr(
        module,
        "__file__",
        str(
            package
            / "apps/builtin/multi_app_dag_project/src/multi_app_dag/preview_multi_app_dag.py"
        ),
    )
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
    refreshed = module._ensure_packaged_layout_adapter(new)
    assert refreshed != root
    assert (refreshed / "src/agilab/apps/builtin/marker.txt").read_text() == "new"
    assert (root / "src/agilab/apps/builtin/marker.txt").read_text() == "old"
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
    selected = module._ensure_packaged_layout_adapter(package)
    assert selected != adapter.parents[2]
    assert (selected / "src/agilab/apps/builtin").is_dir()
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


@pytest.mark.parametrize(
    "layout", ["source", "source-link", "nested-wheel", "unrelated-copy", "shallow"]
)
def test_multi_app_module_identity_controls_source_classification(
    preview, tmp_path, monkeypatch, layout
):
    module, home = preview
    checkout = tmp_path / "checkout"
    package = checkout / "src/agilab"
    (package / "apps/builtin").mkdir(parents=True)
    expected = None
    if layout in {"source", "source-link"}:
        script = (
            package
            / "apps/builtin/multi_app_dag_project/src/multi_app_dag/preview_multi_app_dag.py"
        )
        expected = checkout
    elif layout == "nested-wheel":
        script = (
            checkout
            / ".venv/lib/python3.13/site-packages/agilab/apps/builtin/multi_app_dag_project/src/multi_app_dag/preview_multi_app_dag.py"
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
    assert module._repo_root_from_file() == expected


@pytest.mark.parametrize(
    "layout",
    ["source", "source-link", "nested-wheel", "wheel-link", "other-package", "shallow"],
)
def test_multi_app_package_identity_controls_marker_source_classification(
    preview, tmp_path, monkeypatch, layout
):
    module, home = preview
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
def test_multi_app_planning_follows_resolved_package_marker(
    preview, tmp_path, monkeypatch, source_package
):
    module, home = preview
    checkout = tmp_path / "checkout"
    (checkout / "src/agilab/apps/builtin").mkdir(parents=True)
    package = checkout / (
        "src/agilab" if source_package else ".venv/site-packages/agilab"
    )
    (package / "apps/builtin").mkdir(parents=True, exist_ok=True)
    alias = tmp_path / "marker-package"
    alias.symlink_to(package, target_is_directory=True)
    monkeypatch.setattr(module, "_SOURCE_ROOT", None)
    marker(home, alias)
    selected = module.planning_repo_root()
    if source_package:
        assert selected == checkout
    else:
        assert selected != checkout
        assert (selected / "src/agilab/apps").resolve() == package / "apps"


def test_multi_app_copy_first_adapter_refreshes_a_different_package(
    preview, tmp_path, monkeypatch
):
    module, home = preview
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


def test_multi_app_adapter_preserves_an_unproven_directory(
    preview, tmp_path, monkeypatch
):
    module, home = preview
    package = tmp_path / "wheel/agilab"
    (package / "apps/builtin").mkdir(parents=True)
    adapter = home / ".cache/agilab/multi_app_dag_layout/src/agilab/apps"
    (adapter / "builtin").mkdir(parents=True)
    owned = adapter / "builtin/user-owned.txt"
    owned.write_text("retain this directory")
    selected = module._ensure_packaged_layout_adapter(package)
    assert (selected / "src/agilab/apps/builtin").is_dir()
    assert not (selected / "src/agilab/apps/builtin/user-owned.txt").exists()
    assert owned.read_text() == "retain this directory"
    assert (package / "apps/builtin").is_dir()


def test_multi_app_adapter_can_retry_after_copy_denial(preview, tmp_path, monkeypatch):
    module, home = preview
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


@pytest.fixture(params=["builtin", "inter-project"])
def correction_context(request, preview):
    module, home = preview
    if request.param == "inter-project":
        module = importlib.import_module(
            "agilab.examples.inter_project_dag.preview_inter_project_dag"
        )
    cache_name = (
        "multi_app_dag_layout"
        if request.param == "builtin"
        else "inter_project_dag_layout"
    )
    return module, home, home / ".cache/agilab" / cache_name


def _baseline_copy_fallback(package, repo_root):
    # The exact base helper's unmarked copy fallback, with its cache root injected.
    apps_path = package / "apps"
    adapter_package = repo_root / "src/agilab"
    adapter_apps = adapter_package / "apps"
    adapter_package.mkdir(parents=True, exist_ok=True)
    if adapter_apps.is_symlink() and adapter_apps.resolve() != apps_path.resolve():
        adapter_apps.unlink()
    if not adapter_apps.exists():
        try:
            adapter_apps.symlink_to(apps_path, target_is_directory=True)
        except OSError:
            import shutil

            shutil.copytree(apps_path, adapter_apps, dirs_exist_ok=True)
    return repo_root


def _deny_preview_symlinks(*_args, **_kwargs):
    raise OSError("symlinks unavailable")


def test_correction_legacy_copy_upgrade_preserves_unknown_slots(
    correction_context, tmp_path, monkeypatch
):
    import hashlib

    module, _, cache = correction_context
    old, new = (tmp_path / name / "agilab" for name in ("old", "new"))
    for package in (old, new):
        (package / "apps/builtin").mkdir(parents=True)
        (package / "apps/builtin/package.txt").write_text(package.parent.name)
    monkeypatch.setattr(Path, "symlink_to", _deny_preview_symlinks)
    legacy = _baseline_copy_fallback(old, cache)
    legacy_apps = legacy / "src/agilab/apps"
    assert not (legacy_apps.parent / ".apps-copy-source").exists()
    unknown = (
        cache
        / "copies"
        / hashlib.sha256(str((old / "apps").resolve()).encode()).hexdigest()
    )
    unknown.mkdir(parents=True)
    (unknown / "unknown.txt").write_text("retain unknown alternate")
    for package in (old, new):
        selected = module._ensure_packaged_layout_adapter(package)
        assert selected != legacy
        assert (selected / "src/agilab/apps/builtin/package.txt").read_text() == (
            package.parent.name
        )
    assert (legacy_apps / "builtin/package.txt").read_text() == "old"
    assert not (legacy_apps.parent / ".apps-copy-source").exists()
    assert (unknown / "unknown.txt").read_text() == "retain unknown alternate"


@pytest.mark.parametrize("failure", ["marker-write", "publication"])
def test_correction_copy_publication_is_retryable(
    correction_context, tmp_path, monkeypatch, failure
):
    module, _, cache = correction_context
    package = tmp_path / "wheel/agilab"
    (package / "apps/builtin").mkdir(parents=True)
    (package / "apps/builtin/ready.txt").write_text("complete assets")
    monkeypatch.setattr(Path, "symlink_to", _deny_preview_symlinks)
    write_text, rename = Path.write_text, Path.rename
    failed = False
    marker_staged = False

    def fail_marker(path, *args, **kwargs):
        nonlocal failed
        if path.name == ".apps-copy-source" and not failed:
            failed = True
            raise OSError("injected marker-write failure")
        return write_text(path, *args, **kwargs)

    def fail_publication(path, target):
        nonlocal failed, marker_staged
        if not failed:
            provenance = (
                path / "agilab/.apps-copy-source"
                if path.name == "src"
                else path.parent / ".apps-copy-source"
            )
            marker_staged = provenance.is_file()
            failed = True
            raise OSError("injected publication failure")
        return rename(path, target)

    monkeypatch.setattr(
        Path,
        "write_text" if failure == "marker-write" else "rename",
        fail_marker if failure == "marker-write" else fail_publication,
    )
    with pytest.raises(OSError, match=f"injected {failure} failure"):
        module._ensure_packaged_layout_adapter(package)
    assert failed
    if failure == "publication":
        assert marker_staged, "Provenance must be staged before publishing assets"
    assert not list(cache.rglob("ready.txt")), "Unpublished assets must be cleaned"
    selected = module._ensure_packaged_layout_adapter(package)
    assert (selected / "src/agilab/apps/builtin/ready.txt").read_text() == (
        "complete assets"
    )
    assert (selected / "src/agilab/.apps-copy-source").is_file()
    assert not [p for p in cache.rglob(".apps-copy-*") if p.is_dir()]


@pytest.mark.parametrize("marker_kind", ["file", "symlink", "directory"])
def test_correction_unknown_provenance_is_preserved(
    correction_context, tmp_path, monkeypatch, marker_kind
):
    module, _, cache = correction_context
    package = tmp_path / "wheel/agilab"
    (package / "apps/builtin").mkdir(parents=True)
    (package / "apps/builtin/ready.txt").write_text("source assets")
    provenance = cache / "src/agilab/.apps-copy-source"
    provenance.parent.mkdir(parents=True)
    victim = tmp_path / "user-provenance.txt"
    victim.write_text("user content")
    if marker_kind == "symlink":
        provenance.symlink_to(victim)
    elif marker_kind == "directory":
        provenance.mkdir()
        (provenance / "user.txt").write_text("user directory")
    else:
        provenance.write_text("user marker")
    monkeypatch.setattr(Path, "symlink_to", _deny_preview_symlinks)
    selected = module._ensure_packaged_layout_adapter(package)
    assert selected != cache
    assert (
        selected / "src/agilab/apps/builtin/ready.txt"
    ).read_text() == "source assets"
    assert victim.read_text() == "user content"
    if marker_kind == "symlink":
        assert provenance.is_symlink() and provenance.readlink() == victim
    elif marker_kind == "directory":
        assert (provenance / "user.txt").read_text() == "user directory"
    else:
        assert provenance.read_text() == "user marker"


def test_correction_same_path_asset_upgrade_keeps_prior_copy(
    correction_context, tmp_path, monkeypatch
):
    module, _, _ = correction_context
    package = tmp_path / "wheel/agilab"
    assets = package / "apps/builtin"
    assets.mkdir(parents=True)
    (assets / "changed.txt").write_text("before")
    (assets / "removed.txt").write_text("old asset")
    monkeypatch.setattr(Path, "symlink_to", _deny_preview_symlinks)
    first = module._ensure_packaged_layout_adapter(package)
    assert module._ensure_packaged_layout_adapter(package) == first
    (assets / "changed.txt").write_text("after")
    (assets / "added.txt").write_text("new asset")
    (assets / "removed.txt").unlink()
    second = module._ensure_packaged_layout_adapter(package)
    assert second != first
    current = second / "src/agilab/apps/builtin"
    assert (current / "changed.txt").read_text() == "after"
    assert (current / "added.txt").read_text() == "new asset"
    assert not (current / "removed.txt").exists()
    original = first / "src/agilab/apps/builtin"
    assert (original / "changed.txt").read_text() == "before"
    assert (original / "removed.txt").read_text() == "old asset"
    assert not (original / "added.txt").exists()
    assert module._ensure_packaged_layout_adapter(package) == second


@pytest.mark.parametrize(
    "marker_payload",
    [b"unknown replacement marker", b"\xffunknown"],
    ids=["text", "invalid-utf8"],
)
def test_correction_modified_owned_cache_continues_in_fresh_slot(
    correction_context, tmp_path, monkeypatch, marker_payload
):
    module, _, _ = correction_context
    package = tmp_path / "wheel/agilab"
    (package / "apps/builtin").mkdir(parents=True)
    (package / "apps/builtin/ready.txt").write_text("source")
    monkeypatch.setattr(Path, "symlink_to", _deny_preview_symlinks)
    first = module._ensure_packaged_layout_adapter(package)
    user_file = first / "src/agilab/apps/builtin/user.txt"
    user_file.write_text("preserve added content")
    second = module._ensure_packaged_layout_adapter(package)
    assert second != first
    assert user_file.read_text() == "preserve added content"
    assert not (second / "src/agilab/apps/builtin/user.txt").exists()
    provenance = second / "src/agilab/.apps-copy-source"
    provenance.write_bytes(marker_payload)
    third = module._ensure_packaged_layout_adapter(package)
    assert third not in (first, second)
    assert provenance.read_bytes() == marker_payload
    assert (third / "src/agilab/apps/builtin/ready.txt").read_text() == "source"


@pytest.mark.parametrize("placement", ["app-venv", "nested-src-venv"])
def test_correction_nested_installed_module_never_selects_outer_source(
    correction_context, tmp_path, monkeypatch, placement
):
    import runpy

    module, home, _ = correction_context
    source_text = Path(module.__file__).read_text()
    outer = tmp_path / "outer"
    (outer / "src/agilab/apps/builtin").mkdir(parents=True)
    nested = (
        outer / "src/agilab/apps/example_project/.venv"
        if placement == "app-venv"
        else outer / "src/agilab/tools/src/agilab/.venv"
    )
    package = nested / "lib/python3.13/site-packages/agilab"
    (package / "apps/builtin").mkdir(parents=True)
    builtin = module.__name__.startswith("multi_app_dag.")
    relative_script = (
        "apps/builtin/multi_app_dag_project/src/multi_app_dag/preview_multi_app_dag.py"
        if builtin
        else "examples/inter_project_dag/preview_inter_project_dag.py"
    )
    script = package / relative_script
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(source_text)
    provider = sys.modules[
        "agilab.global_pipeline.global_pipeline_execution_plan"
    ].__file__
    monkeypatch.setattr(module, "__file__", str(script))
    detect = (
        module._repo_root_from_file
        if builtin
        else module._source_checkout_root_from_file
    )
    assert detect() is None
    monkeypatch.setattr(sys, "path", list(sys.path))
    agilab_package = sys.modules["agilab"]
    monkeypatch.setattr(agilab_package, "__path__", list(agilab_package.__path__))
    namespace = runpy.run_path(str(script), run_name="preview_contract_fixture")
    assert str(outer / "src") not in sys.path
    assert (
        sys.modules["agilab.global_pipeline.global_pipeline_execution_plan"].__file__
        == provider
    )
    marker(home, package)
    assert namespace["planning_repo_root"]() != outer
    assert namespace["planning_repo_root"](outer) == outer


def test_correction_concurrent_copy_contexts_finish_independently(
    correction_context, tmp_path, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    module, _, _ = correction_context
    package = tmp_path / "wheel/agilab"
    (package / "apps/builtin").mkdir(parents=True)
    (package / "apps/builtin/ready.txt").write_text("complete")
    monkeypatch.setattr(Path, "symlink_to", _deny_preview_symlinks)
    copytree, rendezvous = module.shutil.copytree, Barrier(2)

    def overlapping_copy(source, destination, *args, **kwargs):
        if Path(source) == package / "apps":
            rendezvous.wait(timeout=5)
        return copytree(source, destination, *args, **kwargs)

    monkeypatch.setattr(module.shutil, "copytree", overlapping_copy)
    with ThreadPoolExecutor(max_workers=2) as pool:
        roots = list(
            pool.map(module._ensure_packaged_layout_adapter, [package, package])
        )
    for root in roots:
        assert (root / "src/agilab/apps/builtin/ready.txt").read_text() == "complete"


def test_correction_copy_cleanup_preserves_replaced_staging(
    correction_context, tmp_path, monkeypatch
):
    module, _, _ = correction_context
    package = tmp_path / "wheel/agilab"
    (package / "apps/builtin").mkdir(parents=True)
    monkeypatch.setattr(Path, "symlink_to", _deny_preview_symlinks)
    copytree = module.shutil.copytree
    replacement = None

    def replace_staging(_source, destination, *args, **kwargs):
        nonlocal replacement
        destination = Path(destination)
        stage = next(
            parent
            for parent in destination.parents
            if parent.name.startswith(".apps-copy-")
        )
        stage.rename(tmp_path / "moved-operation-staging")
        stage.mkdir()
        replacement = stage / "user.txt"
        replacement.write_text("replacement is unknown content")
        raise OSError("injected staging replacement")

    monkeypatch.setattr(module.shutil, "copytree", replace_staging)
    with pytest.raises(OSError, match="injected staging replacement"):
        module._ensure_packaged_layout_adapter(package)
    assert replacement.read_text() == "replacement is unknown content"
    monkeypatch.setattr(module.shutil, "copytree", copytree)
    selected = module._ensure_packaged_layout_adapter(package)
    assert (selected / "src/agilab/apps/builtin").is_dir()
    assert replacement.read_text() == "replacement is unknown content"
