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
