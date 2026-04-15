import os
from pathlib import Path, PurePosixPath

import pytest

from agi_cluster.agi_distributor import uv_source_support


def test_envar_truthy_handles_common_inputs_and_failures():
    assert uv_source_support.envar_truthy({"A": True}, "A") is True
    assert uv_source_support.envar_truthy({"A": 1}, "A") is True
    assert uv_source_support.envar_truthy({"A": 1.0}, "A") is True
    assert uv_source_support.envar_truthy({"A": " yes "}, "A") is True
    assert uv_source_support.envar_truthy({"A": "ON"}, "A") is True
    assert uv_source_support.envar_truthy({"A": None}, "A") is False
    assert uv_source_support.envar_truthy({"A": 2}, "A") is False
    assert uv_source_support.envar_truthy({"A": "off"}, "A") is False
    assert uv_source_support.envar_truthy({"A": float("nan")}, "A") is False

    class _BrokenEnv:
        def get(self, _key):
            raise RuntimeError("boom")

    assert uv_source_support.envar_truthy(_BrokenEnv(), "A") is False


def test_envar_truthy_propagates_unexpected_lookup_bug():
    class _BrokenEnv:
        def get(self, _key):
            raise ValueError("unexpected lookup bug")

    with pytest.raises(ValueError, match="unexpected lookup bug"):
        uv_source_support.envar_truthy(_BrokenEnv(), "A")


