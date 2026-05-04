import os
from pathlib import Path
from unittest import mock

import agi_env.repository_support as repository_support


def test_apps_repository_root_and_pythonpath_helpers(tmp_path: Path, monkeypatch):
    repo_root = tmp_path / "repo"
    apps_root = repo_root / "src" / "agilab" / "apps"
    (apps_root / "alpha_project").mkdir(parents=True)

    mock_logger = mock.Mock()
    assert repository_support.get_apps_repository_root(
        envars={"APPS_REPOSITORY": f"'{repo_root}'"},
        logger=mock_logger,
        fix_windows_drive_fn=lambda value: value,
    ) == apps_root

    alt_repo = tmp_path / "alt-repo"
    alt_apps = alt_repo / "nested" / "apps"
    (alt_apps / "beta_project").mkdir(parents=True)
    assert repository_support.get_apps_repository_root(
        envars={"APPS_REPOSITORY": str(alt_repo)},
        logger=mock_logger,
        fix_windows_drive_fn=lambda value: value,
    ) == alt_apps

    assert repository_support.get_apps_repository_root(
        envars={"APPS_REPOSITORY": str(tmp_path / "missing-repo")},
        logger=mock_logger,
        fix_windows_drive_fn=lambda value: value,
    ) is None
    assert mock_logger.info.called

    package_root = tmp_path / "pkg-root"
    env_pkg = package_root / "envpkg"
    node_pkg = package_root / "nodepkg"
    core_pkg = package_root / "corepkg"
    cluster_pkg = package_root / "clusterpkg"
    for pkg in (env_pkg, node_pkg, core_pkg, cluster_pkg):
        (pkg / "__init__.py").parent.mkdir(parents=True, exist_ok=True)
        (pkg / "__init__.py").write_text("", encoding="utf-8")
    dist_abs = tmp_path / "dist"
    app_src = tmp_path / "app_src"
    wenv_abs = tmp_path / "wenv"
    agilab_pck = tmp_path / "agilab_pck"
    for path in (dist_abs, app_src, wenv_abs / "src", agilab_pck / "agilab"):
        path.mkdir(parents=True, exist_ok=True)

    entries = repository_support.collect_pythonpath_entries(
        env_pck=env_pkg,
        node_pck=node_pkg,
        core_pck=core_pkg,
        cluster_pck=cluster_pkg,
        dist_abs=dist_abs,
        app_src=app_src,
        wenv_abs=wenv_abs,
        agilab_pck=agilab_pck,
    )

    assert repository_support.resolve_package_root(env_pkg) == env_pkg
    assert str(package_root) in entries
    assert str(dist_abs) in entries
    assert str(app_src) in entries
    assert str(wenv_abs / "src") in entries
    assert str(agilab_pck / "agilab") in entries
    assert repository_support.dedupe_existing_paths([dist_abs, dist_abs, tmp_path / "missing"]) == [str(dist_abs)]

    sys_path = ["/existing"]
    monkeypatch.setenv("PYTHONPATH", "/existing")
    repository_support.configure_pythonpath(entries[:2], sys_path=sys_path, environ=os.environ)
    assert entries[0] in sys_path
    assert entries[1] in os.environ["PYTHONPATH"]


def test_resolve_package_root_prefers_src_layout(tmp_path: Path):
    pkg_root = tmp_path / "demo-pkg"
    src_root = pkg_root / "src" / "demo_pkg"
    src_root.mkdir(parents=True)

    assert repository_support.resolve_package_root(pkg_root) == src_root


def test_apps_repository_root_handles_unreadable_alt_apps_dirs(tmp_path: Path, monkeypatch):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    unreadable_apps = repo_root / "nested" / "apps"
    unreadable_apps.mkdir(parents=True)
    mock_logger = mock.Mock()

    original_iterdir = Path.iterdir

    def _broken_iterdir(self):
        if self == unreadable_apps:
            raise OSError("no access")
        return original_iterdir(self)

    monkeypatch.setattr(repository_support.Path, "iterdir", _broken_iterdir, raising=False)

    assert repository_support.get_apps_repository_root(
        envars={"APPS_REPOSITORY": str(repo_root)},
        logger=mock_logger,
        fix_windows_drive_fn=lambda value: value,
    ) is None
    assert mock_logger.info.called


