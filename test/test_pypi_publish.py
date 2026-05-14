from __future__ import annotations

import importlib.util
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = REPO_ROOT / "tools"
sys.path.insert(0, str(TOOLS_ROOT))

from package_split_contract import LIBRARY_PACKAGE_CONTRACTS, WHEEL_ONLY_PACKAGE_NAMES


MODULE_PATH = REPO_ROOT / "tools/pypi_publish.py"


def _load_pypi_publish():
    spec = importlib.util.spec_from_file_location("pypi_publish_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _allow_break_glass_pypi_for_release_flow_unit_tests(monkeypatch):
    """Most tests exercise release ordering internals, not the outer OIDC gate."""
    monkeypatch.setenv("AGILAB_ALLOW_LOCAL_PYPI_TWINE", "1")


def _base_cfg(module, **overrides):
    values = {
        "repo": "pypi",
        "dist": "both",
        "skip_existing": True,
        "retries": 1,
        "dry_run": False,
        "verbose": False,
        "version": None,
        "purge_before": False,
        "purge_after": False,
        "cleanup_only": False,
        "clean_days": None,
        "clean_delete_project": False,
        "cleanup_user": None,
        "cleanup_pass": None,
        "cleanup_timeout": 0,
        "skip_cleanup": True,
        "yank_previous": False,
        "git_tag": False,
        "git_commit_version": False,
        "git_reset_on_failure": False,
        "pypirc_check": False,
        "packages": None,
        "gen_docs": False,
    }
    values.update(overrides)
    return module.Cfg(**values)


def _write_wheel_metadata(path: Path, *, requires_dist: list[str]) -> None:
    metadata = "\n".join(
        [
            "Metadata-Version: 2.1",
            "Name: agilab",
            "Version: 2026.5.5",
            *(f"Requires-Dist: {requirement}" for requirement in requires_dist),
            "",
        ]
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("agilab-2026.5.5.dist-info/METADATA", metadata)


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


def test_git_paths_to_commit_includes_release_coverage_badges(tmp_path, monkeypatch) -> None:
    module = _load_pypi_publish()

    coverage_badge = tmp_path / "badges" / "coverage-agilab.svg"
    coverage_badge.parent.mkdir(parents=True)
    coverage_badge.write_text("<svg />\n", encoding="utf-8")

    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "CORE", [])
    monkeypatch.setattr(module, "UMBRELLA", ("agilab", tmp_path / "missing.toml", tmp_path))
    monkeypatch.setattr(module, "builtin_app_pyprojects", lambda: [])
    monkeypatch.setattr(module, "PUBLIC_RELEASE_METADATA_PATHS", [])

    assert "badges/coverage-agilab.svg" in module.git_paths_to_commit()


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


def test_sync_builtin_app_versions_lower_bounds_internal_runtime_deps(tmp_path, monkeypatch) -> None:
    module = _load_pypi_publish()
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    pyproject = tmp_path / "src/agilab/apps/builtin/flight_telemetry_project/pyproject.toml"
    pyproject.parent.mkdir(parents=True)
    pyproject.write_text(
        "\n".join(
            [
                "[project]",
                'name = "flight_telemetry_project"',
                'version = "2026.04.28.post3"',
                'dependencies = ["agi-env", "agi-node>=2026.04.28.post3", "streamlit"]',
                "",
                "[tool.uv.sources]",
                'agi-env = { path = "../../../core/agi-env", editable = true }',
                'agi-node = { path = "../../../core/agi-node", editable = true }',
                "",
            ]
        ),
        encoding="utf-8",
    )

    updated = module.sync_builtin_app_versions(
        "2026.04.28.post4",
        {"agi-env": "2026.04.28.post4", "agi-node": "2026.04.28.post4"},
    )

    text = pyproject.read_text(encoding="utf-8")
    assert updated == [pyproject]
    assert 'version = "2026.04.28.post4"' in text
    assert '"agi-env>=2026.04.28.post4"' in text
    assert '"agi-node>=2026.04.28.post4"' in text
    assert "[tool.uv.sources]" in text


def test_main_does_not_rewrite_builtin_apps_for_umbrella_build(tmp_path, monkeypatch) -> None:
    module = _load_pypi_publish()

    umbrella_pyproject = tmp_path / "pyproject.toml"
    umbrella_pyproject.write_text(
        "[project]\nname = 'agilab'\nversion = '2026.04.28.post3'\ndependencies = []\n",
        encoding="utf-8",
    )
    cfg = module.Cfg(
        repo="testpypi",
        dist="both",
        skip_existing=True,
        retries=1,
        dry_run=False,
        verbose=False,
        version="2026.04.28.post4",
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
        packages=["agilab"],
        gen_docs=False,
    )
    order: list[str] = []

    monkeypatch.setattr(module, "parse_args", lambda: object())
    monkeypatch.setattr(module, "make_cfg", lambda _args: cfg)
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "CORE", [])
    monkeypatch.setattr(module, "UMBRELLA", ("agilab", umbrella_pyproject, tmp_path))
    monkeypatch.setattr(module, "pypi_releases", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(module, "remove_symlinks_for_umbrella", lambda: [])
    monkeypatch.setattr(module, "restore_symlinks", lambda _entries: None)
    monkeypatch.setattr(module, "update_selected_badges", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "sync_builtin_app_versions", lambda *_args, **_kwargs: order.append("sync-builtin"))
    monkeypatch.setattr(module, "uv_build_repo_root", lambda *_args, **_kwargs: order.append("build-root"))
    monkeypatch.setattr(module, "dist_files_root", lambda: [str(tmp_path / "dist" / "agilab.whl")])
    monkeypatch.setattr(module, "twine_check", lambda _files: None)
    monkeypatch.setattr(module, "twine_upload", lambda *_args, **_kwargs: None)

    module.main()

    assert order == ["build-root"]


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


def test_require_safe_pypi_release_rejects_local_twine_without_break_glass(monkeypatch) -> None:
    module = _load_pypi_publish()
    monkeypatch.delenv(module.ALLOW_LOCAL_PYPI_TWINE_ENV, raising=False)

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
    )

    with pytest.raises(SystemExit, match="Trusted Publishing/OIDC"):
        module.require_safe_pypi_release(cfg)


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

    assert profiles == [
        "agi-env",
        "agi-core-combined",
        "agi-gui",
        "docs",
        "installer",
        "shared-core-typing",
        "dependency-policy",
        "release-proof",
    ]


def test_run_release_preflight_cleans_stale_coverage_before_workflow(tmp_path, monkeypatch) -> None:
    module = _load_pypi_publish()
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    stale_paths = [
        tmp_path / ".coverage.agi-gui",
        tmp_path / ".coverage.agi-core-combined",
        tmp_path / "coverage-agi-gui.xml",
    ]
    for path in stale_paths:
        path.write_text("stale", encoding="utf-8")
    calls = []

    def fake_run(cmd, *, cwd=None, **_kwargs):
        calls.append((cmd, cwd, [path.exists() for path in stale_paths]))

    monkeypatch.setattr(module, "run", fake_run)

    module.run_release_preflight(
        _base_cfg(
            module,
            repo="pypi",
            git_tag=True,
            git_commit_version=True,
            git_reset_on_failure=True,
        )
    )

    assert calls
    assert calls[0][1] == tmp_path
    assert calls[0][2] == [False, False, False]
    assert "tools/workflow_parity.py" in calls[0][0]
    assert calls[0][0][-2:] == ["--profile", "release-proof"]


