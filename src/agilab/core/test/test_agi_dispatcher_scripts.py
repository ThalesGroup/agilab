import os
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from agi_node.agi_dispatcher import build as build_mod
from agi_node.agi_dispatcher import post_install as post_mod
from agi_node.agi_dispatcher import pre_install as pre_mod


def test_pre_install_get_decorator_name_variants():
    tree = pre_mod.parso.parse("@alpha\n@beta(1)\ndef func():\n    return 1\n")
    decorated = tree.children[0]
    decorators = decorated.children[0].children
    assert pre_mod.get_decorator_name(decorators[0]) == "alpha"
    assert pre_mod.get_decorator_name(decorators[1]) == "beta"


def test_pre_install_remove_decorators_by_name():
    source = "@keep\n@drop\ndef func():\n    return 1\n"
    out = pre_mod.remove_decorators(source, decorator_names=["drop"], verbose=False)
    assert "@drop" not in out
    assert "@keep" in out
    assert "def func" in out


def test_pre_install_prepare_for_cython_writes_pyx(tmp_path, monkeypatch):
    worker_py = tmp_path / "demo_worker.py"
    worker_py.write_text("value = 1\n", encoding="utf-8")

    monkeypatch.setattr(
        pre_mod,
        "remove_decorators",
        lambda source, verbose=True: source.replace("value", "prepared"),
    )
    args = Namespace(
        worker_path=str(worker_py),
        cython_target_src_ext=".py",
        verbose=False,
    )
    pre_mod.prepare_for_cython(args)

    pyx_path = worker_py.with_suffix(".pyx")
    assert pyx_path.exists()
    assert "prepared = 1" in pyx_path.read_text(encoding="utf-8")


def test_post_iter_data_files_and_has_samples(tmp_path):
    data_dir = tmp_path / "dataset"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "a.csv").write_text("x\n1\n", encoding="utf-8")
    (data_dir / "b.parquet").write_text("pq", encoding="utf-8")
    (data_dir / "._ignored.csv").write_text("hidden", encoding="utf-8")
    files = post_mod._iter_data_files(data_dir)
    assert [p.name for p in files] == ["a.csv", "b.parquet"]
    assert post_mod._has_samples(data_dir) is True


def test_post_dir_is_duplicate_of(tmp_path):
    src_dir = tmp_path / "src"
    ref_dir = tmp_path / "ref"
    src_dir.mkdir()
    ref_dir.mkdir()

    (src_dir / "a.csv").write_text("111", encoding="utf-8")
    (src_dir / "b.csv").write_text("222", encoding="utf-8")
    (ref_dir / "a.csv").write_text("111", encoding="utf-8")
    (ref_dir / "b.csv").write_text("222", encoding="utf-8")
    (ref_dir / "c.csv").write_text("333", encoding="utf-8")

    assert post_mod._dir_is_duplicate_of(src_dir, ref_dir) is True
    (src_dir / "extra.txt").write_text("x", encoding="utf-8")
    assert post_mod._dir_is_duplicate_of(src_dir, ref_dir) is False


def test_post_generated_trajectory_name_detection():
    assert post_mod._looks_like_generated_trajectory(Path("sat_trajectory.csv"))
    assert post_mod._looks_like_generated_trajectory(Path("starlink-2026.csv"))
    assert post_mod._looks_like_generated_trajectory(Path("flight_traj.parquet"))
    assert post_mod._looks_like_generated_trajectory(Path("flight_traj.csv"))
    assert post_mod._looks_like_generated_trajectory(Path("flight_trajectory.pq"))
    assert not post_mod._looks_like_generated_trajectory(Path("baseline.csv"))


def test_post_folder_looks_large_for_generated_or_many_files(tmp_path):
    generated = tmp_path / "generated"
    generated.mkdir()
    (generated / "a_trajectory.csv").write_text("x", encoding="utf-8")
    (generated / "b.csv").write_text("y", encoding="utf-8")
    assert post_mod._folder_looks_large(generated) is True

    many = tmp_path / "many"
    many.mkdir()
    for idx in range(25):
        (many / f"{idx}.csv").write_text("1", encoding="utf-8")
    assert post_mod._folder_looks_large(many) is True


