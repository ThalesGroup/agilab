from pathlib import Path
from types import SimpleNamespace

from agi_node.agi_dispatcher import post_install as post_mod


def test_resolve_post_install_app_arg_keeps_absolute_path(tmp_path):
    absolute = tmp_path / "apps" / "demo_project"

    resolved = post_mod._resolve_post_install_app_arg(
        absolute,
        home_path_fn=lambda: tmp_path / "home",
    )

    assert resolved == absolute


def test_resolve_post_install_app_arg_places_relative_under_home_wenv(tmp_path):
    home = tmp_path / "home"

    resolved = post_mod._resolve_post_install_app_arg(
        "demo_project",
        home_path_fn=lambda: home,
    )

    assert resolved == home / "wenv" / "demo_project"


def test_prepare_post_install_context_uses_env_target_share_and_existing_archive(tmp_path):
    app_arg = tmp_path / "demo_project"
    dataset_archive = tmp_path / "dataset.7z"
    dataset_archive.write_text("x", encoding="utf-8")
    build_calls = []

    env = SimpleNamespace(
        share_target_name="demo",
        resolve_share_path=lambda target: tmp_path / "share" / target,
    )

    result = post_mod._prepare_post_install_context(
        app_arg,
        build_env_fn=lambda arg: build_calls.append(arg) or env,
        dataset_archive_candidates_fn=lambda _env: [tmp_path / "missing.7z", dataset_archive],
    )

    assert build_calls == [app_arg]
    assert result == (env, "demo", tmp_path / "share" / "demo", dataset_archive)


def test_prepare_post_install_context_returns_none_when_no_archive_exists(tmp_path):
    env = SimpleNamespace(
        share_target_name="demo",
        resolve_share_path=lambda target: tmp_path / "share" / target,
    )

    _, target_name, dest_arg, dataset_archive = post_mod._prepare_post_install_context(
        tmp_path / "demo_project",
        build_env_fn=lambda _arg: env,
        dataset_archive_candidates_fn=lambda _env: [tmp_path / "missing.7z"],
    )

    assert target_name == "demo"
    assert dest_arg == tmp_path / "share" / "demo"
    assert dataset_archive is None


def test_execute_post_install_reports_missing_archive_and_returns_zero(tmp_path):
    lines = []
    env = SimpleNamespace(dataset_archive=tmp_path / "missing.7z")

    result = post_mod._execute_post_install(
        env=env,
        target_name="demo",
        dest_arg=tmp_path / "share" / "demo",
        dataset_archive=None,
        print_fn=lines.append,
    )

    assert result == 0
    assert lines == [
        f"[post_install] dataset archive not found for 'demo'. Looked under {tmp_path / 'missing.7z'} and packaged apps."
    ]


def test_execute_post_install_unzips_and_delegates_optional_seed(tmp_path):
    lines = []
    unzip_calls = []
    seed_calls = []
    dataset_archive = tmp_path / "dataset.7z"
    dataset_archive.write_text("x", encoding="utf-8")
    env = SimpleNamespace(unzip_data=lambda archive, dest: unzip_calls.append((archive, dest)))

    result = post_mod._execute_post_install(
        env=env,
        target_name="demo",
        dest_arg=tmp_path / "share" / "demo",
        dataset_archive=dataset_archive,
        seed_optional_dataset_fn=lambda **kwargs: seed_calls.append(kwargs) or 7,
        print_fn=lines.append,
    )

    assert result == 7
    assert unzip_calls == [(dataset_archive, tmp_path / "share" / "demo")]
    assert seed_calls == [
        {
            "env": env,
            "dataset_archive": dataset_archive,
            "dest_arg": tmp_path / "share" / "demo",
        }
    ]
    assert lines == [
        f"[post_install] dataset archive: {dataset_archive}",
        f"[post_install] destination: {tmp_path / 'share' / 'demo'}",
    ]


def test_execute_post_install_handles_optional_runtime_seed_failure(tmp_path):
    lines = []
    dataset_archive = tmp_path / "dataset.7z"
    dataset_archive.write_text("x", encoding="utf-8")
    env = SimpleNamespace(unzip_data=lambda *_args: None)

    result = post_mod._execute_post_install(
        env=env,
        target_name="demo",
        dest_arg=tmp_path / "share" / "demo",
        dataset_archive=dataset_archive,
        seed_optional_dataset_fn=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("agi_share_path is not configured")),
        is_optional_dataset_seeding_error_fn=lambda exc: "agi_share_path is not configured" in str(exc),
        print_fn=lines.append,
    )

    assert result == 0
    assert lines[-1] == "[post_install] optional dataset seeding skipped: agi_share_path is not configured"