def test_apps_repository_root_uses_process_env_handles_blank_values_and_logs_outer_scan_error(
    tmp_path: Path,
    monkeypatch,
):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    mock_logger = mock.Mock()
    empty_logger = mock.Mock()

    monkeypatch.delenv("APPS_REPOSITORY", raising=False)
    assert repository_support.get_apps_repository_root(
        envars=None,
        logger=empty_logger,
        fix_windows_drive_fn=lambda value: value,
    ) is None

    monkeypatch.setenv("APPS_REPOSITORY", str(repo_root))
    assert repository_support.get_apps_repository_root(
        envars=None,
        logger=mock_logger,
        fix_windows_drive_fn=lambda value: value,
    ) is None
    assert mock_logger.info.called

    assert repository_support.get_apps_repository_root(
        envars={"APPS_REPOSITORY": '   ""   '},
        logger=mock_logger,
        fix_windows_drive_fn=lambda value: value,
    ) is None

    original_glob = Path.glob

    def _broken_glob(self, pattern):
        if self == repo_root and pattern == "**/apps":
            raise OSError("scan failure")
        return original_glob(self, pattern)

    monkeypatch.setattr(repository_support.Path, "glob", _broken_glob, raising=False)

    assert repository_support.get_apps_repository_root(
        envars={"APPS_REPOSITORY": str(repo_root)},
        logger=mock_logger,
        fix_windows_drive_fn=lambda value: value,
    ) is None
    assert mock_logger.debug.called


def test_dedupe_existing_paths_skips_falsey_and_empty_values(tmp_path: Path):
    existing = tmp_path / "existing"
    existing.mkdir()

    assert repository_support.dedupe_existing_paths(
        [None, "", existing, existing, "   ", tmp_path / "missing"]
    ) == [str(existing)]


def test_collect_pythonpath_entries_handles_typeerror_in_import_root(tmp_path: Path):
    class _BrokenImportRoot:
        def __truediv__(self, _other):
            raise TypeError("path join bug")

        def __str__(self):
            return str(tmp_path / "broken-root")

    class _Pkg:
        def __init__(self, parent):
            self.parent = parent

    captured = {}

    def _capture_paths(paths):
        captured["paths"] = list(paths)
        return ["captured"]

    result = repository_support.collect_pythonpath_entries(
        env_pck=_Pkg(_BrokenImportRoot()),
        node_pck=tmp_path / "nodepkg",
        core_pck=tmp_path / "corepkg",
        cluster_pck=tmp_path / "clusterpkg",
        dist_abs=tmp_path / "dist",
        app_src=tmp_path / "app_src",
        wenv_abs=tmp_path / "wenv",
        agilab_pck=tmp_path / "agilab_pck",
        dedupe_paths_fn=_capture_paths,
    )

    assert result == ["captured"]
    assert captured["paths"][0].__class__.__name__ == "_BrokenImportRoot"


def test_collect_pythonpath_entries_uses_parent_when_init_file_exists(tmp_path: Path):
    package_parent = tmp_path / "pkg_parent"
    package_parent.mkdir()
    (package_parent / "__init__.py").write_text("", encoding="utf-8")
    env_pck = package_parent / "childpkg"
    env_pck.mkdir()

    node_pkg = tmp_path / "nodepkg"
    core_pkg = tmp_path / "corepkg"
    cluster_pkg = tmp_path / "clusterpkg"
    for pkg in (node_pkg, core_pkg, cluster_pkg):
        pkg.mkdir()

    entries = repository_support.collect_pythonpath_entries(
        env_pck=env_pck,
        node_pck=node_pkg,
        core_pck=core_pkg,
        cluster_pck=cluster_pkg,
        dist_abs=tmp_path / "dist",
        app_src=tmp_path / "app_src",
        wenv_abs=tmp_path / "wenv",
        agilab_pck=tmp_path / "agilab_pck",
        dedupe_paths_fn=lambda paths: [str(path) for path in paths],
    )

    assert entries[0] == str(package_parent.parent)