def test_post_try_link_dir_replaces_empty_dir(tmp_path):
    link_path = tmp_path / "dataset" / "sat"
    target_path = tmp_path / "trajectory"
    target_path.mkdir(parents=True, exist_ok=True)
    (target_path / "a.csv").write_text("1", encoding="utf-8")
    (target_path / "b.csv").write_text("2", encoding="utf-8")

    link_path.mkdir(parents=True, exist_ok=True)
    ok = post_mod._try_link_dir(link_path, target_path)
    assert ok is True
    assert link_path.exists()
    assert link_path.resolve(strict=False) == target_path.resolve(strict=False)


def test_post_dataset_archive_candidates_deduplicates(tmp_path):
    class DummyEnv:
        share_target_name = "mycode"
        dataset_archive = tmp_path / "dataset.7z"
        agilab_pck = tmp_path

    env = DummyEnv()
    candidates = post_mod._dataset_archive_candidates(env)
    assert len(candidates) == 2
    assert candidates[0] == env.dataset_archive
    assert candidates[1].name == "dataset.7z"
    assert "apps" in candidates[1].as_posix()


def test_build_parse_custom_args_and_remaining():
    opts = build_mod.parse_custom_args(
        ["build_ext", "--packages", "a,b", "-b", "/tmp/out", "--flag"],
        Path("/tmp/app"),
    )
    assert opts.command == "build_ext"
    assert opts.packages == ["a", "b"]
    assert opts.build_dir == "/tmp/out"
    assert opts.remaining == ["--flag"]


def test_build_truncate_path_at_segment_uses_last_match():
    path = "/x/alpha_worker/y/beta_worker/file.py"
    truncated = build_mod.truncate_path_at_segment(path)
    assert truncated.as_posix() == "/x/alpha_worker/y/beta_worker"
    with pytest.raises(ValueError):
        build_mod.truncate_path_at_segment("/x/no/segment/here.py")


def test_build_find_sys_prefix_prefers_python_dirs(tmp_path):
    python_dir = tmp_path / "Python313"
    python_dir.mkdir(parents=True, exist_ok=True)
    build_mod.AgiEnv.logger = type("Logger", (), {"info": staticmethod(lambda *_args, **_kwargs: None)})()
    assert build_mod.find_sys_prefix(str(tmp_path)) == str(python_dir)


def test_build_fix_windows_drive(monkeypatch):
    monkeypatch.setattr(build_mod.os, "name", "nt", raising=False)
    assert build_mod._fix_windows_drive(r"C:Users\me") == r"C:\Users\me"
    assert build_mod._fix_windows_drive(r"C:\Users\me") == r"C:\Users\me"


def test_build_relative_to_home():
    home = Path.home()
    inside = home / "tmp" / "demo"
    outside = Path("/tmp/agilab-demo-outside")
    assert build_mod._relative_to_home(inside) == Path("tmp") / "demo"
    assert build_mod._relative_to_home(outside) == outside


def test_build_keep_lflag(tmp_path):
    existing = tmp_path / "libs"
    existing.mkdir(parents=True, exist_ok=True)
    assert build_mod._keep_lflag("-Wl,--as-needed") is True
    assert build_mod._keep_lflag(f"-L{existing}") is True
    assert build_mod._keep_lflag("-L/definitely/missing/path") is False


def test_build_create_symlink_for_module_uses_symlink_on_unmanaged_host(tmp_path, monkeypatch):
    src_abs = tmp_path / "app-src" / "demo_worker"
    src_abs.mkdir(parents=True, exist_ok=True)
    env = SimpleNamespace(
        agi_node=tmp_path / "agi-node",
        agi_env=tmp_path / "agi-env",
        target_worker="demo_worker",
        app_src=tmp_path / "app-src",
    )

    created = []
    monkeypatch.setattr(build_mod.AgiEnv, "_is_managed_pc", False, raising=False)
    monkeypatch.setattr(build_mod.AgiEnv, "create_symlink", lambda src, dest: created.append((Path(src), Path(dest))))
    monkeypatch.setattr(build_mod.os, "link", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("hard link should not be used")))

    links = build_mod.create_symlink_for_module(env, "demo_worker")

    assert len(links) == 1
    assert created[0][0] == src_abs
    assert created[0][1] == links[0]
    assert links[0].name == "demo_worker"