def test_ensure_optional_extras_noop_when_extras_empty(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    uv_source_support.ensure_optional_extras(pyproject, set())
    assert pyproject.exists() is False


def test_ensure_optional_extras_creates_and_updates_table(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[project]
name = "demo"
optional-dependencies = []
""".strip(),
        encoding="utf-8",
    )

    uv_source_support.ensure_optional_extras(pyproject, {"polars-worker", " ", "dag-worker"})
    content = pyproject.read_text(encoding="utf-8")
    assert "[project.optional-dependencies]" in content
    assert "polars-worker = []" in content
    assert "dag-worker = []" in content


def test_ensure_optional_extras_bootstraps_missing_pyproject(tmp_path):
    pyproject = tmp_path / "pyproject.toml"

    uv_source_support.ensure_optional_extras(pyproject, {"agent-worker"})

    content = pyproject.read_text(encoding="utf-8")
    assert "[project.optional-dependencies]" in content
    assert "agent-worker = []" in content


def test_rewrite_uv_sources_paths_rewrites_invalid_entries_and_logs(tmp_path, monkeypatch):
    src_dir = tmp_path / "src" / "worker"
    dst_dir = tmp_path / "dst" / "worker"
    src_dir.mkdir(parents=True, exist_ok=True)
    dst_dir.mkdir(parents=True, exist_ok=True)

    src_deps = src_dir.parent / "deps"
    (src_deps / "foo").mkdir(parents=True, exist_ok=True)
    (src_deps / "bar").mkdir(parents=True, exist_ok=True)
    (dst_dir / "keep-bar").mkdir(parents=True, exist_ok=True)

    src_pyproject = src_dir / "pyproject.toml"
    dst_pyproject = dst_dir / "pyproject.toml"

    src_pyproject.write_text(
        """
[tool.uv.sources]
foo = { path = "../deps/foo" }
bar = { path = "../deps/bar" }
missing = { path = "../deps/missing" }
blank = { path = "" }
non_dict = "value"
""".strip(),
        encoding="utf-8",
    )
    dst_pyproject.write_text(
        """
[tool.uv.sources]
foo = { path = "../bad/foo" }
bar = { path = "keep-bar" }
missing = { path = "../bad/missing" }
blank = { path = "../bad/blank" }
non_dict = { path = "../bad/non_dict" }
""".strip(),
        encoding="utf-8",
    )

    logs = []
    monkeypatch.setattr(
        uv_source_support.logger,
        "info",
        lambda *args, **kwargs: logs.append(args),
    )

    uv_source_support.rewrite_uv_sources_paths_for_copied_pyproject(
        src_pyproject=src_pyproject,
        dest_pyproject=dst_pyproject,
        log_rewrites=True,
    )

    content = dst_pyproject.read_text(encoding="utf-8")
    expected_rel_foo = os.path.relpath((src_deps / "foo").resolve(strict=False), start=dst_dir)
    assert f'foo = {{ path = "{expected_rel_foo}" }}' in content
    assert 'bar = { path = "keep-bar" }' in content
    assert 'missing = { path = "../bad/missing" }' in content
    assert any("Rewrote uv source" in str(entry[0]) for entry in logs if entry)


def test_rewrite_uv_sources_paths_ignores_missing_files(tmp_path):
    src_pyproject = tmp_path / "missing-src.toml"
    dst_pyproject = tmp_path / "missing-dst.toml"
    uv_source_support.rewrite_uv_sources_paths_for_copied_pyproject(
        src_pyproject=src_pyproject,
        dest_pyproject=dst_pyproject,
    )
    assert src_pyproject.exists() is False
    assert dst_pyproject.exists() is False


def test_stage_uv_sources_for_copied_pyproject_stages_sources(tmp_path, monkeypatch):
    src_dir = tmp_path / "src" / "worker"
    dst_dir = tmp_path / "dst"
    src_dir.mkdir(parents=True, exist_ok=True)
    dst_dir.mkdir(parents=True, exist_ok=True)

    src_deps = src_dir.parent / "deps"
    (src_deps / "foo").mkdir(parents=True, exist_ok=True)
    (src_deps / "foo" / "pyproject.toml").write_text("[project]\nname='foo'\n", encoding="utf-8")
    (src_deps / "foo" / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    (src_deps / "foo" / ".venv").mkdir(parents=True, exist_ok=True)
    (src_deps / "foo" / ".venv" / "skip.txt").write_text("x", encoding="utf-8")

    src_pyproject = src_dir / "pyproject.toml"
    dst_pyproject = dst_dir / "pyproject.toml"
    src_pyproject.write_text(
        """
[tool.uv.sources]
foo = { path = "../deps/foo" }
""".strip(),
        encoding="utf-8",
    )
    dst_pyproject.write_text(
        """
[tool.uv.sources]
foo = { path = "../bad/foo" }
""".strip(),
        encoding="utf-8",
    )

    logs = []
    monkeypatch.setattr(
        uv_source_support.logger,
        "info",
        lambda *args, **kwargs: logs.append(args),
    )

    staged_entries = uv_source_support.stage_uv_sources_for_copied_pyproject(
        src_pyproject=src_pyproject,
        dest_pyproject=dst_pyproject,
        stage_root=dst_dir,
        log_rewrites=True,
    )

    staged_root = dst_dir / "_uv_sources"
    staged_dep = staged_root / "foo"
    assert staged_entries == [staged_root]
    assert staged_dep.exists()
    assert (staged_dep / "module.py").exists()
    assert not (staged_dep / ".venv").exists()
    assert 'foo = { path = "_uv_sources/foo" }' in dst_pyproject.read_text(encoding="utf-8")
    assert any("Staged uv source" in str(entry[0]) for entry in logs if entry)


def test_stage_uv_sources_for_copied_pyproject_stages_nested_sources(tmp_path):
    src_dir = tmp_path / "src" / "worker"
    dst_dir = tmp_path / "dst"
    src_dir.mkdir(parents=True, exist_ok=True)
    dst_dir.mkdir(parents=True, exist_ok=True)

    deps_dir = src_dir.parent / "deps"
    trainer_dir = deps_dir / "sb3_trainer_project"
    sat_dir = deps_dir / "sat_trajectory_project"
    trainer_dir.mkdir(parents=True, exist_ok=True)
    sat_dir.mkdir(parents=True, exist_ok=True)

    (trainer_dir / "pyproject.toml").write_text(
        """
[project]
name = "sb3_trainer_project"

[tool.uv.sources."sat-trajectory-project"]
path = "../sat_trajectory_project"
""".strip(),
        encoding="utf-8",
    )
    (trainer_dir / "trainer.py").write_text("TRAINER = 1\n", encoding="utf-8")
    (sat_dir / "pyproject.toml").write_text("[project]\nname='sat_trajectory_project'\n", encoding="utf-8")
    (sat_dir / "sat.py").write_text("SAT = 1\n", encoding="utf-8")

    src_pyproject = src_dir / "pyproject.toml"
    dst_pyproject = dst_dir / "pyproject.toml"
    src_pyproject.write_text(
        """
[tool.uv.sources]
sb3_trainer_project = { path = "../deps/sb3_trainer_project" }
""".strip(),
        encoding="utf-8",
    )
    dst_pyproject.write_text(
        """
[tool.uv.sources]
sb3_trainer_project = { path = "../bad/sb3_trainer_project" }
""".strip(),
        encoding="utf-8",
    )

    staged_entries = uv_source_support.stage_uv_sources_for_copied_pyproject(
        src_pyproject=src_pyproject,
        dest_pyproject=dst_pyproject,
        stage_root=dst_dir,
    )

    staged_root = dst_dir / "_uv_sources"
    staged_trainer = staged_root / "sb3_trainer_project"
    staged_sat = staged_root / "sat-trajectory-project"

    assert staged_entries == [staged_root]
    assert staged_trainer.exists()
    assert staged_sat.exists()
    assert 'sb3_trainer_project = { path = "_uv_sources/sb3_trainer_project" }' in dst_pyproject.read_text(encoding="utf-8")
    assert 'path = "../sat-trajectory-project"' in (staged_trainer / "pyproject.toml").read_text(encoding="utf-8")


def test_rewrite_uv_sources_paths_for_copied_pyproject_rewrites_invalid_paths_and_keeps_valid_ones(tmp_path, monkeypatch):
    src_dir = tmp_path / "src"
    dest_dir = tmp_path / "dest"
    src_dir.mkdir()
    dest_dir.mkdir()

    rel_dep = src_dir / "deps" / "foo"
    rel_dep.mkdir(parents=True)
    abs_dep = tmp_path / "abs-dep"
    abs_dep.mkdir()
    valid_dest = dest_dir / "vendored" / "baz"
    valid_dest.mkdir(parents=True)

    src_pyproject = src_dir / "pyproject.toml"
    dest_pyproject = dest_dir / "pyproject.toml"
    src_pyproject.write_text(
        f"""
[tool.uv.sources]
foo = {{ path = "deps/foo" }}
bar = {{ path = "{abs_dep}" }}
baz = {{ path = "deps/foo" }}
skip_meta = 3
blank = {{ path = "" }}
missing = {{ path = "deps/missing" }}
""".strip(),
        encoding="utf-8",
    )
    dest_pyproject.write_text(
        f"""
[tool.uv.sources]
foo = {{ path = "../broken/foo" }}
bar = {{ path = "../broken/bar" }}
baz = {{ path = "vendored/baz" }}
skip_meta = {{ path = "../ignored" }}
blank = {{ path = "../ignored-blank" }}
missing = {{ path = "../ignored-missing" }}
""".strip(),
        encoding="utf-8",
    )

    logs = []
    monkeypatch.setattr(uv_source_support.logger, "info", lambda *args, **kwargs: logs.append(args))

    uv_source_support.rewrite_uv_sources_paths_for_copied_pyproject(
        src_pyproject=src_pyproject,
        dest_pyproject=dest_pyproject,
        log_rewrites=True,
    )

    content = dest_pyproject.read_text(encoding="utf-8")
    assert 'foo = { path = "../src/deps/foo" }' in content
    assert f'bar = {{ path = "{os.path.relpath(abs_dep, start=dest_dir)}" }}' in content
    assert 'baz = { path = "vendored/baz" }' in content
    assert 'blank = { path = "../ignored-blank" }' in content
    assert 'missing = { path = "../ignored-missing" }' in content
    assert any("Rewrote uv source" in str(entry[0]) for entry in logs if entry)


def test_rewrite_uv_sources_paths_for_copied_pyproject_handles_missing_files_and_relpath_failures(tmp_path, monkeypatch):
    src_dir = tmp_path / "src"
    dest_dir = tmp_path / "dest"
    src_dir.mkdir()
    dest_dir.mkdir()
    dep = src_dir / "dep"
    dep.mkdir()

    src_pyproject = src_dir / "pyproject.toml"
    dest_pyproject = dest_dir / "pyproject.toml"
    src_pyproject.write_text('[tool.uv.sources]\nfoo = { path = "dep" }\nnot_a_table = "skip"\n', encoding="utf-8")
    dest_pyproject.write_text('[tool.uv.sources]\nfoo = { path = "../old" }\nnot_a_table = { path = "../unchanged" }\n', encoding="utf-8")

    monkeypatch.setattr(uv_source_support.os.path, "relpath", lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("boom")))

    uv_source_support.rewrite_uv_sources_paths_for_copied_pyproject(
        src_pyproject=src_pyproject,
        dest_pyproject=dest_pyproject,
    )

    assert f'foo = {{ path = "{dep.resolve(strict=False)}" }}' in dest_pyproject.read_text(encoding="utf-8")
    uv_source_support.rewrite_uv_sources_paths_for_copied_pyproject(
        src_pyproject=tmp_path / "missing-src.toml",
        dest_pyproject=dest_pyproject,
    )


def test_rewrite_uv_sources_paths_for_copied_pyproject_propagates_unexpected_relpath_bug(tmp_path, monkeypatch):
    src_dir = tmp_path / "src"
    dest_dir = tmp_path / "dest"
    src_dir.mkdir()
    dest_dir.mkdir()
    dep = src_dir / "dep"
    dep.mkdir()

    src_pyproject = src_dir / "pyproject.toml"
    dest_pyproject = dest_dir / "pyproject.toml"
    src_pyproject.write_text('[tool.uv.sources]\nfoo = { path = "dep" }\n', encoding="utf-8")
    dest_pyproject.write_text('[tool.uv.sources]\nfoo = { path = "../old" }\n', encoding="utf-8")

    monkeypatch.setattr(uv_source_support.os.path, "relpath", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("unexpected relpath bug")))

    with pytest.raises(RuntimeError, match="unexpected relpath bug"):
        uv_source_support.rewrite_uv_sources_paths_for_copied_pyproject(
            src_pyproject=src_pyproject,
            dest_pyproject=dest_pyproject,
        )


def test_stage_uv_sources_for_copied_pyproject_falls_back_when_relpath_fails(tmp_path, monkeypatch):
    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst"
    src_dir.mkdir()
    dst_dir.mkdir()
    dep = src_dir / "dep"
    dep.mkdir()
    (dep / "pyproject.toml").write_text("[project]\nname='dep'\n", encoding="utf-8")

    src_pyproject = src_dir / "pyproject.toml"
    dest_pyproject = dst_dir / "pyproject.toml"
    src_pyproject.write_text('[tool.uv.sources]\nfoo = { path = "dep" }\n', encoding="utf-8")
    dest_pyproject.write_text('[tool.uv.sources]\nfoo = { path = "../old" }\n', encoding="utf-8")

    monkeypatch.setattr(uv_source_support.os.path, "relpath", lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("boom")))

    staged_entries = uv_source_support.stage_uv_sources_for_copied_pyproject(
        src_pyproject=src_pyproject,
        dest_pyproject=dest_pyproject,
        stage_root=dst_dir,
    )

    staged_target = dst_dir / "_uv_sources" / "foo"
    assert staged_entries == [dst_dir / "_uv_sources"]
    assert f'foo = {{ path = "{staged_target}" }}' in dest_pyproject.read_text(encoding="utf-8")


def test_stage_uv_sources_for_copied_pyproject_propagates_unexpected_relpath_bug(tmp_path, monkeypatch):
    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst"
    src_dir.mkdir()
    dst_dir.mkdir()
    dep = src_dir / "dep"
    dep.mkdir()
    (dep / "pyproject.toml").write_text("[project]\nname='dep'\n", encoding="utf-8")

    src_pyproject = src_dir / "pyproject.toml"
    dest_pyproject = dst_dir / "pyproject.toml"
    src_pyproject.write_text('[tool.uv.sources]\nfoo = { path = "dep" }\n', encoding="utf-8")
    dest_pyproject.write_text('[tool.uv.sources]\nfoo = { path = "../old" }\n', encoding="utf-8")

    monkeypatch.setattr(uv_source_support.os.path, "relpath", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("unexpected relpath bug")))

    with pytest.raises(RuntimeError, match="unexpected relpath bug"):
        uv_source_support.stage_uv_sources_for_copied_pyproject(
            src_pyproject=src_pyproject,
            dest_pyproject=dest_pyproject,
            stage_root=dst_dir,
        )


def test_copy_uv_source_tree_replaces_existing_file_destination(tmp_path):
    source = tmp_path / "source.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    destination = tmp_path / "staged" / "source.py"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("old\n", encoding="utf-8")

    uv_source_support.copy_uv_source_tree(source, destination)

    assert destination.read_text(encoding="utf-8") == "VALUE = 1\n"


def test_missing_uv_source_paths_reports_unresolved_entries(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    (tmp_path / "_uv_sources" / "ok").mkdir(parents=True, exist_ok=True)
    pyproject.write_text(
        """
[tool.uv.sources]
ok = { path = "_uv_sources/ok" }
missing = { path = "_uv_sources/missing" }
""".strip(),
        encoding="utf-8",
    )

    missing = uv_source_support.missing_uv_source_paths(pyproject)
    assert missing == [("missing", "_uv_sources/missing")]


def test_missing_uv_source_paths_and_validation_cover_edge_cases(tmp_path):
    assert uv_source_support.missing_uv_source_paths(tmp_path / "missing.toml") == []

    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[tool.uv.sources]
a = { path = "_uv_sources/a" }
b = { path = "_uv_sources/b" }
c = { path = "_uv_sources/c" }
d = { path = "_uv_sources/d" }
e = { path = "_uv_sources/e" }
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match=r"\+1 more"):
        uv_source_support.validate_worker_uv_sources(pyproject)


def test_validate_worker_uv_sources_raises_actionable_error(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[tool.uv.sources]
ilp_worker = { path = "../../PycharmProjects/thales_agilab/apps/ilp_project/src/ilp_worker" }
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="stale or incomplete"):
        uv_source_support.validate_worker_uv_sources(pyproject)


def test_staged_uv_sources_pth_content_relative_for_local_paths(tmp_path):
    site_packages = tmp_path / "wenv" / ".venv" / "lib" / "python3.13" / "site-packages"
    uv_sources = tmp_path / "wenv" / "_uv_sources"
    content = uv_source_support.staged_uv_sources_pth_content(site_packages, uv_sources)
    assert content == "../../../../_uv_sources\n"


def test_staged_uv_sources_pth_content_relative_for_remote_posix_paths():
    site_packages = PurePosixPath("wenv/.venv/lib/python3.13/site-packages")
    uv_sources = PurePosixPath("wenv/_uv_sources")
    content = uv_source_support.staged_uv_sources_pth_content(site_packages, uv_sources)
    assert content == "../../../../_uv_sources\n"


def test_worker_site_packages_dir_and_pth_writer_branches(tmp_path):
    windows_path = uv_source_support.worker_site_packages_dir(Path("worker"), "3.13", windows=True)
    free_threaded = uv_source_support.worker_site_packages_dir(Path("worker"), "3.13t")
    assert windows_path == Path("worker/.venv/Lib/site-packages")
    assert free_threaded == Path("worker/.venv/lib/python3.13t/site-packages")

    site_packages = tmp_path / "worker" / ".venv" / "lib" / "python3.13" / "site-packages"
    site_packages.mkdir(parents=True, exist_ok=True)
    pth_path = site_packages / "agilab_uv_sources.pth"
    pth_path.write_text("stale\n", encoding="utf-8")

    assert uv_source_support.write_staged_uv_sources_pth(site_packages, tmp_path / "missing") is None
    assert not pth_path.exists()

    uv_sources = tmp_path / "worker" / "_uv_sources"
    uv_sources.mkdir(parents=True, exist_ok=True)
    written = uv_source_support.write_staged_uv_sources_pth(site_packages, uv_sources)
    assert written == pth_path
    assert pth_path.read_text(encoding="utf-8").endswith("_uv_sources\n")
