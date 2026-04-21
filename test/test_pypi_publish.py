from __future__ import annotations

import importlib.util
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


MODULE_PATH = Path("tools/pypi_publish.py").resolve()


def _load_pypi_publish():
    spec = importlib.util.spec_from_file_location("pypi_publish_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_shields_badge_uses_stable_cache_endpoint() -> None:
    module = _load_pypi_publish()

    badge = module.shields_badge("2026.03.23", "agilab")

    assert "https://img.shields.io/pypi/v/agilab.svg?cacheSeconds=300" in badge


def test_update_badge_rewrites_readme_link(tmp_path, monkeypatch) -> None:
    module = _load_pypi_publish()
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)

    readme = tmp_path / "README.md"
    readme.write_text(
        "[![PyPI version](https://img.shields.io/pypi/v/agilab.svg)]"
        "(https://pypi.org/project/agilab/)\n",
        encoding="utf-8",
    )

    changed = module.update_badge(readme, "agilab", "2026.03.23")

    assert changed is True
    assert "https://img.shields.io/pypi/v/agilab.svg?cacheSeconds=300" in readme.read_text(encoding="utf-8")


def test_update_badge_is_noop_when_pattern_is_missing(tmp_path, monkeypatch) -> None:
    module = _load_pypi_publish()
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)

    readme = tmp_path / "README.md"
    readme.write_text("No badge here.\n", encoding="utf-8")

    changed = module.update_badge(readme, "agilab", "2026.03.23")

    assert changed is False
    assert readme.read_text(encoding="utf-8") == "No badge here.\n"


def test_update_badge_is_noop_when_badge_is_already_current(tmp_path, monkeypatch) -> None:
    module = _load_pypi_publish()
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)

    current = "[![PyPI version](https://img.shields.io/pypi/v/agilab.svg?cacheSeconds=300)](https://pypi.org/project/agilab/)\n"
    readme = tmp_path / "README.md"
    readme.write_text(current, encoding="utf-8")

    changed = module.update_badge(readme, "agilab", "2026.03.23")

    assert changed is False
    assert readme.read_text(encoding="utf-8") == current


def test_render_static_badge_svg_expands_for_post_release() -> None:
    module = _load_pypi_publish()

    badge = module.render_static_badge_svg("2026.04.07.post1")

    assert 'aria-label="pypi: v2026.04.07.post1"' in badge
    assert 'width="158"' in badge
    assert ">v2026.04.07.post1</text>" in badge


def test_update_static_badge_rewrites_svg(tmp_path, monkeypatch) -> None:
    module = _load_pypi_publish()
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)

    badge = tmp_path / "badges" / "pypi-version-agilab.svg"
    badge.parent.mkdir(parents=True)
    badge.write_text(module.render_static_badge_svg("2026.04.07"), encoding="utf-8")

    changed = module.update_static_badge(badge, "2026.04.07.post1")

    assert changed is True
    text = badge.read_text(encoding="utf-8")
    assert 'aria-label="pypi: v2026.04.07.post1"' in text
    assert 'width="158"' in text


def test_fetch_url_text_falls_back_to_curl(monkeypatch) -> None:
    module = _load_pypi_publish()

    def _raise(*_args, **_kwargs):
        raise RuntimeError("urllib down")

    monkeypatch.setattr(module.urllib.request, "urlopen", _raise)
    monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/bin/curl" if name == "curl" else None)
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout="simple body", stderr=""),
    )

    assert module.fetch_url_text("https://example.test") == "simple body"


def test_pypi_releases_uses_simple_index_when_json_is_stale(monkeypatch) -> None:
    module = _load_pypi_publish()

    monkeypatch.setattr(module, "fetch_url_json", lambda *_args, **_kwargs: {"releases": {"2026.4.18": []}})
    monkeypatch.setattr(
        module,
        "fetch_url_text",
        lambda *_args, **_kwargs: '<a href="https://files.pythonhosted.org/packages/x/agilab-2026.4.19.tar.gz">agilab-2026.4.19.tar.gz</a>',
    )

    assert module.pypi_releases("agilab", "pypi") == {"2026.4.18", "2026.4.19"}