def test_build_create_symlink_for_module_falls_back_to_hard_link(tmp_path, monkeypatch):
    src_abs = tmp_path / "agi-env" / "agi_env" / "pkg"
    src_abs.mkdir(parents=True, exist_ok=True)
    env = SimpleNamespace(
        agi_node=tmp_path / "agi-node",
        agi_env=tmp_path / "agi-env",
        target_worker="demo_worker",
        app_src=tmp_path / "app-src",
    )

    created_hard_links = []
    build_mod.AgiEnv.logger = SimpleNamespace(
        info=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
        error=lambda *args, **kwargs: None,
        debug=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(build_mod.AgiEnv, "_is_managed_pc", False, raising=False)
    monkeypatch.setattr(
        build_mod.AgiEnv,
        "create_symlink",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("no symlink")),
    )
    monkeypatch.setattr(build_mod.os, "link", lambda src, dest: created_hard_links.append((Path(src), Path(dest))))

    links = build_mod.create_symlink_for_module(env, "agi_env.pkg")

    assert len(links) == 1
    assert created_hard_links[0][0] == src_abs
    assert created_hard_links[0][1] == links[0]
    assert links[0].name == "pkg"


def test_build_cleanup_links_removes_empty_parent_tree(tmp_path):
    link = tmp_path / "src" / "agi_node" / "demo_worker"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.write_text("x", encoding="utf-8")

    build_mod.cleanup_links([link])

    assert not link.exists()
    assert not link.parent.exists()


def test_build_cleanup_links_stops_when_parent_not_empty(tmp_path):
    link = tmp_path / "src" / "agi_node" / "demo_worker"
    sibling = tmp_path / "src" / "agi_node" / "keep.txt"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.write_text("x", encoding="utf-8")
    sibling.write_text("keep", encoding="utf-8")

    build_mod.cleanup_links([link])

    assert not link.exists()
    assert sibling.exists()
    assert link.parent.exists()


def test_post_main_invalid_args_returns_usage_code():
    assert post_mod.main([]) == 1
    assert post_mod.main(["a", "b"]) == 1


def test_post_main_relative_app_arg_uses_home_wenv(tmp_path, monkeypatch):
    captured = {}

    class DummyEnv:
        share_target_name = "demo"
        dataset_archive = tmp_path / "missing.7z"
        agilab_pck = tmp_path / "pkg"

        def resolve_share_path(self, _target):
            return tmp_path / "share"

        def unzip_data(self, _archive, _dest):
            raise AssertionError("unzip_data should not be called when archive is missing")

        def share_root_path(self):
            return tmp_path / "share-root"

    monkeypatch.setattr(post_mod.Path, "home", staticmethod(lambda: tmp_path))

    def _fake_build_env(app_arg):
        captured["app_arg"] = app_arg
        return DummyEnv()

    monkeypatch.setattr(post_mod, "_build_env", _fake_build_env)
    monkeypatch.setattr(post_mod, "_dataset_archive_candidates", lambda _env: [tmp_path / "missing.7z"])

    assert post_mod.main(["demo_project"]) == 0
    assert captured["app_arg"] == tmp_path / "wenv" / "demo_project"


def test_post_main_missing_archive_returns_zero_without_unzip(tmp_path, monkeypatch):
    flags = {"unzipped": False}

    class DummyEnv:
        share_target_name = "demo"
        dataset_archive = tmp_path / "missing.7z"
        agilab_pck = tmp_path / "pkg"

        def resolve_share_path(self, _target):
            return tmp_path / "share"

        def unzip_data(self, _archive, _dest):
            flags["unzipped"] = True

        def share_root_path(self):
            return tmp_path / "share-root"

    monkeypatch.setattr(post_mod, "_build_env", lambda _app_arg: DummyEnv())
    monkeypatch.setattr(post_mod, "_dataset_archive_candidates", lambda _env: [tmp_path / "missing.7z"])

    assert post_mod.main([str(tmp_path / "demo_project")]) == 0
    assert flags["unzipped"] is False