def test_resolve_preferred_sat_dataset_prefers_packaged_dataset(tmp_path):
    share_root = tmp_path / "share-root"
    preferred = share_root / "sat_trajectory" / "dataset" / "Trajectory"
    fallback = share_root / "sat_trajectory" / "dataframe" / "Trajectory"
    preferred.mkdir(parents=True, exist_ok=True)
    fallback.mkdir(parents=True, exist_ok=True)
    for folder in (preferred, fallback):
        (folder / "a.csv").write_text("1", encoding="utf-8")
        (folder / "b.csv").write_text("2", encoding="utf-8")

    sat_trajectory_root, preferred_candidate = post_mod._resolve_preferred_sat_dataset(
        SimpleNamespace(share_root_path=lambda: share_root),
    )

    assert sat_trajectory_root == (share_root / "sat_trajectory").resolve(strict=False)
    assert preferred_candidate == preferred


def test_resolve_preferred_sat_dataset_logs_share_root_failure(tmp_path):
    lines = []

    sat_trajectory_root, preferred_candidate = post_mod._resolve_preferred_sat_dataset(
        SimpleNamespace(
            share_root_path=lambda: (_ for _ in ()).throw(RuntimeError("agi_share_path is not configured"))
        ),
        print_fn=lines.append,
    )

    assert sat_trajectory_root is None
    assert preferred_candidate is None
    assert lines == [
        "[post_install] optional dataset seeding shared-root lookup skipped: agi_share_path is not configured"
    ]


def test_apply_preferred_sat_dataset_relinks_existing_sat_trajectory_symlink(tmp_path):
    lines = []
    sat_trajectory_root = tmp_path / "shared-root" / "sat_trajectory"
    preferred = sat_trajectory_root / "dataset" / "Trajectory"
    current = sat_trajectory_root / "dataframe" / "Trajectory"
    preferred.mkdir(parents=True, exist_ok=True)
    current.mkdir(parents=True, exist_ok=True)
    for folder in (preferred, current):
        (folder / "a.csv").write_text("1", encoding="utf-8")
        (folder / "b.csv").write_text("2", encoding="utf-8")

    sat_folder = tmp_path / "dataset" / "sat"
    sat_folder.parent.mkdir(parents=True, exist_ok=True)
    sat_folder.symlink_to(current, target_is_directory=True)

    result = post_mod._apply_preferred_sat_dataset(
        sat_folder=sat_folder,
        preferred_candidate=preferred,
        sat_trajectory_root=sat_trajectory_root,
        preserve_existing=False,
        print_fn=lines.append,
    )

    assert result == 0
    assert sat_folder.resolve(strict=False) == preferred.resolve(strict=False)
    assert lines == [f"[post_install] relinked {sat_folder} -> {preferred}"]


def test_apply_preferred_sat_dataset_deduplicates_duplicate_folder(tmp_path):
    lines = []
    sat_trajectory_root = tmp_path / "shared-root" / "sat_trajectory"
    preferred = sat_trajectory_root / "dataset" / "Trajectory"
    preferred.mkdir(parents=True, exist_ok=True)
    (preferred / "a.csv").write_text("1", encoding="utf-8")
    (preferred / "b.csv").write_text("2", encoding="utf-8")

    sat_folder = tmp_path / "dataset" / "sat"
    sat_folder.mkdir(parents=True, exist_ok=True)
    (sat_folder / "a.csv").write_text("1", encoding="utf-8")
    (sat_folder / "b.csv").write_text("2", encoding="utf-8")

    result = post_mod._apply_preferred_sat_dataset(
        sat_folder=sat_folder,
        preferred_candidate=preferred,
        sat_trajectory_root=sat_trajectory_root,
        preserve_existing=False,
        print_fn=lines.append,
    )

    assert result == 0
    assert sat_folder.resolve(strict=False) == preferred.resolve(strict=False)
    assert lines == [f"[post_install] deduplicated {sat_folder} -> {preferred}"]


