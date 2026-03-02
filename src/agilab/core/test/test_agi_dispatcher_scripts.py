import os
from argparse import Namespace
from pathlib import Path

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