def test_validate_wheel_external_machine_metadata_rejects_unmarked_mlx(tmp_path) -> None:
    module = _load_pypi_publish()
    wheel = tmp_path / "agilab-2026.5.5-py3-none-any.whl"
    _write_wheel_metadata(wheel, requires_dist=["mlx>=0.31.2", "mlx-lm>=0.31.3"])

    with pytest.raises(SystemExit, match="external-machine safe"):
        module.validate_wheel_external_machine_metadata([str(wheel)])


def test_validate_wheel_external_machine_metadata_accepts_apple_silicon_marked_mlx(tmp_path) -> None:
    module = _load_pypi_publish()
    wheel = tmp_path / "agilab-2026.5.5-py3-none-any.whl"
    marker = 'sys_platform == "darwin" and platform_machine == "arm64"'
    _write_wheel_metadata(
        wheel,
        requires_dist=[f"mlx>=0.31.2; {marker}", f"mlx-lm>=0.31.3; {marker}"],
    )

    module.validate_wheel_external_machine_metadata([str(wheel)])


def test_pre_upload_external_install_guard_dry_runs_release_wheel_matrix(tmp_path, monkeypatch) -> None:
    module = _load_pypi_publish()
    wheel = tmp_path / "agilab-2026.5.5-py3-none-any.whl"
    _write_wheel_metadata(wheel, requires_dist=[])
    calls: list[list[str]] = []

    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "EXTERNAL_INSTALL_PLATFORMS", ("x86_64-pc-windows-msvc", "x86_64-unknown-linux-gnu"))
    monkeypatch.setattr(module, "run", lambda cmd, **_kwargs: calls.append(cmd))

    module.run_pre_upload_external_install_guard(
        _base_cfg(module, repo="pypi", git_tag=True, git_commit_version=True, git_reset_on_failure=True),
        [str(wheel), str(tmp_path / "agilab-2026.5.5.tar.gz")],
    )

    assert len(calls) == 2
    assert all("--dry-run" in call for call in calls)
    assert all("--python-version" in call and "3.13" in call for call in calls)
    assert [call[call.index("--python-platform") + 1] for call in calls] == [
        "x86_64-pc-windows-msvc",
        "x86_64-unknown-linux-gnu",
    ]
    assert all(str(wheel) in call for call in calls)


def test_compute_unified_version_rejects_auto_post_when_latest_release_is_newer_on_pypi(monkeypatch) -> None:
    module = _load_pypi_publish()

    class _FixedDatetime:
        @staticmethod
        def now(_tz):
            return datetime(2026, 4, 24, 10, 0, 0, tzinfo=timezone.utc)

    releases = {
        "agi-env": {"2026.4.25"},
        "agi-node": {"2026.4.25"},
        "agilab": {"2026.4.25"},
    }

    monkeypatch.setattr(module, "datetime", _FixedDatetime)
    monkeypatch.setattr(
        module,
        "pypi_releases",
        lambda name, _repo: releases.get(name, set()),
    )

    try:
        module.compute_unified_version(
            ["agi-env", "agi-node", "agilab"],
            "pypi",
            None,
        )
    except SystemExit as exc:
        assert "Automatic .postN PyPI version bumps are disabled" in str(exc)
        assert "agi-env: 2026.4.25" in str(exc)
    else:
        raise AssertionError("compute_unified_version() should not auto-create .postN on real PyPI")


def test_compute_unified_version_uses_today_base_without_post_on_pypi(monkeypatch) -> None:
    module = _load_pypi_publish()

    class _FixedDatetime:
        @staticmethod
        def now(_tz):
            return datetime(2026, 4, 29, 10, 0, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(module, "datetime", _FixedDatetime)
    monkeypatch.setattr(module, "pypi_releases", lambda *_args, **_kwargs: set())

    chosen, collisions = module.compute_unified_version(
        ["agi-env", "agi-node", "agilab"],
        "pypi",
        None,
    )

    assert chosen == "2026.04.29"
    assert collisions == {"agi-env": [], "agi-node": [], "agilab": []}


def test_compute_unified_version_handles_testpypi_canonicalized_date_posts(monkeypatch) -> None:
    module = _load_pypi_publish()

    class _FixedDatetime:
        @staticmethod
        def now(_tz):
            return datetime(2026, 4, 28, 10, 0, 0, tzinfo=timezone.utc)

    releases = {
        "agi-env": {"2026.4.28.post2"},
        "agi-node": {"2026.4.28.post1"},
        "agilab": {"2026.4.28.post2"},
    }

    monkeypatch.setattr(module, "datetime", _FixedDatetime)
    monkeypatch.setattr(
        module,
        "pypi_releases",
        lambda name, _repo: releases.get(name, set()),
    )

    chosen, collisions = module.compute_unified_version(
        ["agi-env", "agi-node", "agilab"],
        "testpypi",
        None,
    )

    assert chosen == "2026.04.28.post3"
    assert collisions == {
        "agi-env": ["2026.4.28.post2"],
        "agi-node": ["2026.4.28.post1"],
        "agilab": ["2026.4.28.post2"],
    }


def test_compute_unified_version_rejects_explicit_canonical_collision_on_pypi(monkeypatch) -> None:
    module = _load_pypi_publish()

    releases = {
        "agi-env": {"2026.4.28.post2"},
        "agilab": {"2026.4.28.post2"},
    }
    monkeypatch.setattr(
        module,
        "pypi_releases",
        lambda name, _repo: releases.get(name, set()),
    )

    try:
        module.compute_unified_version(
            ["agi-env", "agilab"],
            "pypi",
            "2026.04.28.post2",
        )
    except SystemExit as exc:
        assert "Automatic .postN PyPI version bumps are disabled" in str(exc)
        assert "agi-env: 2026.4.28.post2" in str(exc)
    else:
        raise AssertionError("compute_unified_version() should reject explicit collisions on real PyPI")


def test_compute_unified_version_rejects_free_explicit_version_below_latest_release(monkeypatch) -> None:
    module = _load_pypi_publish()

    releases = {
        "agi-env": {"2026.4.25"},
        "agilab": {"2026.4.25"},
    }
    monkeypatch.setattr(
        module,
        "pypi_releases",
        lambda name, _repo: releases.get(name, set()),
    )

    try:
        module.compute_unified_version(["agi-env", "agilab"], "pypi", "2026.4.24.post1")
    except SystemExit as exc:
        assert "Computed version 2026.4.24.post1 is lower than existing release 2026.4.25" in str(exc)
    else:
        raise AssertionError("compute_unified_version() should reject computed lower versions")


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


def test_github_release_notes_lists_published_packages() -> None:
    module = _load_pypi_publish()

    notes = module.github_release_notes("2026.4.27", ["agi-env", "agilab"])

    assert "Published AGILAB 2026.4.27 to PyPI." in notes
    assert "Packages: agi-env, agilab" in notes


def test_create_or_update_github_release_creates_missing_release(monkeypatch, tmp_path) -> None:
    module = _load_pypi_publish()
    calls: list[list[str]] = []

    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/bin/gh" if name == "gh" else None)
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1),
    )
    monkeypatch.setattr(module, "run", lambda cmd, cwd=None, env=None, timeout=None: calls.append(cmd))

    module.create_or_update_github_release("2026.04.24", "2026.4.27", ["agilab"])

    assert calls == [
        [
            "/usr/bin/gh",
            "release",
            "create",
            "v2026.04.24",
            "--title",
            "AGILAB 2026.4.27",
            "--notes",
            "Published AGILAB 2026.4.27 to PyPI.\n\nPackages: agilab\n",
            "--verify-tag",
            "--latest",
        ]
    ]