def test_require_safe_pypi_release_rejects_missing_repo_sync_flags() -> None:
    module = _load_pypi_publish()

    cfg = module.Cfg(
        repo="pypi",
        dist="both",
        skip_existing=True,
        retries=1,
        dry_run=False,
        verbose=False,
        version=None,
        purge_before=False,
        purge_after=False,
        cleanup_only=False,
        clean_days=None,
        clean_delete_project=False,
        cleanup_user=None,
        cleanup_pass=None,
        cleanup_timeout=0,
        skip_cleanup=True,
        yank_previous=False,
        git_tag=False,
        git_commit_version=False,
        git_reset_on_failure=False,
        pypirc_check=False,
        packages=["agilab"],
        gen_docs=False,
    )

    try:
        module.require_safe_pypi_release(cfg)
    except SystemExit as exc:
        assert "--git-commit-version" in str(exc)
        assert "--git-tag" in str(exc)
        assert "--git-reset-on-failure" in str(exc)
    else:
        raise AssertionError("require_safe_pypi_release() should reject unsafe real PyPI publish settings")


def test_require_safe_pypi_release_rejects_skipping_release_preflight() -> None:
    module = _load_pypi_publish()

    cfg = module.Cfg(
        repo="pypi",
        dist="both",
        skip_existing=True,
        retries=1,
        dry_run=False,
        verbose=False,
        version=None,
        purge_before=False,
        purge_after=False,
        cleanup_only=False,
        clean_days=None,
        clean_delete_project=False,
        cleanup_user=None,
        cleanup_pass=None,
        cleanup_timeout=0,
        skip_cleanup=True,
        yank_previous=False,
        git_tag=True,
        git_commit_version=True,
        git_reset_on_failure=True,
        pypirc_check=False,
        packages=["agilab"],
        gen_docs=False,
        release_preflight=False,
    )

    try:
        module.require_safe_pypi_release(cfg)
    except SystemExit as exc:
        assert "--skip-release-preflight" in str(exc)
    else:
        raise AssertionError("require_safe_pypi_release() should reject skipping real release preflight")


def test_release_preflight_profiles_only_for_real_pypi() -> None:
    module = _load_pypi_publish()

    assert module.release_preflight_profiles(module.Cfg(repo="testpypi", dist="both", skip_existing=True, retries=1, dry_run=False, verbose=False, version=None, purge_before=False, purge_after=False, cleanup_only=False, clean_days=None, clean_delete_project=False, cleanup_user=None, cleanup_pass=None, cleanup_timeout=0, skip_cleanup=True, yank_previous=False, git_tag=False, git_commit_version=False, git_reset_on_failure=False, pypirc_check=False, packages=None, gen_docs=False)) == []

    profiles = module.release_preflight_profiles(
        module.Cfg(
            repo="pypi",
            dist="both",
            skip_existing=True,
            retries=1,
            dry_run=False,
            verbose=False,
            version=None,
            purge_before=False,
            purge_after=False,
            cleanup_only=False,
            clean_days=None,
            clean_delete_project=False,
            cleanup_user=None,
            cleanup_pass=None,
            cleanup_timeout=0,
            skip_cleanup=True,
            yank_previous=False,
            git_tag=True,
            git_commit_version=True,
            git_reset_on_failure=True,
            pypirc_check=False,
            packages=["agilab"],
            gen_docs=False,
        )
    )

    assert profiles == ["agi-env", "agi-node", "agi-cluster", "agi-gui", "docs", "installer", "shared-core-typing"]