def test_post_main_links_preferred_sat_trajectory(tmp_path, monkeypatch):
    dataset_archive = tmp_path / "dataset.7z"
    dataset_archive.write_text("x", encoding="utf-8")
    share_root = tmp_path / "share"
    preferred = share_root / "sat_trajectory" / "dataset" / "Trajectory"
    preferred.mkdir(parents=True, exist_ok=True)
    (preferred / "a.csv").write_text("1", encoding="utf-8")
    (preferred / "b.csv").write_text("2", encoding="utf-8")

    class DummyEnv:
        def __init__(self):
            self.share_target_name = "demo"
            self.dataset_archive = dataset_archive
            self.agilab_pck = tmp_path / "pkg"

        def resolve_share_path(self, _target):
            return tmp_path / "share-dest"

        def unzip_data(self, _archive, dest):
            (Path(dest) / "dataset").mkdir(parents=True, exist_ok=True)

        def share_root_path(self):
            return share_root

    link_calls = []

    def _fake_try_link(link_path, target_path):
        link_calls.append((Path(link_path), Path(target_path)))
        return True

    monkeypatch.setattr(post_mod, "_build_env", lambda _app_arg: DummyEnv())
    monkeypatch.setattr(post_mod, "_dataset_archive_candidates", lambda _env: [dataset_archive])
    monkeypatch.setattr(post_mod, "_try_link_dir", _fake_try_link)

    assert post_mod.main([str(tmp_path / "demo_project")]) == 0
    assert len(link_calls) == 1
    assert link_calls[0][0].name == "sat"
    assert link_calls[0][1] == preferred


def test_post_main_respects_preserve_existing_sat_flag(tmp_path, monkeypatch):
    dataset_archive = tmp_path / "dataset.7z"
    dataset_archive.write_text("x", encoding="utf-8")
    share_root = tmp_path / "share"
    preferred = share_root / "sat_trajectory" / "dataset" / "Trajectory"
    preferred.mkdir(parents=True, exist_ok=True)
    (preferred / "a.csv").write_text("1", encoding="utf-8")
    (preferred / "b.csv").write_text("2", encoding="utf-8")

    class DummyEnv:
        def __init__(self):
            self.share_target_name = "demo"
            self.dataset_archive = dataset_archive
            self.agilab_pck = tmp_path / "pkg"

        def resolve_share_path(self, _target):
            return tmp_path / "share-dest"

        def unzip_data(self, _archive, dest):
            sat = Path(dest) / "dataset" / "sat"
            sat.mkdir(parents=True, exist_ok=True)
            (sat / "x.csv").write_text("1", encoding="utf-8")
            (sat / "y.csv").write_text("2", encoding="utf-8")

        def share_root_path(self):
            return share_root

    called = {"link": False}

    monkeypatch.setattr(post_mod, "_build_env", lambda _app_arg: DummyEnv())
    monkeypatch.setattr(post_mod, "_dataset_archive_candidates", lambda _env: [dataset_archive])
    monkeypatch.setenv("AGILAB_PRESERVE_LINK_SIM_SAT", "1")
    monkeypatch.setattr(post_mod, "_try_link_dir", lambda *_args, **_kwargs: called.update(link=True))

    assert post_mod.main([str(tmp_path / "demo_project")]) == 0
    assert called["link"] is False


def test_post_main_extracts_then_copies_when_link_unavailable(tmp_path, monkeypatch):
    dataset_archive = tmp_path / "dataset.7z"
    dataset_archive.write_text("x", encoding="utf-8")
    trajectory_archive = tmp_path / "Trajectory.7z"
    trajectory_archive.write_text("x", encoding="utf-8")

    class DummyEnv:
        def __init__(self):
            self.share_target_name = "demo"
            self.dataset_archive = dataset_archive
            self.agilab_pck = tmp_path / "pkg"

        def resolve_share_path(self, _target):
            return tmp_path / "share-dest"

        def unzip_data(self, _archive, dest):
            (Path(dest) / "dataset" / "sat").mkdir(parents=True, exist_ok=True)

        def share_root_path(self):
            return tmp_path / "share"

    def _fake_extract(_archive, dest):
        traj = Path(dest) / "Trajectory"
        traj.mkdir(parents=True, exist_ok=True)
        (traj / "a.csv").write_text("1", encoding="utf-8")
        (traj / "b.csv").write_text("2", encoding="utf-8")

    monkeypatch.setattr(post_mod, "_build_env", lambda _app_arg: DummyEnv())
    monkeypatch.setattr(post_mod, "_dataset_archive_candidates", lambda _env: [dataset_archive])
    monkeypatch.setattr(post_mod, "_extract_archive", _fake_extract)
    monkeypatch.setattr(post_mod, "_try_link_dir", lambda *_args, **_kwargs: False)

    assert post_mod.main([str(tmp_path / "demo_project")]) == 0
    sat = tmp_path / "share-dest" / "dataset" / "sat"
    assert (sat / "a.csv").exists()
    assert (sat / "b.csv").exists()


