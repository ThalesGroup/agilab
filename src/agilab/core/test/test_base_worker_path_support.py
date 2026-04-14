from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from agi_node.agi_dispatcher import base_worker_path_support as path_support


def test_base_worker_path_support_normalized_and_share_root(monkeypatch, tmp_path):
    assert path_support.normalized_path(
        "~/demo",
        normalize_path_fn=lambda _path: (_ for _ in ()).throw(RuntimeError("boom")),
    ) == Path("~/demo").expanduser()

    env = SimpleNamespace(
        share_root_path=lambda: (_ for _ in ()).throw(RuntimeError("no share")),
        agi_share_path_abs=None,
        agi_share_path=Path("clustershare"),
        home_abs=tmp_path,
    )
    assert path_support.share_root_path(env) == tmp_path / "clustershare"


def test_base_worker_path_support_data_dir_aliases_and_home_remap(monkeypatch, tmp_path):
    class _BrokenPath:
        def __fspath__(self):
            raise RuntimeError("boom")

    env = SimpleNamespace(
        AGILAB_SHARE_HINT=Path("clustershare/link_sim"),
        AGILAB_SHARE_REL=_BrokenPath(),
        agi_share_path=_BrokenPath(),
        share_root_path=lambda: tmp_path / "share",
        agi_share_path_abs=tmp_path / "share",
        home_abs=tmp_path / "home",
        _is_managed_pc=False,
    )
    (tmp_path / "share").mkdir()

    aliases = path_support.collect_share_aliases(env, tmp_path / "share")
    assert {"share", "clustershare", "data", "datashare", "link_sim"} <= aliases

    fallback = path_support.resolve_data_dir(
        env,
        Path("dataset") / "inputs",
        share_root_path_fn=lambda current_env: path_support.share_root_path(current_env),
        remap_managed_pc_path_fn=lambda value: Path(value),
        normalized_path_fn=lambda value: Path(value),
    )
    assert fallback == (tmp_path / "share" / "dataset" / "inputs").resolve(strict=False)

    home_path = Path("/Users/demo/data/file.csv")
    assert path_support.relative_to_user_home(home_path) == Path("data/file.csv")
    assert path_support.relative_to_user_home(Path("/tmp/data/file.csv")) is None
    assert path_support.remap_user_home(home_path, username="other") == Path("/Users/other/data/file.csv")
    assert path_support.remap_user_home(Path("/tmp/data/file.csv"), username="other") is None
    assert path_support.strip_share_prefix(Path("clustershare/demo/file.csv"), {"clustershare"}) == Path("demo/file.csv")


def test_base_worker_path_support_candidate_roots_and_resolve_input_folder(tmp_path):
    share_root = tmp_path / "share"
    dataset_root = tmp_path / "runtime" / "dataset"
    flights_dir = share_root / "link_sim" / "dataset" / "flights"
    flights_dir.mkdir(parents=True)
    (flights_dir / "plane0.csv").write_text("plane_id,time_s\n0,0\n")
    (flights_dir / "plane1.csv").write_text("plane_id,time_s\n1,1\n")

    env = SimpleNamespace(
        share_root_path=lambda: share_root,
        agi_share_path_abs=share_root,
        agi_share_path=share_root,
        home_abs=Path.home(),
        AGILAB_SHARE_HINT=None,
        AGILAB_SHARE_REL=None,
        _is_managed_pc=False,
    )

    candidates = path_support.candidate_named_dataset_roots(
        env,
        dataset_root,
        namespace="link_sim",
        normalized_path_fn=lambda value: Path(value).expanduser(),
        share_root_path_fn=lambda current_env: path_support.share_root_path(current_env),
    )
    assert share_root / "link_sim" in candidates
    assert share_root / "link_sim" / "dataset" in candidates

    warnings: list[str] = []
    resolved = path_support.resolve_input_folder(
        env,
        dataset_root,
        "flight_trajectory/pipeline",
        descriptor="flight_trajectory",
        fallback_subdirs=("flights",),
        dataset_namespace="link_sim",
        min_files=2,
        required_label="plane trajectory files",
        normalized_path_fn=lambda value: Path(value).expanduser(),
        has_min_input_files_fn=lambda folder, min_files=1, patterns=None: path_support.has_min_input_files(
            folder,
            min_files=min_files,
            patterns=patterns,
        ),
        candidate_named_dataset_roots_fn=lambda current_env, root, namespace=None: path_support.candidate_named_dataset_roots(
            current_env,
            root,
            namespace=namespace,
            normalized_path_fn=lambda value: Path(value).expanduser(),
            share_root_path_fn=lambda support_env: path_support.share_root_path(support_env),
        ),
        warn_fn=lambda msg, *args: warnings.append(msg % args),
    )

    assert resolved == flights_dir
    assert warnings


def test_base_worker_path_support_iter_input_files_and_can_create_path(tmp_path, monkeypatch):
    folder = tmp_path / "dataset"
    folder.mkdir()
    (folder / "a.csv").write_text("x\n1\n", encoding="utf-8")
    (folder / "b.parquet").write_text("pq", encoding="utf-8")
    (folder / "._hidden.csv").write_text("hidden", encoding="utf-8")

    files = path_support.iter_input_files(folder)
    assert [path.name for path in files] == ["a.csv", "b.parquet"]
    assert path_support.has_min_input_files(folder, min_files=2, patterns=("*.csv", "*.parquet")) is True

    writable_target = tmp_path / "output" / "data.csv"
    assert path_support.can_create_path(writable_target) is True

    monkeypatch.setattr(
        Path,
        "touch",
        lambda self, *args, **kwargs: (_ for _ in ()).throw(PermissionError("denied")),
    )
    assert path_support.can_create_path(tmp_path / "blocked" / "data.csv") is False