def test_compute_date_tag_without_collision(monkeypatch) -> None:
    module = _load_pypi_publish()

    class _FixedDatetime:
        @staticmethod
        def now(_tz):
            return datetime(2026, 3, 20, 10, 0, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(module, "datetime", _FixedDatetime)
    monkeypatch.setattr(module, "_tag_exists", lambda _tag, repo=None: False)

    assert module.compute_date_tag() == "2026.03.20"


def test_compute_date_tag_with_collisions(monkeypatch) -> None:
    module = _load_pypi_publish()

    class _FixedDatetime:
        @staticmethod
        def now(_tz):
            return datetime(2026, 3, 20, 10, 0, 0, tzinfo=timezone.utc)

    existing = {"v2026.03.20", "v2026.03.20-2"}
    monkeypatch.setattr(module, "datetime", _FixedDatetime)
    monkeypatch.setattr(module, "_tag_exists", lambda tag, repo=None: tag in existing)

    assert module.compute_date_tag() == "2026.03.20-3"


def test_git_paths_to_commit_collects_expected_files_without_duplicates(tmp_path, monkeypatch) -> None:
    module = _load_pypi_publish()
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)

    core_dir = tmp_path / "core" / "agi-env"
    core_dir.mkdir(parents=True)
    core_toml = core_dir / "pyproject.toml"
    core_toml.write_text("[project]\nname='agi-env'\nversion='1.0.0'\n", encoding="utf-8")
    core_readme = core_dir / "README.md"
    core_readme.write_text("core\n", encoding="utf-8")

    umbrella_dir = tmp_path
    umbrella_toml = umbrella_dir / "pyproject.toml"
    umbrella_toml.write_text("[project]\nname='agilab'\nversion='1.0.0'\n", encoding="utf-8")
    umbrella_readme = umbrella_dir / "README.md"
    umbrella_readme.write_text("umbrella\n", encoding="utf-8")
    umbrella_badge = tmp_path / "badges" / "pypi-version-agilab.svg"
    umbrella_badge.parent.mkdir(parents=True)
    umbrella_badge.write_text("badge\n", encoding="utf-8")

    builtin_dir = tmp_path / "src" / "agilab" / "apps" / "builtin" / "flight_project"
    builtin_dir.mkdir(parents=True)
    builtin_toml = builtin_dir / "pyproject.toml"
    builtin_toml.write_text("[project]\nname='flight_project'\nversion='1.0.0'\n", encoding="utf-8")

    monkeypatch.setattr(module, "CORE", [("agi-env", core_toml, core_dir)])
    monkeypatch.setattr(module, "UMBRELLA", ("agilab", umbrella_toml, umbrella_dir))
    monkeypatch.setattr(module, "builtin_app_pyprojects", lambda: [builtin_toml, builtin_toml])

    paths = module.git_paths_to_commit(include_docs=True)

    assert paths == [
        "core/agi-env/pyproject.toml",
        "core/agi-env/README.md",
        "pyproject.toml",
        "src/agilab/apps/builtin/flight_project/pyproject.toml",
        "README.md",
        "badges/pypi-version-agilab.svg",
    ]


def test_main_rejects_invalid_explicit_version(monkeypatch) -> None:
    module = _load_pypi_publish()

    cfg = module.Cfg(
        repo="testpypi",
        dist="both",
        skip_existing=True,
        retries=1,
        dry_run=False,
        verbose=False,
        version="2026-03-23",
        purge_before=False,
        purge_after=False,
        cleanup_only=False,
        clean_days=None,
        clean_delete_project=False,
        cleanup_user=None,
        cleanup_pass=None,
        cleanup_timeout=0,
        skip_cleanup=True,
        yank_previous=False,
        git_tag=False,
        git_commit_version=False,
        git_reset_on_failure=False,
        pypirc_check=False,
        packages=["agi-env"],
        gen_docs=False,
    )

    monkeypatch.setattr(module, "parse_args", lambda: object())
    monkeypatch.setattr(module, "make_cfg", lambda _args: cfg)

    try:
        module.main()
    except SystemExit as exc:
        assert "Invalid --version format" in str(exc)
    else:
        raise AssertionError("main() should reject an invalid explicit version")


def test_main_rejects_real_pypi_publish_without_repo_sync_flags(monkeypatch) -> None:
    module = _load_pypi_publish()

    cfg = module.Cfg(
        repo="pypi",
        dist="both",
        skip_existing=True,
        retries=1,
        dry_run=False,
        verbose=False,
        version=None,
        purge_before=False,
        purge_after=False,
        cleanup_only=False,
        clean_days=None,
        clean_delete_project=False,
        cleanup_user=None,
        cleanup_pass=None,
        cleanup_timeout=0,
        skip_cleanup=True,
        yank_previous=False,
        git_tag=False,
        git_commit_version=False,
        git_reset_on_failure=False,
        pypirc_check=False,
        packages=["agilab"],
        gen_docs=False,
    )

    monkeypatch.setattr(module, "parse_args", lambda: object())
    monkeypatch.setattr(module, "make_cfg", lambda _args: cfg)

    try:
        module.main()
    except SystemExit as exc:
        assert "Real PyPI releases must run with" in str(exc)
    else:
        raise AssertionError("main() should reject unsafe real PyPI publish settings")