def test_apply_preferred_sat_dataset_preserves_existing_samples_when_requested(tmp_path):
    preferred = tmp_path / "shared-root" / "sat_trajectory" / "dataset" / "Trajectory"
    preferred.mkdir(parents=True, exist_ok=True)
    (preferred / "a.csv").write_text("1", encoding="utf-8")
    (preferred / "b.csv").write_text("2", encoding="utf-8")

    sat_folder = tmp_path / "dataset" / "sat"
    sat_folder.mkdir(parents=True, exist_ok=True)
    (sat_folder / "existing-a.csv").write_text("1", encoding="utf-8")
    (sat_folder / "existing-b.csv").write_text("2", encoding="utf-8")

    result = post_mod._apply_preferred_sat_dataset(
        sat_folder=sat_folder,
        preferred_candidate=preferred,
        sat_trajectory_root=preferred.parents[2],
        preserve_existing=True,
    )

    assert result == 0
    assert sat_folder.is_dir()
    assert sat_folder.is_symlink() is False
    assert (sat_folder / "existing-a.csv").exists()


def test_apply_trajectory_sat_dataset_extracts_archive_and_links_sat_folder(tmp_path, monkeypatch):
    lines = []
    dataset_archive = tmp_path / "dataset.7z"
    trajectory_archive = tmp_path / "Trajectory.7z"
    dataset_archive.write_text("x", encoding="utf-8")
    trajectory_archive.write_text("x", encoding="utf-8")
    dataset_root = tmp_path / "dataset"
    sat_folder = dataset_root / "sat"
    extracted = {}

    def _fake_extract(archive, dest):
        extracted["archive"] = archive
        extracted["dest"] = dest
        trajectory_folder = dest / "Trajectory"
        trajectory_folder.mkdir(parents=True, exist_ok=True)
        (trajectory_folder / "a.csv").write_text("1", encoding="utf-8")
        (trajectory_folder / "b.csv").write_text("2", encoding="utf-8")

    monkeypatch.setattr(post_mod, "_extract_archive", _fake_extract)

    result = post_mod._apply_trajectory_sat_dataset(
        dataset_archive=dataset_archive,
        dataset_root=dataset_root,
        sat_folder=sat_folder,
        print_fn=lines.append,
    )

    assert result == 0
    assert extracted == {"archive": trajectory_archive, "dest": dataset_root}
    assert sat_folder.resolve(strict=False) == (dataset_root / "Trajectory").resolve(strict=False)
    assert lines == [
        f"[post_install] extracting optional trajectories: {trajectory_archive}",
        f"[post_install] linked {sat_folder} -> {dataset_root / 'Trajectory'}",
    ]


def test_apply_trajectory_sat_dataset_copies_when_linking_fails(tmp_path, monkeypatch):
    lines = []
    dataset_archive = tmp_path / "dataset.7z"
    dataset_archive.write_text("x", encoding="utf-8")
    dataset_root = tmp_path / "dataset"
    trajectory_folder = dataset_root / "Trajectory"
    trajectory_folder.mkdir(parents=True, exist_ok=True)
    (trajectory_folder / "a.csv").write_text("1", encoding="utf-8")
    (trajectory_folder / "b.csv").write_text("2", encoding="utf-8")
    sat_folder = dataset_root / "sat"

    monkeypatch.setattr(post_mod, "_try_link_dir", lambda *_args, **_kwargs: False)

    result = post_mod._apply_trajectory_sat_dataset(
        dataset_archive=dataset_archive,
        dataset_root=dataset_root,
        sat_folder=sat_folder,
        print_fn=lines.append,
    )

    assert result == 0
    assert (sat_folder / "a.csv").exists()
    assert (sat_folder / "b.csv").exists()
    assert lines == [f"[post_install] copied 2 trajectory file(s) into {sat_folder}"]


def test_apply_trajectory_sat_dataset_returns_zero_when_no_samples_available(tmp_path):
    dataset_archive = tmp_path / "dataset.7z"
    dataset_archive.write_text("x", encoding="utf-8")
    dataset_root = tmp_path / "dataset"
    sat_folder = dataset_root / "sat"

    result = post_mod._apply_trajectory_sat_dataset(
        dataset_archive=dataset_archive,
        dataset_root=dataset_root,
        sat_folder=sat_folder,
    )

    assert result == 0
    assert not sat_folder.exists()