def test_create_or_update_github_release_updates_existing_release(monkeypatch, tmp_path) -> None:
    module = _load_pypi_publish()
    calls: list[list[str]] = []

    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/bin/gh" if name == "gh" else None)
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0),
    )
    monkeypatch.setattr(module, "run", lambda cmd, cwd=None, env=None, timeout=None: calls.append(cmd))

    module.create_or_update_github_release("v2026.04.24", "2026.4.27", ["agilab"])

    assert calls == [
        [
            "/usr/bin/gh",
            "release",
            "edit",
            "v2026.04.24",
            "--title",
            "AGILAB 2026.4.27",
            "--notes",
            "Published AGILAB 2026.4.27 to PyPI.\n\nPackages: agilab\n",
            "--latest",
        ]
    ]


def test_create_or_update_github_release_requires_gh(monkeypatch) -> None:
    module = _load_pypi_publish()
    monkeypatch.setattr(module.shutil, "which", lambda _name: None)

    try:
        module.create_or_update_github_release("2026.04.24", "2026.4.27", ["agilab"])
    except SystemExit as exc:
        assert "requires the GitHub CLI" in str(exc)
    else:
        raise AssertionError("create_or_update_github_release() should require gh")


def test_delete_former_github_release_deletes_first_non_current_release(monkeypatch, tmp_path) -> None:
    module = _load_pypi_publish()
    calls: list[list[str]] = []

    def fake_subprocess_run(cmd, **_kwargs):
        assert cmd == ["/usr/bin/gh", "release", "list", "--limit", "20", "--json", "tagName"]
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout='[{"tagName": "v2026.04.29"}, {"tagName": "v2026.04.28"}, {"tagName": "v2026.04.27"}]',
            stderr="",
        )

    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/bin/gh" if name == "gh" else None)
    monkeypatch.setattr(module.subprocess, "run", fake_subprocess_run)
    monkeypatch.setattr(module, "run", lambda cmd, cwd=None, env=None, timeout=None: calls.append(cmd))

    deleted = module.delete_former_github_release("2026.04.29")

    assert deleted == "v2026.04.28"
    assert calls == [["/usr/bin/gh", "release", "delete", "v2026.04.28", "--yes"]]


def test_delete_former_github_release_noops_when_only_current_release_exists(monkeypatch, tmp_path) -> None:
    module = _load_pypi_publish()
    calls: list[list[str]] = []

    def fake_subprocess_run(cmd, **_kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout='[{"tagName": "v2026.04.29"}]', stderr="")

    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/bin/gh" if name == "gh" else None)
    monkeypatch.setattr(module.subprocess, "run", fake_subprocess_run)
    monkeypatch.setattr(module, "run", lambda cmd, cwd=None, env=None, timeout=None: calls.append(cmd))

    assert module.delete_former_github_release("v2026.04.29") is None
    assert calls == []


def test_require_safe_pypi_release_rejects_former_release_delete_without_github_release() -> None:
    module = _load_pypi_publish()

    cfg = module.Cfg(
        repo="testpypi",
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
        delete_former_github_release=True,
    )

    try:
        module.require_safe_pypi_release(cfg)
    except SystemExit as exc:
        assert "--delete-former-github-release requires --repo pypi --git-tag" in str(exc)
    else:
        raise AssertionError("require_safe_pypi_release() should reject impossible GitHub release cleanup")


def test_exact_release_regex_normalizes_zero_padded_versions() -> None:
    module = _load_pypi_publish()

    assert module.exact_release_regex("2026.04.29.post1") == r"^2026\.4\.29\.post1$"


def test_delete_exact_pypi_releases_uses_precise_cleanup_pattern(monkeypatch) -> None:
    module = _load_pypi_publish()
    cfg = _base_cfg(
        module,
        cleanup_user="maintainer",
        cleanup_pass="secret",
        cleanup_timeout=12,
        skip_cleanup=False,
        delete_pypi_releases=["2026.04.29.post1"],
    )
    calls = []

    monkeypatch.setattr(module, "run", lambda cmd, cwd=None, env=None, timeout=None: calls.append((cmd, env, timeout)))

    module.delete_exact_pypi_releases(cfg, ["agilab", "agi-core"])

    assert len(calls) == 2
    first_cmd, first_env, first_timeout = calls[0]
    assert first_cmd == [
        "pypi-cleanup",
        "--version-regex",
        r"^2026\.4\.29\.post1$",
        "--do-it",
        "-y",
        "--host",
        "https://pypi.org/",
        "--package",
        "agilab",
        "--username",
        "maintainer",
    ]
    assert first_env["PYPI_PASSWORD"] == "secret"
    assert first_timeout == 12
    assert calls[1][0][7:9] == ["--package", "agi-core"]


def test_delete_exact_pypi_releases_requires_web_credentials(monkeypatch) -> None:
    module = _load_pypi_publish()
    cfg = _base_cfg(
        module,
        skip_cleanup=False,
        delete_pypi_releases=["2026.4.29.post1"],
    )

    monkeypatch.delenv("PYPI_USERNAME", raising=False)
    monkeypatch.delenv("PYPI_PASSWORD", raising=False)
    monkeypatch.delenv("PYPI_CLEANUP_PASSWORD", raising=False)
    monkeypatch.setattr(module, "read_cleanup_creds_from_pypirc", lambda _repo: (None, None))

    try:
        module.delete_exact_pypi_releases(cfg, ["agilab"])
    except SystemExit as exc:
        assert "cleanup web-login credentials" in str(exc)
    else:
        raise AssertionError("delete_exact_pypi_releases() should reject missing cleanup credentials")


def test_main_cleanup_only_exact_delete_skips_publish_version_computation(monkeypatch) -> None:
    module = _load_pypi_publish()
    cfg = _base_cfg(
        module,
        cleanup_only=True,
        skip_cleanup=False,
        packages=["agilab"],
        delete_pypi_releases=["2026.04.29.post1"],
    )
    deleted = []

    monkeypatch.setattr(module, "parse_args", lambda: object())
    monkeypatch.setattr(module, "make_cfg", lambda _args: cfg)
    monkeypatch.setattr(module, "assert_pypirc_has", lambda _repo: None)
    monkeypatch.setattr(module, "delete_exact_pypi_releases", lambda _cfg, packages: deleted.append(packages))
    monkeypatch.setattr(
        module,
        "compute_unified_version",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not compute publish version")),
    )

    module.main()

    assert deleted == [["agilab"]]


def test_find_docs_repository_uses_docs_repository_env_name(tmp_path, monkeypatch) -> None:
    module = _load_pypi_publish()

    generic_docs_repo = tmp_path / "docs_repo"
    generic_docs_repo.mkdir()

    monkeypatch.setenv("DOCS_REPOSITORY", str(generic_docs_repo))
    monkeypatch.setattr(module, "_is_git_repo", lambda _path: True)

    repo, source = module.find_docs_repository()

    assert repo == generic_docs_repo.resolve()
    assert source == "env:DOCS_REPOSITORY"