def test_main_rejects_explicit_version_lower_than_latest_release(tmp_path, monkeypatch) -> None:
    module = _load_pypi_publish()

    project_dir = tmp_path / "agi-env"
    project_dir.mkdir()
    pyproject = project_dir / "pyproject.toml"
    pyproject.write_text(
        "[project]\nname = 'agi-env'\nversion = '2026.03.16'\ndependencies = []\n",
        encoding="utf-8",
    )

    cfg = module.Cfg(
        repo="testpypi",
        dist="both",
        skip_existing=True,
        retries=1,
        dry_run=False,
        verbose=False,
        version="2026.03.22",
        purge_before=False,
        purge_after=False,
        cleanup_only=False,
        clean_days=None,
        clean_delete_project=False,
        cleanup_user=None,
        cleanup_pass=None,
        cleanup_timeout=0,
        skip_cleanup=True,
        yank_previous=False,
        git_tag=False,
        git_commit_version=False,
        git_reset_on_failure=False,
        pypirc_check=False,
        packages=["agi-env"],
        gen_docs=False,
    )

    monkeypatch.setattr(module, "parse_args", lambda: object())
    monkeypatch.setattr(module, "make_cfg", lambda _args: cfg)
    monkeypatch.setattr(module, "CORE", [("agi-env", pyproject, project_dir)])
    monkeypatch.setattr(module, "pypi_releases", lambda *_args, **_kwargs: {"2026.03.23"})

    try:
        module.main()
    except SystemExit as exc:
        assert "is lower than existing release 2026.03.23" in str(exc)
    else:
        raise AssertionError("main() should reject a lower explicit version")