def test_post_main_ignores_optional_seeding_exception(tmp_path, monkeypatch):
    dataset_archive = tmp_path / "dataset.7z"
    dataset_archive.write_text("x", encoding="utf-8")

    class DummyEnv:
        def __init__(self):
            self.share_target_name = "demo"
            self.dataset_archive = dataset_archive
            self.agilab_pck = tmp_path / "pkg"

        def resolve_share_path(self, _target):
            return tmp_path / "share-dest"

        def unzip_data(self, _archive, dest):
            (Path(dest) / "dataset").mkdir(parents=True, exist_ok=True)

        def share_root_path(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(post_mod, "_build_env", lambda _app_arg: DummyEnv())
    monkeypatch.setattr(post_mod, "_dataset_archive_candidates", lambda _env: [dataset_archive])

    assert post_mod.main([str(tmp_path / "demo_project")]) == 0


class _DummyLogger:
    def info(self, *_args, **_kwargs):
        return None

    def warning(self, *_args, **_kwargs):
        return None

    def error(self, *_args, **_kwargs):
        return None

    def debug(self, *_args, **_kwargs):
        return None


def test_build_create_symlink_for_module_hardlink_fallback(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source_file = tmp_path / "app" / "demo_worker" / "module_a"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_text("payload", encoding="utf-8")

    env = SimpleNamespace(
        agi_node=tmp_path / "agi_node",
        agi_env=tmp_path / "agi_env",
        target_worker="demo_worker",
        app_src=tmp_path / "app",
    )

    monkeypatch.setattr(build_mod.AgiEnv, "_is_managed_pc", False, raising=False)
    monkeypatch.setattr(build_mod.AgiEnv, "logger", _DummyLogger(), raising=False)
    monkeypatch.setattr(
        build_mod.AgiEnv,
        "create_symlink",
        staticmethod(lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("symlink disabled"))),
        raising=False,
    )

    links = build_mod.create_symlink_for_module(env, "demo_worker.module_a")
    assert len(links) == 1
    dest = links[0]
    assert dest.exists()
    assert os.path.samefile(dest, source_file)


def test_build_cleanup_links_removes_file_and_empty_parents(tmp_path):
    target = tmp_path / "a" / "agi_node" / "demo" / "payload.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("x", encoding="utf-8")

    build_mod.cleanup_links([target])
    assert not target.exists()
    assert not (tmp_path / "a" / "agi_node" / "demo").exists()


def test_build_main_build_ext_invokes_pre_install_and_setup(tmp_path, monkeypatch):
    app_dir = tmp_path / "demo_project"
    (app_dir / "src" / "demo_worker").mkdir(parents=True, exist_ok=True)
    worker_home = tmp_path / "home"
    worker_file = worker_home / "workers" / "demo_worker.py"
    worker_file.parent.mkdir(parents=True, exist_ok=True)
    worker_file.write_text("value = 1\n", encoding="utf-8")
    pre_script = tmp_path / "pre_install.py"
    pre_script.write_text("print('ok')\n", encoding="utf-8")
    out_dir = worker_home / "demo_worker"
    out_dir.mkdir(parents=True, exist_ok=True)

    class DummyAgiEnv:
        logger = _DummyLogger()
        _is_managed_pc = False

        @staticmethod
        def create_symlink(src, dest):
            os.symlink(src, dest)

        @staticmethod
        def create_junction_windows(_src, _dest):
            return None

        init_args = None

        def __init__(self, *, apps_path=None, active_app, verbose):
            DummyAgiEnv.init_args = {
                "apps_path": apps_path,
                "active_app": active_app,
                "verbose": verbose,
            }
            self.home_abs = str(worker_home)
            self.worker_path = str(worker_file.relative_to(worker_home))
            self.pre_install = str(pre_script)
            self.verbose = verbose
            self.pyvers_worker = "3.13"
            self.is_worker_env = True
            self.active_app = app_dir
            self.target_worker = "demo_worker"
            self.agi_node = tmp_path / "agi_node"
            self.agi_env = tmp_path / "agi_env"
            self.app_src = app_dir

    monkeypatch.setattr(build_mod, "AgiEnv", DummyAgiEnv)
    monkeypatch.setattr(build_mod, "find_sys_prefix", lambda _base: str(tmp_path / "prefix"))
    monkeypatch.setattr(build_mod, "find_packages", lambda where="src": ["demo_worker"])

    run_calls = []
    monkeypatch.setattr(build_mod.subprocess, "run", lambda cmd, check=True: run_calls.append((cmd, check)))
    cythonize_calls = []
    monkeypatch.setattr(
        build_mod,
        "cythonize",
        lambda modules, language_level=3, quiet=False, compiler_directives=None: (
            cythonize_calls.append((modules, quiet, compiler_directives)) or ["ext_mod"]
        ),
    )
    setup_calls = []
    monkeypatch.setattr(build_mod, "setup", lambda **kwargs: setup_calls.append(kwargs))

    build_mod.main(
        [
            "--app-path",
            str(app_dir),
            "build_ext",
            "-b",
            str(out_dir),
            "--packages",
            "pkg_a,pkg_b",
            "--quiet",
        ]
    )

    assert DummyAgiEnv.init_args is not None
    assert DummyAgiEnv.init_args["apps_path"] is None
    assert Path(DummyAgiEnv.init_args["active_app"]) == app_dir
    assert run_calls, "Expected pre_install subprocess to run when .pyx is missing"
    assert cythonize_calls, "Expected Cythonize to be invoked for build_ext"
    assert cythonize_calls[0][1] is True, "Expected quiet=True when --quiet is passed"
    assert setup_calls and setup_calls[0]["name"] == "demo_worker"


def test_build_main_bdist_egg_unpacks_and_cleans_links(tmp_path, monkeypatch):
    app_dir = tmp_path / "demo_project"
    app_dir.mkdir(parents=True, exist_ok=True)
    worker_home = tmp_path / "home"
    out_dir = worker_home / "demo_project"
    dist_dir = out_dir / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)

    egg_path = dist_dir / "demo_worker-0.1.0.egg"
    with ZipFile(egg_path, "w") as zf:
        zf.writestr("demo_worker/__init__.py", "")

    class DummyAgiEnv:
        logger = _DummyLogger()
        _is_managed_pc = False

        @staticmethod
        def create_symlink(src, dest):
            os.symlink(src, dest)

        @staticmethod
        def create_junction_windows(_src, _dest):
            return None

        init_args = None

        def __init__(self, *, apps_path=None, active_app, verbose):
            DummyAgiEnv.init_args = {
                "apps_path": apps_path,
                "active_app": active_app,
                "verbose": verbose,
            }
            self.home_abs = str(worker_home)
            self.worker_path = "workers/demo_worker.py"
            self.pre_install = None
            self.verbose = verbose
            self.pyvers_worker = "3.13"
            self.is_worker_env = False
            self.active_app = app_dir
            self.target_worker = "demo_worker"
            self.agi_node = tmp_path / "agi_node"
            self.agi_env = tmp_path / "agi_env"
            self.app_src = app_dir

    monkeypatch.setattr(build_mod, "AgiEnv", DummyAgiEnv)
    monkeypatch.setattr(build_mod, "find_packages", lambda where="src": ["demo_worker"])
    monkeypatch.setattr(build_mod, "setup", lambda **_kwargs: None)

    links_created = [tmp_path / "src" / "demo_worker" / "module_link"]
    links_created[0].parent.mkdir(parents=True, exist_ok=True)
    links_created[0].write_text("x", encoding="utf-8")
    monkeypatch.setattr(build_mod, "create_symlink_for_module", lambda *_args, **_kwargs: links_created)

    cleanup_calls = []
    monkeypatch.setattr(build_mod, "cleanup_links", lambda links: cleanup_calls.append(list(links)))
    os_calls = []
    monkeypatch.setattr(build_mod.os, "system", lambda cmd: os_calls.append(cmd) or 0)

    build_mod.main(
        [
            "--app-path",
            str(app_dir),
            "bdist_egg",
            "-d",
            str(out_dir),
            "--packages",
            "agi_env.tools",
        ]
    )

    assert DummyAgiEnv.init_args is not None
    assert DummyAgiEnv.init_args["apps_path"] is None
    assert Path(DummyAgiEnv.init_args["active_app"]) == app_dir
    extracted = out_dir / "src" / "demo_worker" / "__init__.py"
    assert extracted.exists()
    assert os_calls and "remove_decorators" in os_calls[0]
    assert cleanup_calls and cleanup_calls[0] == links_created