def test_builtin_app_pyprojects_includes_worker_manifests(tmp_path, monkeypatch) -> None:
    module = _load_pypi_publish()
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)

    app_pyproject = tmp_path / "src/agilab/apps/builtin/demo_project/pyproject.toml"
    worker_pyproject = tmp_path / "src/agilab/apps/builtin/demo_project/src/demo_worker/pyproject.toml"
    app_pyproject.parent.mkdir(parents=True)
    worker_pyproject.parent.mkdir(parents=True)
    app_pyproject.write_text("[project]\nname='demo_project'\nversion='1.0.0'\n", encoding="utf-8")
    worker_pyproject.write_text("[project]\nname='demo_worker'\nversion='1.0.0'\n", encoding="utf-8")

    assert module.builtin_app_pyprojects() == [app_pyproject, worker_pyproject]


def test_publishable_libs_include_asset_packages_in_release_order() -> None:
    module = _load_pypi_publish()

    package_names = [name for name, *_ in module.publishable_libs()]

    assert package_names == [package.name for package in LIBRARY_PACKAGE_CONTRACTS]
    assert "agi-pages" in package_names
    assert "agi-apps" in package_names
    assert package_names.index("agi-gui") < package_names.index("agi-pages")
    assert package_names.index("agi-core") < package_names.index("agi-apps")


def test_asset_packages_are_wheel_only_for_release_tooling() -> None:
    module = _load_pypi_publish()

    for package in WHEEL_ONLY_PACKAGE_NAMES:
        assert module.effective_dist_kind(package, "wheel") == "wheel"
        assert module.effective_dist_kind(package, "both") == "wheel"
        with pytest.raises(SystemExit, match=f"{package} is wheel-only"):
            module.effective_dist_kind(package, "sdist")
    assert module.effective_dist_kind("agilab", "both") == "both"


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
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("# Changelog\n", encoding="utf-8")
    docs_index = tmp_path / "docs" / "source" / "index.rst"
    docs_index.parent.mkdir(parents=True)
    docs_index.write_text("docs\n", encoding="utf-8")
    docs_stamp = tmp_path / "docs" / ".docs_source_mirror_stamp.json"
    docs_stamp.write_text("{}\n", encoding="utf-8")
    release_proof_data = tmp_path / "docs" / "source" / "data" / "release_proof.toml"
    release_proof_data.parent.mkdir(parents=True, exist_ok=True)
    release_proof_data.write_text("[release]\n", encoding="utf-8")
    release_proof_page = tmp_path / "docs" / "source" / "release-proof.rst"
    release_proof_page.write_text("Release proof\n", encoding="utf-8")
    public_demo_test = tmp_path / "test" / "test_public_demo_links.py"
    public_demo_test.parent.mkdir(parents=True)
    public_demo_test.write_text("tests\n", encoding="utf-8")

    builtin_dir = tmp_path / "src" / "agilab" / "apps" / "builtin" / "flight_telemetry_project"
    builtin_dir.mkdir(parents=True)
    builtin_toml = builtin_dir / "pyproject.toml"
    builtin_toml.write_text("[project]\nname='flight_telemetry_project'\nversion='1.0.0'\n", encoding="utf-8")

    monkeypatch.setattr(module, "CORE", [("agi-env", core_toml, core_dir)])
    monkeypatch.setattr(module, "UMBRELLA", ("agilab", umbrella_toml, umbrella_dir))
    monkeypatch.setattr(module, "builtin_app_pyprojects", lambda: [builtin_toml, builtin_toml])

    paths = module.git_paths_to_commit(include_docs=True)

    assert paths == [
        "core/agi-env/pyproject.toml",
        "core/agi-env/README.md",
        "pyproject.toml",
        "src/agilab/apps/builtin/flight_telemetry_project/pyproject.toml",
        "README.md",
        "badges/pypi-version-agilab.svg",
        "CHANGELOG.md",
        "docs/.docs_source_mirror_stamp.json",
        "docs/source/index.rst",
        "docs/source/data/release_proof.toml",
        "docs/source/release-proof.rst",
        "test/test_public_demo_links.py",
    ]


def test_update_public_release_references_updates_docs_changelog_and_test(tmp_path, monkeypatch) -> None:
    module = _load_pypi_publish()
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)

    docs_repo = tmp_path / "thales_agilab"
    canonical_index = docs_repo / "docs" / "source" / "index.rst"
    canonical_index.parent.mkdir(parents=True)
    canonical_index.write_text(
        "For release-level evidence, inspect the `latest public GitHub release\n"
        "<https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.01>`__.\n",
        encoding="utf-8",
    )
    public_index = tmp_path / "docs" / "source" / "index.rst"
    public_index.parent.mkdir(parents=True)
    public_index.write_text(canonical_index.read_text(encoding="utf-8"), encoding="utf-8")
    stamp = tmp_path / "docs" / ".docs_source_mirror_stamp.json"
    stamp.write_text("{}\n", encoding="utf-8")
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("# Changelog\n\n## [2026.04.01] - 2026-04-01\n\nOld.\n", encoding="utf-8")
    public_test = tmp_path / "test" / "test_public_demo_links.py"
    public_test.parent.mkdir(parents=True)
    public_test.write_text(
        'RELEASES_URL = "https://github.com/ThalesGroup/agilab/releases"\n'
        'LATEST_RELEASE_URL = f"{RELEASES_URL}/tag/v2026.04.01"\n',
        encoding="utf-8",
    )

    def _fake_sync(source: Path) -> None:
        public_index.write_text((source / "index.rst").read_text(encoding="utf-8"), encoding="utf-8")
        stamp.write_text('{"target_digest_sha256": "updated"}\n', encoding="utf-8")

    monkeypatch.setattr(module, "find_docs_repository", lambda: (docs_repo, "default"))
    monkeypatch.setattr(module, "sync_docs_source_mirror", _fake_sync)
    refreshed_release_proofs: list[str] = []
    monkeypatch.setattr(module, "update_release_proof_references", refreshed_release_proofs.append)

    module.update_public_release_references(
        "2026.04.24",
        "2026.4.27",
        ["agilab", "agi-core", "agi-env"],
    )

    release_url = "https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.24"
    assert release_url in canonical_index.read_text(encoding="utf-8")
    assert release_url in public_index.read_text(encoding="utf-8")
    changelog_text = changelog.read_text(encoding="utf-8")
    assert "## [2026.4.27] - 2026-04-24" in changelog_text
    assert "Published AGILAB `2026.4.27` to PyPI for `agilab`, `agi-core`, and `agi-env`." in changelog_text
    assert f"[2026.4.27]: {release_url}" in changelog_text
    assert 'LATEST_RELEASE_URL = f"{RELEASES_URL}/tag/v2026.04.24"' in public_test.read_text(encoding="utf-8")
    assert refreshed_release_proofs == ["2026.04.24"]


def test_update_public_demo_release_test_skips_manifest_backed_constant(tmp_path, monkeypatch) -> None:
    module = _load_pypi_publish()
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    public_test = tmp_path / "test" / "test_public_demo_links.py"
    public_test.parent.mkdir(parents=True)
    text = (
        'RELEASES_URL = "https://github.com/ThalesGroup/agilab/releases"\n'
        'LATEST_RELEASE_URL = _release_proof_manifest()["release"]["github_release_url"]\n'
    )
    public_test.write_text(text, encoding="utf-8")

    module.update_public_demo_release_test("2026.04.24")

    assert public_test.read_text(encoding="utf-8") == text