def test_main_updates_badges_before_build(tmp_path, monkeypatch) -> None:
    module = _load_pypi_publish()

    project_dir = tmp_path / "agi-env"
    project_dir.mkdir()
    pyproject = project_dir / "pyproject.toml"
    pyproject.write_text(
        "\n".join(
            [
                "[project]",
                'name = "agi-env"',
                'version = "2026.03.16"',
                'dependencies = []',
                "",
            ]
        ),
        encoding="utf-8",
    )

    order: list[str] = []

    cfg = module.Cfg(
        repo="testpypi",
        dist="both",
        skip_existing=True,
        retries=1,
        dry_run=False,
        verbose=False,
        version="2026.03.23",
        purge_before=False,
        purge_after=False,
        cleanup_only=False,
        clean_days=None,
        clean_delete_project=False,
        cleanup_user=None,
        cleanup_pass=None,
        cleanup_timeout=0,
        skip_cleanup=True,
        yank_previous=False,
        git_tag=False,
        git_commit_version=False,
        git_reset_on_failure=True,
        pypirc_check=False,
        packages=["agi-env"],
        gen_docs=False,
    )

    monkeypatch.setattr(module, "parse_args", lambda: object())
    monkeypatch.setattr(module, "make_cfg", lambda _args: cfg)
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "CORE", [("agi-env", pyproject, project_dir)])
    monkeypatch.setattr(module, "UMBRELLA", ("agilab", tmp_path / "missing.toml", tmp_path))
    monkeypatch.setattr(module, "pypi_releases", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(module, "remove_symlinks_for_umbrella", lambda: [])
    monkeypatch.setattr(module, "restore_symlinks", lambda _entries: None)
    monkeypatch.setattr(module, "sync_builtin_app_versions", lambda _version: None)
    monkeypatch.setattr(module, "dist_files", lambda _project_dir: [str(project_dir / "dist" / "fake.whl")])
    monkeypatch.setattr(module, "twine_check", lambda _files: None)
    monkeypatch.setattr(module, "twine_upload", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "update_selected_badges", lambda *_args, **_kwargs: order.append("badge"))
    monkeypatch.setattr(module, "uv_build_project", lambda *_args, **_kwargs: order.append("build"))

    module.main()

    assert order[:2] == ["badge", "build"]


def test_main_runs_release_preflight_before_build(tmp_path, monkeypatch) -> None:
    module = _load_pypi_publish()

    project_dir = tmp_path / "agi-env"
    project_dir.mkdir()
    pyproject = project_dir / "pyproject.toml"
    pyproject.write_text(
        "\n".join(
            [
                "[project]",
                'name = "agi-env"',
                'version = "2026.03.16"',
                'dependencies = []',
                "",
            ]
        ),
        encoding="utf-8",
    )

    order: list[str] = []

    cfg = module.Cfg(
        repo="pypi",
        dist="both",
        skip_existing=True,
        retries=1,
        dry_run=False,
        verbose=False,
        version="2026.03.23",
        purge_before=False,
        purge_after=False,
        cleanup_only=False,
        clean_days=None,
        clean_delete_project=False,
        cleanup_user=None,
        cleanup_pass=None,
        cleanup_timeout=0,
        skip_cleanup=True,
        yank_previous=False,
        git_tag=True,
        git_commit_version=True,
        git_reset_on_failure=True,
        pypirc_check=False,
        packages=["agi-env"],
        gen_docs=False,
    )

    monkeypatch.setattr(module, "parse_args", lambda: object())
    monkeypatch.setattr(module, "make_cfg", lambda _args: cfg)
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "CORE", [("agi-env", pyproject, project_dir)])
    monkeypatch.setattr(module, "UMBRELLA", ("agilab", tmp_path / "missing.toml", tmp_path))
    monkeypatch.setattr(module, "pypi_releases", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(module, "remove_symlinks_for_umbrella", lambda: [])
    monkeypatch.setattr(module, "restore_symlinks", lambda _entries: None)
    monkeypatch.setattr(module, "sync_builtin_app_versions", lambda _version: None)
    monkeypatch.setattr(module, "dist_files", lambda _project_dir: [str(project_dir / "dist" / "fake.whl")])
    monkeypatch.setattr(module, "twine_check", lambda _files: None)
    monkeypatch.setattr(module, "twine_upload", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "update_selected_badges", lambda *_args, **_kwargs: order.append("badge"))
    monkeypatch.setattr(module, "uv_build_project", lambda *_args, **_kwargs: order.append("build"))
    monkeypatch.setattr(module, "run_release_preflight", lambda _cfg: order.append("preflight"))
    monkeypatch.setattr(module, "git_commit_version", lambda *_args, **_kwargs: order.append("commit"))
    monkeypatch.setattr(module, "compute_date_tag", lambda: "2026.03.23")
    monkeypatch.setattr(module, "create_and_push_tag", lambda *_args, **_kwargs: order.append("tag"))

    module.main()

    assert order[:3] == ["preflight", "badge", "build"]


def test_main_dry_run_restores_release_files(tmp_path, monkeypatch) -> None:
    module = _load_pypi_publish()

    project_dir = tmp_path / "agi-env"
    project_dir.mkdir(parents=True)
    pyproject = project_dir / "pyproject.toml"
    original_text = (
        "[project]\n"
        "name = 'agi-env'\n"
        "version = '2026.03.16'\n"
        "dependencies = []\n"
    )
    pyproject.write_text(original_text, encoding="utf-8")

    cfg = module.Cfg(
        repo="testpypi",
        dist="both",
        skip_existing=True,
        retries=1,
        dry_run=True,
        verbose=False,
        version="2026.03.23",
        purge_before=False,
        purge_after=False,
        cleanup_only=False,
        clean_days=None,
        clean_delete_project=False,
        cleanup_user=None,
        cleanup_pass=None,
        cleanup_timeout=0,
        skip_cleanup=True,
        yank_previous=False,
        git_tag=False,
        git_commit_version=False,
        git_reset_on_failure=False,
        pypirc_check=False,
        packages=["agi-env"],
        gen_docs=False,
    )

    monkeypatch.setattr(module, "parse_args", lambda: object())
    monkeypatch.setattr(module, "make_cfg", lambda _args: cfg)
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "CORE", [("agi-env", pyproject, project_dir)])
    monkeypatch.setattr(module, "UMBRELLA", ("agilab", tmp_path / "missing.toml", tmp_path))
    monkeypatch.setattr(module, "pypi_releases", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(module, "remove_symlinks_for_umbrella", lambda: [])
    monkeypatch.setattr(module, "restore_symlinks", lambda _entries: None)
    monkeypatch.setattr(module, "sync_builtin_app_versions", lambda _version: None)
    monkeypatch.setattr(module, "dist_files", lambda _project_dir: [])
    monkeypatch.setattr(module, "update_selected_badges", lambda *_args, **_kwargs: None)

    module.main()

    assert pyproject.read_text(encoding="utf-8") == original_text


def test_main_refreshes_badges_before_collision_rebuild(tmp_path, monkeypatch) -> None:
    module = _load_pypi_publish()

    project_dir = tmp_path / "agi-env"
    project_dir.mkdir()
    pyproject = project_dir / "pyproject.toml"
    pyproject.write_text(
        "\n".join(
            [
                "[project]",
                'name = "agi-env"',
                'version = "2026.03.16"',
                'dependencies = []',
                "",
            ]
        ),
        encoding="utf-8",
    )

    order: list[str] = []
    upload_calls = {"count": 0}

    cfg = module.Cfg(
        repo="testpypi",
        dist="both",
        skip_existing=True,
        retries=1,
        dry_run=False,
        verbose=False,
        version="2026.03.23.post1",
        purge_before=False,
        purge_after=False,
        cleanup_only=False,
        clean_days=None,
        clean_delete_project=False,
        cleanup_user=None,
        cleanup_pass=None,
        cleanup_timeout=0,
        skip_cleanup=True,
        yank_previous=False,
        git_tag=False,
        git_commit_version=False,
        git_reset_on_failure=False,
        pypirc_check=False,
        packages=["agi-env"],
        gen_docs=False,
    )

    def _twine_upload(*_args, **_kwargs):
        upload_calls["count"] += 1
        if upload_calls["count"] == 1:
            module.UPLOAD_COLLISION_DETECTED = True
            module.UPLOAD_SUCCESS_COUNT = 0
        else:
            module.UPLOAD_COLLISION_DETECTED = False
            module.UPLOAD_SUCCESS_COUNT = 1

    monkeypatch.setattr(module, "parse_args", lambda: object())
    monkeypatch.setattr(module, "make_cfg", lambda _args: cfg)
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "CORE", [("agi-env", pyproject, project_dir)])
    monkeypatch.setattr(module, "UMBRELLA", ("agilab", tmp_path / "missing.toml", tmp_path))
    monkeypatch.setattr(module, "pypi_releases", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(module, "remove_symlinks_for_umbrella", lambda: [])
    monkeypatch.setattr(module, "restore_symlinks", lambda _entries: None)
    monkeypatch.setattr(module, "sync_builtin_app_versions", lambda _version: None)
    monkeypatch.setattr(module, "dist_files", lambda _project_dir: [str(project_dir / "dist" / "fake.whl")])
    monkeypatch.setattr(module, "twine_check", lambda _files: None)
    monkeypatch.setattr(module, "twine_upload", _twine_upload)
    monkeypatch.setattr(module, "update_selected_badges", lambda *_args, **_kwargs: order.append("badge"))
    monkeypatch.setattr(module, "uv_build_project", lambda *_args, **_kwargs: order.append("build"))
    monkeypatch.setattr(module, "next_free_post_for_all", lambda *_args, **_kwargs: "2026.03.23.post2")

    module.main()

    assert order[:4] == ["badge", "build", "badge", "build"]


def test_twine_upload_reports_summary_and_skip_existing(monkeypatch, capsys) -> None:
    module = _load_pypi_publish()

    files = ["first.whl", "second.whl"]
    calls = {"count": 0}

    def _fake_run(_cmd, cwd=None, text=None, capture_output=None, env=None):
        calls["count"] += 1
        if calls["count"] == 1:
            return subprocess.CompletedProcess(_cmd, 0, stdout="ok", stderr="")
        return subprocess.CompletedProcess(
            _cmd,
            1,
            stdout="",
            stderr="HTTPError: 400 Bad Request from already used filename",
        )

    monkeypatch.setattr(module.subprocess, "run", _fake_run)

    module.twine_upload(files, "pypi", True, 1)

    out = capsys.readouterr().out
    assert "[upload] uploaded: first.whl" in out
    assert "[upload] skipped existing (already on server): second.whl" in out
    assert "[upload] summary: uploaded=1 skipped_existing=1 total=2 repo=pypi" in out
    assert module.UPLOAD_SUCCESS_COUNT == 1
    assert module.UPLOAD_SKIPPED_EXISTING_COUNT == 1


def test_main_does_not_reset_release_files_after_success(tmp_path, monkeypatch) -> None:
    module = _load_pypi_publish()

    project_dir = tmp_path / "agi-env"
    project_dir.mkdir()
    pyproject = project_dir / "pyproject.toml"
    pyproject.write_text(
        "[project]\nname = 'agi-env'\nversion = '2026.03.16'\ndependencies = []\n",
        encoding="utf-8",
    )

    cfg = module.Cfg(
        repo="testpypi",
        dist="both",
        skip_existing=True,
        retries=1,
        dry_run=False,
        verbose=False,
        version="2026.03.23",
        purge_before=False,
        purge_after=False,
        cleanup_only=False,
        clean_days=None,
        clean_delete_project=False,
        cleanup_user=None,
        cleanup_pass=None,
        cleanup_timeout=0,
        skip_cleanup=True,
        yank_previous=False,
        git_tag=False,
        git_commit_version=False,
        git_reset_on_failure=True,
        pypirc_check=False,
        packages=["agi-env"],
        gen_docs=False,
    )

    reset_calls: list[str] = []

    monkeypatch.setattr(module, "parse_args", lambda: object())
    monkeypatch.setattr(module, "make_cfg", lambda _args: cfg)
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "CORE", [("agi-env", pyproject, project_dir)])
    monkeypatch.setattr(module, "UMBRELLA", ("agilab", tmp_path / "missing.toml", tmp_path))
    monkeypatch.setattr(module, "pypi_releases", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(module, "remove_symlinks_for_umbrella", lambda: [])
    monkeypatch.setattr(module, "restore_symlinks", lambda _entries: None)
    monkeypatch.setattr(module, "sync_builtin_app_versions", lambda _version: None)
    monkeypatch.setattr(module, "dist_files", lambda _project_dir: [str(project_dir / "dist" / "fake.whl")])
    monkeypatch.setattr(module, "twine_check", lambda _files: None)
    monkeypatch.setattr(module, "twine_upload", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "update_selected_badges", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "uv_build_project", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "git_reset_pyprojects", lambda: reset_calls.append("reset"))

    module.main()

    assert reset_calls == []


def test_main_commits_before_tagging(tmp_path, monkeypatch) -> None:
    module = _load_pypi_publish()

    project_dir = tmp_path / "agi-env"
    project_dir.mkdir()
    pyproject = project_dir / "pyproject.toml"
    pyproject.write_text(
        "[project]\nname = 'agi-env'\nversion = '2026.03.16'\ndependencies = []\n",
        encoding="utf-8",
    )

    cfg = module.Cfg(
        repo="pypi",
        dist="both",
        skip_existing=True,
        retries=1,
        dry_run=False,
        verbose=False,
        version="2026.03.23",
        purge_before=False,
        purge_after=False,
        cleanup_only=False,
        clean_days=None,
        clean_delete_project=False,
        cleanup_user=None,
        cleanup_pass=None,
        cleanup_timeout=0,
        skip_cleanup=True,
        yank_previous=False,
        git_tag=True,
        git_commit_version=True,
        git_reset_on_failure=True,
        pypirc_check=False,
        packages=["agi-env"],
        gen_docs=False,
    )

    order: list[str] = []

    monkeypatch.setattr(module, "parse_args", lambda: object())
    monkeypatch.setattr(module, "make_cfg", lambda _args: cfg)
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "CORE", [("agi-env", pyproject, project_dir)])
    monkeypatch.setattr(module, "UMBRELLA", ("agilab", tmp_path / "missing.toml", tmp_path))
    monkeypatch.setattr(module, "pypi_releases", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(module, "remove_symlinks_for_umbrella", lambda: [])
    monkeypatch.setattr(module, "restore_symlinks", lambda _entries: None)
    monkeypatch.setattr(module, "sync_builtin_app_versions", lambda _version: None)
    monkeypatch.setattr(module, "dist_files", lambda _project_dir: [str(project_dir / "dist" / "fake.whl")])
    monkeypatch.setattr(module, "twine_check", lambda _files: None)
    monkeypatch.setattr(module, "twine_upload", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "update_selected_badges", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "uv_build_project", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "run_release_preflight", lambda _cfg: order.append("preflight"))
    monkeypatch.setattr(module, "git_commit_version", lambda *_args, **_kwargs: order.append("commit"))
    monkeypatch.setattr(module, "compute_date_tag", lambda: "2026.03.23")
    monkeypatch.setattr(module, "create_and_push_tag", lambda *_args, **_kwargs: order.append("tag"))

    module.main()

    assert order == ["preflight", "commit", "tag"]


def test_git_commit_version_pushes_branch_when_requested(monkeypatch) -> None:
    module = _load_pypi_publish()

    calls: list[list[str]] = []

    monkeypatch.setattr(module, "git_paths_to_commit", lambda include_docs=False: ["pyproject.toml"])
    monkeypatch.setattr(module, "current_git_branch", lambda repo=module.REPO_ROOT: "main")
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(["git"], 1),
    )
    monkeypatch.setattr(module, "run", lambda cmd, cwd=None, env=None, timeout=None: calls.append(cmd))

    module.git_commit_version("2026.03.23", push=True)

    assert calls == [
        ["git", "add", "pyproject.toml"],
        ["git", "commit", "-m", "chore(release): bump version to 2026.03.23"],
        ["git", "push", "origin", "main"],
    ]