def test_collect_pythonpath_entries_keeps_src_layout_root_with_init_file(tmp_path: Path):
    src_root = tmp_path / "pkg" / "src"
    src_root.mkdir(parents=True)
    (src_root / "__init__.py").write_text("", encoding="utf-8")
    env_pck = src_root / "agi_env"
    env_pck.mkdir()

    node_pck = tmp_path / "node" / "src" / "agi_node"
    core_pck = tmp_path / "core" / "src" / "agi_core"
    cluster_pck = tmp_path / "cluster" / "src" / "agi_cluster"
    for pkg in (node_pck, core_pck, cluster_pck):
        pkg.mkdir(parents=True)

    entries = repository_support.collect_pythonpath_entries(
        env_pck=env_pck,
        node_pck=node_pck,
        core_pck=core_pck,
        cluster_pck=cluster_pck,
        dist_abs=tmp_path / "dist",
        app_src=tmp_path / "app_src",
        wenv_abs=tmp_path / "wenv",
        agilab_pck=tmp_path / "agilab_pck",
        dedupe_paths_fn=lambda paths: [str(path) for path in paths],
    )

    assert entries[0] == str(src_root)
    assert entries[1] == str(node_pck.parent)


def test_configure_pythonpath_handles_empty_entries_and_preserves_existing_order():
    sys_path = ["/already-present"]
    environ = {}

    repository_support.configure_pythonpath([], sys_path=sys_path, environ=environ)
    assert sys_path == ["/already-present"]
    assert "PYTHONPATH" not in environ

    repository_support.configure_pythonpath(
        ["/already-present", "/new-entry"],
        sys_path=sys_path,
        environ=environ,
    )

    assert sys_path == ["/already-present", "/new-entry"]
    assert environ["PYTHONPATH"] == os.pathsep.join(["/already-present", "/new-entry"])


def test_configure_pythonpath_skips_duplicate_current_pythonpath_entries():
    sys_path = ["/alpha"]
    environ = {"PYTHONPATH": os.pathsep.join(["/alpha", "/beta"])}

    repository_support.configure_pythonpath(
        ["/alpha", "/gamma"],
        sys_path=sys_path,
        environ=environ,
    )

    assert sys_path == ["/alpha", "/gamma"]
    assert environ["PYTHONPATH"] == os.pathsep.join(["/alpha", "/gamma", "/beta"])


def test_apps_repository_root_returns_none_when_alt_apps_has_no_project(tmp_path: Path):
    repo_root = tmp_path / "repo"
    alt_apps = repo_root / "nested" / "apps"
    (alt_apps / "docs").mkdir(parents=True)
    mock_logger = mock.Mock()

    assert repository_support.get_apps_repository_root(
        envars={"APPS_REPOSITORY": str(repo_root)},
        logger=mock_logger,
        fix_windows_drive_fn=lambda value: value,
    ) is None
    assert mock_logger.info.called


def test_apps_repository_root_handles_outer_scan_error_without_logger(tmp_path: Path, monkeypatch):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    original_glob = Path.glob

    def _broken_glob(self, pattern):
        if self == repo_root and pattern == "**/apps":
            raise OSError("scan failure")
        return original_glob(self, pattern)

    monkeypatch.setattr(repository_support.Path, "glob", _broken_glob, raising=False)

    assert repository_support.get_apps_repository_root(
        envars={"APPS_REPOSITORY": str(repo_root)},
        logger=None,
        fix_windows_drive_fn=lambda value: value,
    ) is None


def test_dedupe_existing_paths_skips_objects_with_empty_string_representation(tmp_path: Path):
    existing = tmp_path / "existing"
    existing.mkdir()

    class _EmptyStringPath:
        def __bool__(self):
            return True

        def __str__(self):
            return ""

    assert repository_support.dedupe_existing_paths([_EmptyStringPath(), existing]) == [str(existing)]
