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

    assert profiles == ["agi-env", "agi-core-combined", "agi-gui", "docs", "installer", "shared-core-typing"]


def test_compute_unified_version_never_drops_below_latest_release(monkeypatch) -> None:
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

    chosen, collisions = module.compute_unified_version(
        ["agi-env", "agi-node", "agilab"],
        "pypi",
        None,
    )

    assert chosen == "2026.4.25.post1"
    assert collisions == {
        "agi-env": ["2026.4.25"],
        "agi-node": ["2026.4.25"],
        "agilab": ["2026.4.25"],
    }


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


def test_find_docs_repository_uses_docs_repository_env_name(tmp_path, monkeypatch) -> None:
    module = _load_pypi_publish()

    generic_docs_repo = tmp_path / "docs_repo"
    generic_docs_repo.mkdir()

    monkeypatch.setenv("DOCS_REPOSITORY", str(generic_docs_repo))
    monkeypatch.setattr(module, "_is_git_repo", lambda _path: True)

    repo, source = module.find_docs_repository()

    assert repo == generic_docs_repo.resolve()
    assert source == "env:DOCS_REPOSITORY"


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
    public_demo_test = tmp_path / "test" / "test_public_demo_links.py"
    public_demo_test.parent.mkdir(parents=True)
    public_demo_test.write_text("tests\n", encoding="utf-8")

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
        "CHANGELOG.md",
        "docs/.docs_source_mirror_stamp.json",
        "docs/source/index.rst",
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
    monkeypatch.setattr(module, "update_public_release_references", lambda *_args, **_kwargs: order.append("release-refs"))
    monkeypatch.setattr(module, "create_and_push_tag", lambda *_args, **_kwargs: order.append("tag"))
    monkeypatch.setattr(module, "create_or_update_github_release", lambda *_args, **_kwargs: order.append("github-release"))

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
    monkeypatch.setattr(module, "sync_builtin_app_versions", lambda _version: None)
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
    monkeypatch.setattr(module, "update_public_release_references", lambda *_args, **_kwargs: order.append("release-refs"))
    monkeypatch.setattr(module, "create_and_push_tag", lambda *_args, **_kwargs: order.append("tag"))
    monkeypatch.setattr(module, "create_or_update_github_release", lambda *_args, **_kwargs: order.append("github-release"))

    module.main()

    assert order == ["preflight", "release-refs", "commit", "tag", "github-release"]


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
    monkeypatch.setattr(module, "sync_builtin_app_versions", lambda _version: None)
    monkeypatch.setattr(module, "dist_files", lambda _project_dir: [str(project_dir / "dist" / "fake.whl")])
    monkeypatch.setattr(module, "twine_check", lambda _files: None)
    monkeypatch.setattr(module, "twine_upload", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "update_selected_badges", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "uv_build_project", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "run_release_preflight", lambda _cfg: order.append("preflight"))
    monkeypatch.setattr(module, "generate_docs_in_docs_repository", lambda: order.append("gen-docs"))
    monkeypatch.setattr(module, "git_commit_version", lambda *_args, **_kwargs: order.append("commit"))
    monkeypatch.setattr(module, "git_commit_docs_repository", lambda *_args, **_kwargs: order.append("commit-docs"))
    monkeypatch.setattr(module, "compute_date_tag", lambda: "2026.04.23")
    monkeypatch.setattr(module, "update_public_release_references", lambda *_args, **_kwargs: order.append("release-refs"))
    monkeypatch.setattr(module, "create_and_push_tag", lambda *_args, **_kwargs: order.append("tag"))
    monkeypatch.setattr(module, "create_or_update_github_release", lambda *_args, **_kwargs: order.append("github-release"))

    module.main()

    assert order == ["preflight", "gen-docs", "release-refs", "commit", "commit-docs", "tag", "github-release"]


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