def test_ensure_docs_repo_release_ready_rejects_unrelated_dirty_paths(tmp_path, monkeypatch) -> None:
    module = _load_pypi_publish()

    docs_repo = tmp_path / "thales_agilab"
    docs_repo.mkdir()

    monkeypatch.setattr(module, "_git_status_paths", lambda _repo: ["docs/source/quick-start.rst", "apps/templates"])

    try:
        module.ensure_docs_repo_release_ready(docs_repo)
    except SystemExit as exc:
        assert "apps/templates" in str(exc)
    else:
        raise AssertionError("ensure_docs_repo_release_ready() should reject unrelated dirty paths")


def test_git_commit_docs_repository_pushes_only_release_managed_docs_paths(monkeypatch, tmp_path) -> None:
    module = _load_pypi_publish()

    docs_repo = tmp_path / "thales_agilab"
    docs_repo.mkdir()

    calls: list[tuple[list[str], Path]] = []

    monkeypatch.setattr(module, "find_docs_repository", lambda: (docs_repo, "default"))
    monkeypatch.setattr(
        module,
        "ensure_docs_repo_release_ready",
        lambda _repo: ["docs/source/quick-start.rst", "docs/source/demos.rst"],
    )
    monkeypatch.setattr(module, "current_git_branch", lambda repo=module.REPO_ROOT: "main")
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(["git"], 1),
    )
    monkeypatch.setattr(
        module,
        "run",
        lambda cmd, cwd=None, env=None, timeout=None: calls.append((cmd, cwd)),
    )

    module.git_commit_docs_repository("2026.04.21", push=True)

    assert calls == [
        (["git", "add", "-A", "--", "docs/source/demos.rst", "docs/source/quick-start.rst"], docs_repo),
        (["git", "commit", "-m", "docs(release): sync docs for 2026.04.21"], docs_repo),
        (["git", "push", "origin", "main"], docs_repo),
    ]