def test_update_release_proof_references_refreshes_canonical_docs_and_syncs(tmp_path, monkeypatch) -> None:
    module = _load_pypi_publish()
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    script = tmp_path / "tools" / "release_proof_report.py"
    script.parent.mkdir(parents=True)
    script.write_text("print('ok')\n", encoding="utf-8")
    docs_repo = tmp_path / "thales_agilab"
    canonical_source = docs_repo / "docs" / "source"
    manifest = canonical_source / "data" / "release_proof.toml"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("[release]\n", encoding="utf-8")
    commands: list[list[str]] = []
    synced: list[Path] = []
    monkeypatch.setattr(module, "find_docs_repository", lambda: (docs_repo, "default"))
    monkeypatch.setattr(module, "run", lambda cmd, cwd=None, **_kwargs: commands.append([str(part) for part in cmd]))
    monkeypatch.setattr(module, "sync_docs_source_mirror", synced.append)

    module.update_release_proof_references("2026.04.24")

    assert synced == [canonical_source]
    command = commands[0]
    assert "--docs-source" in command
    assert str(canonical_source) in command
    assert "--github-release-tag" in command
    assert "v2026.04.24" in command
    assert "--github-release-url" in command
    assert "https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.24" in command


def test_update_docs_index_release_link_requires_canonical_docs_repo(tmp_path, monkeypatch) -> None:
    module = _load_pypi_publish()
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)

    public_index = tmp_path / "docs" / "source" / "index.rst"
    public_index.parent.mkdir(parents=True)
    public_index.write_text("latest public GitHub release\n", encoding="utf-8")
    monkeypatch.setattr(module, "find_docs_repository", lambda: (None, None))

    try:
        module.update_docs_index_release_link("2026.04.24")
    except SystemExit as exc:
        assert "canonical docs repository was not found" in str(exc)
    else:
        raise AssertionError("update_docs_index_release_link() should require canonical docs source")


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
    monkeypatch.setattr(module, "sync_builtin_app_versions", lambda *_args, **_kwargs: None)
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
    monkeypatch.setattr(module, "sync_builtin_app_versions", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "dist_files", lambda _project_dir: [str(project_dir / "dist" / "fake.whl")])
    monkeypatch.setattr(module, "twine_check", lambda _files: None)
    monkeypatch.setattr(module, "twine_upload", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "update_selected_badges", lambda *_args, **_kwargs: order.append("badge"))
    monkeypatch.setattr(module, "uv_build_project", lambda *_args, **_kwargs: order.append("build"))
    monkeypatch.setattr(module, "run_release_preflight", lambda _cfg: order.append("preflight"))
    monkeypatch.setattr(
        module,
        "run_pre_upload_external_install_guard",
        lambda *_args, **_kwargs: order.append("external-install-guard"),
    )
    monkeypatch.setattr(
        module,
        "run_pre_upload_release_guard",
        lambda *_args, **_kwargs: order.append("pre-upload-guard"),
    )
    monkeypatch.setattr(
        module,
        "run_release_coverage_workflow_prerequisite",
        lambda *_args, **_kwargs: order.append("coverage-workflow"),
    )
    monkeypatch.setattr(module, "git_commit_version", lambda *_args, **_kwargs: order.append("commit"))
    monkeypatch.setattr(module, "compute_date_tag", lambda: "2026.03.23")
    monkeypatch.setattr(module, "update_public_release_references", lambda *_args, **_kwargs: order.append("release-refs"))
    monkeypatch.setattr(module, "create_and_push_tag", lambda *_args, **_kwargs: order.append("tag"))
    monkeypatch.setattr(module, "create_or_update_github_release", lambda *_args, **_kwargs: order.append("github-release"))

    module.main()

    assert order[:5] == ["preflight", "badge", "build", "external-install-guard", "pre-upload-guard"]


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
    monkeypatch.setattr(module, "sync_builtin_app_versions", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "dist_files", lambda _project_dir: [])
    monkeypatch.setattr(module, "update_selected_badges", lambda *_args, **_kwargs: None)

    module.main()

    assert pyproject.read_text(encoding="utf-8") == original_text


def test_main_dry_run_does_not_report_stale_dist_artifacts(tmp_path, monkeypatch, capsys) -> None:
    module = _load_pypi_publish()

    project_dir = tmp_path / "agi-env"
    project_dir.mkdir(parents=True)
    pyproject = project_dir / "pyproject.toml"
    pyproject.write_text(
        "[project]\nname = 'agi-env'\nversion = '2026.03.16'\ndependencies = []\n",
        encoding="utf-8",
    )
    stale_dist = project_dir / "dist" / "agi_env-2026.03.16-py3-none-any.whl"
    stale_dist.parent.mkdir()
    stale_dist.write_text("stale", encoding="utf-8")

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
    monkeypatch.setattr(module, "sync_builtin_app_versions", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        module,
        "dist_files",
        lambda _project_dir: (_ for _ in ()).throw(AssertionError("dry-run must not read dist")),
    )
    monkeypatch.setattr(module, "update_selected_badges", lambda *_args, **_kwargs: None)

    module.main()

    output = capsys.readouterr().out
    assert str(stale_dist) not in output
    assert "[build] agi-env: (dry-run would build both artifacts for 2026.03.23)" in output


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
    monkeypatch.setattr(module, "sync_builtin_app_versions", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "dist_files", lambda _project_dir: [str(project_dir / "dist" / "fake.whl")])
    monkeypatch.setattr(module, "twine_check", lambda _files: None)
    monkeypatch.setattr(module, "twine_upload", _twine_upload)
    monkeypatch.setattr(module, "update_selected_badges", lambda *_args, **_kwargs: order.append("badge"))
    monkeypatch.setattr(module, "uv_build_project", lambda *_args, **_kwargs: order.append("build"))
    monkeypatch.setattr(module, "next_free_post_for_all", lambda *_args, **_kwargs: "2026.03.23.post2")

    module.main()

    assert order[:4] == ["badge", "build", "badge", "build"]


