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