def test_create_and_push_tag_includes_docs_repo_when_requested(monkeypatch, tmp_path) -> None:
    module = _load_pypi_publish()

    docs_repo = tmp_path / "thales_agilab"
    docs_repo.mkdir()

    calls: list[tuple[Path, str, str, str]] = []

    monkeypatch.setattr(module, "find_apps_repository", lambda: (None, None))
    monkeypatch.setattr(module, "find_docs_repository", lambda: (docs_repo, "default"))
    monkeypatch.setattr(module, "_git_status_paths", lambda _repo: [])
    monkeypatch.setattr(module, "_tag_exists", lambda _tag, repo=None: False)
    monkeypatch.setattr(
        module,
        "_create_tag_in_repo",
        lambda repo_path, tag_ref, release_label, remote: calls.append((repo_path, tag_ref, release_label, remote)),
    )

    module.create_and_push_tag("2026.04.21", include_apps_repo=False, include_docs_repo=True)

    assert calls == [
        (module.REPO_ROOT, "v2026.04.21", "2026.04.21", "origin"),
        (docs_repo, "v2026.04.21", "2026.04.21", "origin"),
    ]


def test_main_resets_release_files_only_when_publish_fails(tmp_path, monkeypatch) -> None:
    module = _load_pypi_publish()

    project_dir = tmp_path / "agi-env"
    project_dir.mkdir()
    pyproject = project_dir / "pyproject.toml"
    pyproject.write_text(
        "[project]\nname = 'agi-env'\nversion = '2026.03.16'\ndependencies = []\n",
        encoding="utf-8",
    )

    cfg = module.Cfg(
        repo="testpypi",
        dist="both",
        skip_existing=True,
        retries=1,
        dry_run=False,
        verbose=False,
        version="2026.03.23",
        purge_before=False,
        purge_after=False,
        cleanup_only=False,
        clean_days=None,
        clean_delete_project=False,
        cleanup_user=None,
        cleanup_pass=None,
        cleanup_timeout=0,
        skip_cleanup=True,
        yank_previous=False,
        git_tag=False,
        git_commit_version=False,
        git_reset_on_failure=True,
        pypirc_check=False,
        packages=["agi-env"],
        gen_docs=False,
    )

    reset_calls: list[str] = []

    monkeypatch.setattr(module, "parse_args", lambda: object())
    monkeypatch.setattr(module, "make_cfg", lambda _args: cfg)
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "CORE", [("agi-env", pyproject, project_dir)])
    monkeypatch.setattr(module, "UMBRELLA", ("agilab", tmp_path / "missing.toml", tmp_path))
    monkeypatch.setattr(module, "pypi_releases", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(module, "remove_symlinks_for_umbrella", lambda: [])
    monkeypatch.setattr(module, "restore_symlinks", lambda _entries: None)
    monkeypatch.setattr(module, "sync_builtin_app_versions", lambda _version: None)
    monkeypatch.setattr(module, "dist_files", lambda _project_dir: [str(project_dir / "dist" / "fake.whl")])
    monkeypatch.setattr(module, "twine_check", lambda _files: None)
    monkeypatch.setattr(
        module,
        "twine_upload",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(subprocess.CalledProcessError(1, ["twine"])),
    )
    monkeypatch.setattr(module, "update_selected_badges", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "uv_build_project", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "git_reset_pyprojects", lambda: reset_calls.append("reset"))

    try:
        module.main()
    except subprocess.CalledProcessError:
        pass
    else:
        raise AssertionError("main() should propagate upload failures")

    assert reset_calls == ["reset"]