@pytest.mark.parametrize("upload_success_count", [0, 1])
def test_main_rejects_real_pypi_collision_instead_of_post_rebuild(
    tmp_path, monkeypatch, upload_success_count
) -> None:
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

    def _twine_upload(*_args, **_kwargs):
        module.UPLOAD_COLLISION_DETECTED = True
        module.UPLOAD_SUCCESS_COUNT = upload_success_count

    monkeypatch.setattr(module, "parse_args", lambda: object())
    monkeypatch.setattr(module, "make_cfg", lambda _args: cfg)
    monkeypatch.setattr(module, "run_release_preflight", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "CORE", [("agi-env", pyproject, project_dir)])
    monkeypatch.setattr(module, "UMBRELLA", ("agilab", tmp_path / "missing.toml", tmp_path))
    monkeypatch.setattr(module, "pypi_releases", lambda *_args, **_kwargs: set())
    monkeypatch.setattr(module, "remove_symlinks_for_umbrella", lambda: [])
    monkeypatch.setattr(module, "restore_symlinks", lambda _entries: None)
    monkeypatch.setattr(module, "sync_builtin_app_versions", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "dist_files", lambda _project_dir: [str(project_dir / "dist" / "fake.whl")])
    monkeypatch.setattr(module, "twine_check", lambda _files: None)
    monkeypatch.setattr(module, "twine_upload", _twine_upload)
    monkeypatch.setattr(module, "update_selected_badges", lambda *_args, **_kwargs: order.append("badge"))
    monkeypatch.setattr(module, "uv_build_project", lambda *_args, **_kwargs: order.append("build"))
    monkeypatch.setattr(module, "compute_date_tag", lambda: "2026.03.23")
    monkeypatch.setattr(module, "run_pre_upload_external_install_guard", lambda *_args, **_kwargs: order.append("external-install-guard"))
    monkeypatch.setattr(module, "run_pre_upload_release_guard", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        module,
        "run_release_coverage_workflow_prerequisite",
        lambda *_args, **_kwargs: order.append("coverage-workflow"),
    )
    monkeypatch.setattr(module, "next_free_post_for_all", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not auto-post for pypi")))
    monkeypatch.setattr(module, "update_release_proof_references", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "git_commit_version", lambda *_args, **_kwargs: order.append("commit"))
    monkeypatch.setattr(module, "git_reset_pyprojects", lambda: order.append("reset"))

    try:
        module.main()
    except SystemExit as exc:
        assert "Automatic .postN PyPI version bumps are disabled" in str(exc)
    else:
        raise AssertionError("main() should reject real PyPI upload collisions")

    assert order == ["badge", "build", "external-install-guard", "coverage-workflow", "reset"]


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
    monkeypatch.setattr(module, "sync_builtin_app_versions", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "dist_files", lambda _project_dir: [str(project_dir / "dist" / "fake.whl")])
    monkeypatch.setattr(module, "twine_check", lambda _files: None)
    monkeypatch.setattr(module, "twine_upload", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "update_selected_badges", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "uv_build_project", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "git_reset_pyprojects", lambda: reset_calls.append("reset"))

    module.main()

    assert reset_calls == []


def test_main_commits_after_successful_upload_before_tagging(tmp_path, monkeypatch) -> None:
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
    monkeypatch.setattr(module, "sync_builtin_app_versions", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "dist_files", lambda _project_dir: [str(project_dir / "dist" / "fake.whl")])
    monkeypatch.setattr(module, "twine_check", lambda _files: None)
    monkeypatch.setattr(module, "twine_upload", lambda *_args, **_kwargs: order.append("upload"))
    monkeypatch.setattr(module, "update_selected_badges", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "uv_build_project", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "run_release_preflight", lambda _cfg: order.append("preflight"))
    monkeypatch.setattr(
        module,
        "run_pre_upload_external_install_guard",
        lambda *_args, **_kwargs: order.append("external-install-guard"),
    )
    monkeypatch.setattr(
        module,
        "run_pre_upload_release_guard",
        lambda *_args, **_kwargs: order.append("pre-upload-guard"),
    )
    monkeypatch.setattr(
        module,
        "run_release_coverage_workflow_prerequisite",
        lambda *_args, **_kwargs: order.append("coverage-workflow"),
    )
    monkeypatch.setattr(module, "git_commit_version", lambda *_args, **_kwargs: order.append("commit"))
    monkeypatch.setattr(module, "compute_date_tag", lambda: "2026.03.23")
    monkeypatch.setattr(module, "update_public_release_references", lambda *_args, **_kwargs: order.append("release-refs"))
    monkeypatch.setattr(module, "create_and_push_tag", lambda *_args, **_kwargs: order.append("tag"))
    monkeypatch.setattr(module, "create_or_update_github_release", lambda *_args, **_kwargs: order.append("github-release"))

    module.main()

    assert order == [
        "preflight",
        "external-install-guard",
        "pre-upload-guard",
        "coverage-workflow",
        "upload",
        "release-refs",
        "commit",
        "tag",
        "github-release",
    ]


def test_main_does_not_publish_release_metadata_when_upload_fails(tmp_path, monkeypatch) -> None:
    module = _load_pypi_publish()

    project_dir = tmp_path / "agi-env"
    project_dir.mkdir()
    pyproject = project_dir / "pyproject.toml"
    pyproject.write_text(
        "[project]\nname = 'agi-env'\nversion = '2026.03.16'\ndependencies = []\n",
        encoding="utf-8",
    )

    cfg = _base_cfg(
        module,
        repo="pypi",
        version="2026.03.23",
        git_tag=True,
        git_commit_version=True,
        git_reset_on_failure=True,
        packages=["agi-env"],
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
    monkeypatch.setattr(module, "sync_builtin_app_versions", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "dist_files", lambda _project_dir: [str(project_dir / "dist" / "fake.whl")])
    monkeypatch.setattr(module, "twine_check", lambda _files: None)
    monkeypatch.setattr(
        module,
        "twine_upload",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("upload failed")),
    )
    monkeypatch.setattr(module, "update_selected_badges", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "uv_build_project", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "run_release_preflight", lambda _cfg: order.append("preflight"))
    monkeypatch.setattr(module, "run_pre_upload_external_install_guard", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "run_pre_upload_release_guard", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "run_release_coverage_workflow_prerequisite", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "compute_date_tag", lambda: "2026.03.23")
    monkeypatch.setattr(module, "update_public_release_references", lambda *_args, **_kwargs: order.append("release-refs"))
    monkeypatch.setattr(module, "git_commit_version", lambda *_args, **_kwargs: order.append("commit"))
    monkeypatch.setattr(module, "create_and_push_tag", lambda *_args, **_kwargs: order.append("tag"))
    monkeypatch.setattr(module, "create_or_update_github_release", lambda *_args, **_kwargs: order.append("github-release"))
    monkeypatch.setattr(module, "git_reset_pyprojects", lambda: order.append("reset"))

    with pytest.raises(RuntimeError, match="upload failed"):
        module.main()

    assert order == ["preflight", "reset"]


def test_main_deletes_former_github_release_after_current_release(tmp_path, monkeypatch) -> None:
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
        delete_former_github_release=True,
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
    monkeypatch.setattr(module, "sync_builtin_app_versions", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "dist_files", lambda _project_dir: [str(project_dir / "dist" / "fake.whl")])
    monkeypatch.setattr(module, "twine_check", lambda _files: None)
    monkeypatch.setattr(module, "twine_upload", lambda *_args, **_kwargs: order.append("upload"))
    monkeypatch.setattr(module, "update_selected_badges", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "uv_build_project", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "run_release_preflight", lambda _cfg: order.append("preflight"))
    monkeypatch.setattr(
        module,
        "run_pre_upload_external_install_guard",
        lambda *_args, **_kwargs: order.append("external-install-guard"),
    )
    monkeypatch.setattr(
        module,
        "run_pre_upload_release_guard",
        lambda *_args, **_kwargs: order.append("pre-upload-guard"),
    )
    monkeypatch.setattr(
        module,
        "run_release_coverage_workflow_prerequisite",
        lambda *_args, **_kwargs: order.append("coverage-workflow"),
    )
    monkeypatch.setattr(module, "git_commit_version", lambda *_args, **_kwargs: order.append("commit"))
    monkeypatch.setattr(module, "compute_date_tag", lambda: "2026.03.23")
    monkeypatch.setattr(module, "update_public_release_references", lambda *_args, **_kwargs: order.append("release-refs"))
    monkeypatch.setattr(module, "create_and_push_tag", lambda *_args, **_kwargs: order.append("tag"))
    monkeypatch.setattr(module, "create_or_update_github_release", lambda *_args, **_kwargs: order.append("github-release"))
    monkeypatch.setattr(module, "delete_former_github_release", lambda *_args, **_kwargs: order.append("delete-former"))

    module.main()

    assert order == [
        "preflight",
        "external-install-guard",
        "pre-upload-guard",
        "coverage-workflow",
        "upload",
        "release-refs",
        "commit",
        "tag",
        "github-release",
        "delete-former",
    ]


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


def test_git_commit_version_blocks_dirty_release_metadata_after_commit(monkeypatch) -> None:
    module = _load_pypi_publish()

    calls: list[list[str]] = []

    monkeypatch.setattr(module, "git_paths_to_commit", lambda include_docs=False: ["pyproject.toml"])
    monkeypatch.setattr(module, "current_git_branch", lambda repo=module.REPO_ROOT: "main")

    def fake_subprocess_run(cmd, *_args, **_kwargs):
        if cmd[:3] == ["git", "diff", "--cached"]:
            return subprocess.CompletedProcess(cmd, 1)
        if cmd[:3] == ["git", "status", "--porcelain"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=" M pyproject.toml\n")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(module.subprocess, "run", fake_subprocess_run)
    monkeypatch.setattr(module, "run", lambda cmd, cwd=None, env=None, timeout=None: calls.append(cmd))

    try:
        module.git_commit_version("2026.03.23", push=True)
    except SystemExit as exc:
        assert "release metadata paths are still dirty after the release commit" in str(exc)
        assert "pyproject.toml" in str(exc)
    else:
        raise AssertionError("git_commit_version() should reject dirty release metadata after commit")

    assert calls == [
        ["git", "add", "pyproject.toml"],
        ["git", "commit", "-m", "chore(release): bump version to 2026.03.23"],
    ]


def test_ensure_docs_repo_release_ready_ignores_unrelated_dirty_paths(tmp_path, monkeypatch, capsys) -> None:
    module = _load_pypi_publish()

    docs_repo = tmp_path / "thales_agilab"
    docs_repo.mkdir()

    monkeypatch.setattr(module, "_git_status_paths", lambda _repo: ["docs/source/quick-start.rst", "apps/templates"])

    assert module.ensure_docs_repo_release_ready(docs_repo) == ["docs/source/quick-start.rst"]
    assert "ignoring them for docs release: apps/templates" in capsys.readouterr().out


def test_generate_docs_in_docs_repository_runs_in_docs_repo(monkeypatch, tmp_path) -> None:
    module = _load_pypi_publish()

    docs_repo = tmp_path / "thales_agilab"
    docs_repo.mkdir()

    calls: list[tuple[list[str], Path | None]] = []

    monkeypatch.setattr(module, "find_docs_repository", lambda: (docs_repo, "env:DOCS_REPOSITORY"))
    monkeypatch.setattr(
        module,
        "run",
        lambda cmd, cwd=None, env=None, timeout=None: calls.append((cmd, cwd)),
    )

    module.generate_docs_in_docs_repository()

    assert calls == [
        (["uv", "sync", "--dev", "--group", "sphinx"], docs_repo),
        (
            ["uv", "run", "python", "docs/gen-docs.py", "--agilab-repository", str(module.REPO_ROOT)],
            docs_repo,
        ),
    ]


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
    monkeypatch.setattr(module, "ensure_docs_repo_push_ready", lambda _repo: None)
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


def test_docs_repository_commit_required_for_release_link_updates() -> None:
    module = _load_pypi_publish()

    assert module.should_commit_docs_repository_after_release(
        docs_repo_ready=True,
        gen_docs=False,
        release_tag="2026.04.29-4",
    )
    assert module.should_commit_docs_repository_after_release(
        docs_repo_ready=True,
        gen_docs=True,
        release_tag=None,
    )
    assert not module.should_commit_docs_repository_after_release(
        docs_repo_ready=False,
        gen_docs=True,
        release_tag="2026.04.29-4",
    )
    assert not module.should_commit_docs_repository_after_release(
        docs_repo_ready=True,
        gen_docs=False,
        release_tag=None,
    )


def test_ensure_docs_repo_push_ready_allows_up_to_date_or_release_only_commits(monkeypatch, tmp_path) -> None:
    module = _load_pypi_publish()
    docs_repo = tmp_path / "thales_agilab"
    docs_repo.mkdir()

    monkeypatch.setattr(module, "_git_upstream", lambda _repo: "origin/main")
    monkeypatch.setattr(module, "_git_ahead_behind", lambda _repo, _upstream: (1, 0))
    monkeypatch.setattr(module, "_unpublished_non_release_commits", lambda _repo, _upstream: [])

    module.ensure_docs_repo_push_ready(docs_repo)


def test_ensure_docs_repo_push_ready_blocks_unpublished_non_release_commits(monkeypatch, tmp_path) -> None:
    module = _load_pypi_publish()
    docs_repo = tmp_path / "thales_agilab"
    docs_repo.mkdir()

    monkeypatch.setattr(module, "_git_upstream", lambda _repo: "origin/main")
    monkeypatch.setattr(module, "_git_ahead_behind", lambda _repo, _upstream: (2, 0))
    monkeypatch.setattr(
        module,
        "_unpublished_non_release_commits",
        lambda _repo, _upstream: ["abc1234 app change"],
    )

    try:
        module.ensure_docs_repo_push_ready(docs_repo)
    except SystemExit as exc:
        assert "unpublished non-docs commits" in str(exc)
        assert "abc1234 app change" in str(exc)
    else:
        raise AssertionError("ensure_docs_repo_push_ready() should reject non-docs commits")


def test_ensure_docs_repo_push_ready_blocks_behind_upstream(monkeypatch, tmp_path) -> None:
    module = _load_pypi_publish()
    docs_repo = tmp_path / "thales_agilab"
    docs_repo.mkdir()

    monkeypatch.setattr(module, "_git_upstream", lambda _repo: "origin/main")
    monkeypatch.setattr(module, "_git_ahead_behind", lambda _repo, _upstream: (0, 3))

    try:
        module.ensure_docs_repo_push_ready(docs_repo)
    except SystemExit as exc:
        assert "is behind origin/main by 3 commit(s)" in str(exc)
    else:
        raise AssertionError("ensure_docs_repo_push_ready() should reject behind branches")


def test_create_and_push_tag_includes_docs_repo_when_requested(monkeypatch, tmp_path) -> None:
    module = _load_pypi_publish()

    docs_repo = tmp_path / "thales_agilab"
    docs_repo.mkdir()

    calls: list[tuple[Path, str, str, str]] = []

    monkeypatch.setattr(module, "find_apps_repository", lambda: (None, None))
    monkeypatch.setattr(module, "find_docs_repository", lambda: (docs_repo, "default"))
    monkeypatch.setattr(module, "_git_status_paths", lambda _repo: ["apps/templates"])
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


def test_create_and_push_tag_blocks_uncommitted_docs_release_paths(monkeypatch, tmp_path) -> None:
    module = _load_pypi_publish()

    docs_repo = tmp_path / "thales_agilab"
    docs_repo.mkdir()

    monkeypatch.setattr(module, "find_apps_repository", lambda: (None, None))
    monkeypatch.setattr(module, "find_docs_repository", lambda: (docs_repo, "default"))
    monkeypatch.setattr(module, "_git_status_paths", lambda _repo: ["docs/source/quick-start.rst", "apps/templates"])
    monkeypatch.setattr(module, "_create_tag_in_repo", lambda *_args, **_kwargs: None)

    try:
        module.create_and_push_tag("2026.04.21", include_apps_repo=False, include_docs_repo=True)
    except SystemExit as exc:
        assert "docs/source/quick-start.rst" in str(exc)
        assert "apps/templates" not in str(exc)
    else:
        raise AssertionError("create_and_push_tag() should reject uncommitted docs release paths")


def test_main_generates_docs_before_docs_commit_and_tag(tmp_path, monkeypatch) -> None:
    module = _load_pypi_publish()

    project_dir = tmp_path / "agi-env"
    project_dir.mkdir()
    pyproject = project_dir / "pyproject.toml"
    pyproject.write_text(
        "[project]\nname = 'agi-env'\nversion = '2026.03.16'\ndependencies = []\n",
        encoding="utf-8",
    )

    docs_repo = tmp_path / "thales_agilab"
    docs_repo.mkdir()

    cfg = module.Cfg(
        repo="pypi",
        dist="both",
        skip_existing=True,
        retries=1,
        dry_run=False,
        verbose=False,
        version="2026.04.23",
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
        gen_docs=True,
    )

    order: list[str] = []

    monkeypatch.setattr(module, "parse_args", lambda: object())
    monkeypatch.setattr(module, "make_cfg", lambda _args: cfg)
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "CORE", [("agi-env", pyproject, project_dir)])
    monkeypatch.setattr(module, "UMBRELLA", ("agilab", tmp_path / "missing.toml", tmp_path))
    monkeypatch.setattr(module, "find_docs_repository", lambda: (docs_repo, "env:DOCS_REPOSITORY"))
    monkeypatch.setattr(module, "ensure_docs_repo_release_ready", lambda _repo: [])
    monkeypatch.setattr(module, "pypi_releases", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(module, "remove_symlinks_for_umbrella", lambda: [])
    monkeypatch.setattr(module, "restore_symlinks", lambda _entries: None)
    monkeypatch.setattr(module, "sync_builtin_app_versions", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "dist_files", lambda _project_dir: [str(project_dir / "dist" / "fake.whl")])
    monkeypatch.setattr(module, "twine_check", lambda _files: None)
    monkeypatch.setattr(module, "twine_upload", lambda *_args, **_kwargs: order.append("upload"))
    monkeypatch.setattr(module, "update_selected_badges", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "uv_build_project", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "run_release_preflight", lambda _cfg: order.append("preflight"))
    monkeypatch.setattr(
        module,
        "run_pre_upload_external_install_guard",
        lambda *_args, **_kwargs: order.append("external-install-guard"),
    )
    monkeypatch.setattr(
        module,
        "run_pre_upload_release_guard",
        lambda *_args, **_kwargs: order.append("pre-upload-guard"),
    )
    monkeypatch.setattr(
        module,
        "run_release_coverage_workflow_prerequisite",
        lambda *_args, **_kwargs: order.append("coverage-workflow"),
    )
    monkeypatch.setattr(module, "generate_docs_in_docs_repository", lambda: order.append("gen-docs"))
    monkeypatch.setattr(module, "git_commit_version", lambda *_args, **_kwargs: order.append("commit"))
    monkeypatch.setattr(module, "git_commit_docs_repository", lambda *_args, **_kwargs: order.append("commit-docs"))
    monkeypatch.setattr(module, "compute_date_tag", lambda: "2026.04.23")
    monkeypatch.setattr(module, "update_public_release_references", lambda *_args, **_kwargs: order.append("release-refs"))
    monkeypatch.setattr(module, "create_and_push_tag", lambda *_args, **_kwargs: order.append("tag"))
    monkeypatch.setattr(module, "create_or_update_github_release", lambda *_args, **_kwargs: order.append("github-release"))

    module.main()

    assert order == [
        "preflight",
        "external-install-guard",
        "pre-upload-guard",
        "gen-docs",
        "coverage-workflow",
        "upload",
        "release-refs",
        "commit",
        "commit-docs",
        "tag",
        "github-release",
    ]


def test_pre_upload_release_guard_runs_before_irreversible_upload(monkeypatch) -> None:
    module = _load_pypi_publish()

    cfg = module.Cfg(
        repo="pypi",
        dist="both",
        skip_existing=True,
        retries=1,
        dry_run=False,
        verbose=False,
        version="2026.04.23",
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
    calls: list[str] = []

    monkeypatch.setattr(
        module,
        "update_public_release_references_for_guard",
        lambda *_args, **_kwargs: calls.append("release-refs-guard"),
    )
    monkeypatch.setattr(module, "run_release_preflight", lambda _cfg: calls.append("preflight"))

    def fake_run(cmd, **_kwargs):
        command_text = " ".join(str(part) for part in cmd)
        if "generate_component_coverage_badges.py" in command_text:
            calls.append("coverage-badge-refresh")
        elif "coverage_badge_guard.py" in command_text:
            assert "--require-fresh-xml" not in cmd
            if "--changed-only" in cmd:
                assert "--allow-badge-only" in cmd
                calls.append("coverage-guard-changed-only")
            else:
                assert "--allow-badge-only" not in cmd
                calls.append("coverage-guard-all")
        else:
            calls.append(command_text)

    monkeypatch.setattr(module, "run", fake_run)

    module.run_pre_upload_release_guard(
        cfg,
        planned_tag="2026.04.23",
        chosen_version="2026.04.23.post1",
        version_targets=["agilab"],
    )

    assert calls == [
        "release-refs-guard",
        "preflight",
        "coverage-badge-refresh",
        "coverage-guard-all",
        "coverage-guard-changed-only",
    ]


def test_release_coverage_workflow_prerequisite_triggers_and_waits(monkeypatch) -> None:
    module = _load_pypi_publish()
    cfg = _base_cfg(module, repo="pypi", git_tag=True)
    states = iter(
        [
            [],
            [{"status": "in_progress", "conclusion": "", "url": "https://example.test/runs/1"}],
            [{"status": "completed", "conclusion": "success", "url": "https://example.test/runs/1"}],
        ]
    )
    triggers: list[str] = []

    monkeypatch.setattr(module, "current_git_branch", lambda repo=module.REPO_ROOT: "main")
    monkeypatch.setattr(module, "_git_head_sha", lambda: "abc123def456")

    module.run_release_coverage_workflow_prerequisite(
        cfg,
        timeout_seconds=30,
        poll_seconds=1,
        list_runs_fn=lambda _sha: next(states),
        trigger_fn=lambda branch: triggers.append(branch),
        sleep_fn=lambda _seconds: None,
        time_fn=lambda: 0.0,
    )

    assert triggers == ["main"]


def test_release_coverage_workflow_prerequisite_blocks_failed_run(monkeypatch) -> None:
    module = _load_pypi_publish()
    cfg = _base_cfg(module, repo="pypi", git_tag=True)

    monkeypatch.setattr(module, "current_git_branch", lambda repo=module.REPO_ROOT: "main")
    monkeypatch.setattr(module, "_git_head_sha", lambda: "abc123def456")

    with pytest.raises(SystemExit, match="Coverage workflow prerequisite failed"):
        module.run_release_coverage_workflow_prerequisite(
            cfg,
            timeout_seconds=30,
            list_runs_fn=lambda _sha: [
                {"status": "completed", "conclusion": "failure", "url": "https://example.test/runs/1"}
            ],
            trigger_fn=lambda _branch: None,
            sleep_fn=lambda _seconds: None,
            time_fn=lambda: 0.0,
        )


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
    monkeypatch.setattr(module, "sync_builtin_app_versions", lambda *_args, **_kwargs: None)
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
