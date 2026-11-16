"""Archive extraction must share the public workflow path resolver's trust root."""

from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import py7zr
import pytest

from agi_env import AgiEnv
import agi_env.agi_env as agi_env_module
from agi_env import data_archive_support


@pytest.fixture
def archive_context(tmp_path):
    legacy_root = tmp_path / "legacy-localshare"
    workflow_root = tmp_path / "synthetic-backing" / "workflow-session"
    legacy_root.mkdir()
    payload = tmp_path / "source-payload.txt"
    payload.write_text("new dataset payload\n", encoding="utf-8")
    archive = tmp_path / "workflow-root-dataset.7z"
    with py7zr.SevenZipFile(archive, "w") as handle:
        handle.write(payload, arcname="dataset/payload.txt")

    env = object.__new__(AgiEnv)
    env._share_root_cache = None
    env.agi_share_path = str(legacy_root)
    env.agi_share_path_abs = legacy_root
    env.AGILAB_WORKFLOW_DATA_ROOT = str(workflow_root)
    env.agi_workflow_data_root = None
    env.envars = {}
    env.share_target_name = "demo"
    env.app_data_rel = legacy_root / env.share_target_name
    env.home_abs = Path.home()
    env.user = Path.home().name
    env.is_worker_env = False
    env.verbose = 0
    env.logger = mock.Mock()
    return SimpleNamespace(
        env=env,
        archive=archive,
        legacy_root=legacy_root,
        workflow_root=workflow_root,
        payload=payload.read_text(encoding="utf-8"),
    )


def _live_marker(context):
    dataset = context.env.resolve_share_path("demo") / "dataset"
    dataset.mkdir(parents=True)
    marker = dataset / "old.marker"
    marker.write_text("keep", encoding="utf-8")
    return marker


def _assert_preserved(context, marker):
    assert marker.read_text(encoding="utf-8") == "keep"
    assert not (marker.parent / "payload.txt").exists()
    assert not any(marker.parent.parent.glob(".agilab-dataset-refresh-*"))


@pytest.mark.parametrize("scoped", [False, True], ids=["legacy-default", "workflow"])
@pytest.mark.parametrize("destination", ["absolute", "relative", "default"])
def test_unzip_data_extracts_real_archive_under_active_root(
    archive_context, scoped, destination
):
    context = archive_context
    env = context.env
    if not scoped:
        env.AGILAB_WORKFLOW_DATA_ROOT = None
    active_root = context.workflow_root if scoped else context.legacy_root
    sentinel = context.legacy_root / "unrelated.marker"
    sentinel.write_text("preserve legacy share", encoding="utf-8")
    dest = env.resolve_share_path("demo")
    assert dest == active_root / "demo"
    argument = {"absolute": dest, "relative": "demo", "default": None}[destination]

    env.unzip_data(context.archive, argument)

    dataset = active_root / "demo" / "dataset"
    assert (dataset / "payload.txt").read_text(encoding="utf-8") == context.payload
    assert (dataset / ".agilab_dataset_stamp").read_text(encoding="utf-8") == str(
        context.archive
    )
    assert sentinel.read_text(encoding="utf-8") == "preserve legacy share"
    if scoped:
        assert not (context.legacy_root / "demo").exists()
    assert not any(dest.glob(".agilab-dataset-refresh-*"))


@pytest.mark.parametrize(
    "escape", ["legacy-share", "absolute-sibling", "parent-traversal"]
)
def test_workflow_archive_rejects_destination_escape_before_mutation(
    archive_context, escape
):
    context = archive_context
    marker = _live_marker(context)
    legacy_marker = context.legacy_root / "keep.marker"
    legacy_marker.write_text("legacy", encoding="utf-8")
    destination = {
        "legacy-share": context.legacy_root / "demo",
        "absolute-sibling": context.workflow_root.parent / "outside",
        "parent-traversal": "../outside",
    }[escape]

    with pytest.raises(ValueError, match="share root"):
        context.env.unzip_data(context.archive, destination, force_extract=True)

    _assert_preserved(context, marker)
    assert legacy_marker.read_text(encoding="utf-8") == "legacy"
    assert not (context.legacy_root / "demo").exists()
    assert not (context.workflow_root.parent / "outside").exists()


def test_workflow_archive_rejects_symlink_escape_before_mutation(archive_context):
    context = archive_context
    marker = _live_marker(context)
    outside = context.workflow_root.parent / "outside"
    outside.mkdir()
    (context.workflow_root / "linked").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="share root"):
        context.env.unzip_data(context.archive, "linked/demo", force_extract=True)

    _assert_preserved(context, marker)
    assert not any(outside.iterdir())


def test_workflow_archive_refuses_dataset_alias_of_active_root(archive_context):
    context = archive_context
    dest = context.env.resolve_share_path("demo")
    dest.mkdir(parents=True)
    (dest / "dataset").symlink_to(context.workflow_root, target_is_directory=True)
    sentinel = context.workflow_root / "keep.marker"
    sentinel.write_text("keep", encoding="utf-8")

    with pytest.raises(ValueError, match="Dataset reset target"):
        context.env.unzip_data(context.archive, dest, force_extract=True)

    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert (dest / "dataset").is_symlink()
    assert not any(dest.glob(".agilab-dataset-refresh-*"))


@pytest.mark.parametrize("member", ["../escaped.txt", "dataset/../../escaped.txt"])
def test_workflow_archive_member_traversal_preserves_live_dataset(
    archive_context, monkeypatch, member
):
    context = archive_context
    marker = _live_marker(context)

    class UnsafeArchive:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def getnames(self):
            return [member]

        def extractall(self, path):
            pytest.fail("Unsafe archive must be refused before extraction")

    monkeypatch.setattr(agi_env_module.py7zr, "SevenZipFile", UnsafeArchive)
    with pytest.raises(RuntimeError, match="Unsafe archive member"):
        context.env.unzip_data(context.archive, "demo", force_extract=True)

    _assert_preserved(context, marker)


def test_workflow_archive_quota_preserves_live_dataset(archive_context, monkeypatch):
    context = archive_context
    marker = _live_marker(context)
    monkeypatch.setattr(
        data_archive_support,
        "validate_archive_extraction_quota",
        partial(
            data_archive_support.validate_archive_extraction_quota, max_member_bytes=1
        ),
    )

    with pytest.raises(ValueError, match="limit"):
        context.env.unzip_data(context.archive, "demo", force_extract=True)

    _assert_preserved(context, marker)


def test_workflow_archive_swap_failure_restores_live_dataset(
    archive_context, monkeypatch
):
    context = archive_context
    marker = _live_marker(context)
    original_replace = Path.replace

    def fail_staged_install(path, target):
        if path.name == "dataset" and path.parent.name.startswith(
            ".agilab-dataset-refresh-"
        ):
            raise OSError("injected dataset swap failure")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_staged_install)
    with pytest.raises(RuntimeError, match="Extraction failed"):
        context.env.unzip_data(context.archive, "demo", force_extract=True)

    _assert_preserved(context, marker)


def test_workflow_archive_preserves_explicit_owner_mismatch(archive_context):
    context = archive_context
    context.env.user = context.env.home_abs.name + "-other-owner"

    context.env.unzip_data(context.archive, "demo")

    assert context.env.resolve_share_path("demo").is_dir()
    assert not (context.workflow_root / "demo" / "dataset").exists()
    assert not (context.legacy_root / "demo").exists()


def test_packaged_dataset_seed_uses_active_workflow_despite_physical_data(
    archive_context,
):
    from agi_env.runtime import agi_env_instance_initialization as initialization

    context = archive_context
    env = context.env
    env.dataset_archive = context.archive
    legacy_dataset = context.legacy_root / env.share_target_name / "dataset"
    legacy_dataset.mkdir(parents=True)
    sentinel = legacy_dataset / "unrelated.csv"
    sentinel.write_text("preserve physical data\n", encoding="utf-8")

    initialization._extract_packaged_dataset_if_needed(env, env_cls=AgiEnv)

    active_dataset = env.resolve_share_path(env.share_target_name) / "dataset"
    assert (active_dataset / "payload.txt").read_text(encoding="utf-8") == context.payload
    assert (active_dataset / ".agilab_dataset_stamp").is_file()
    assert sentinel.read_text(encoding="utf-8") == "preserve physical data\n"


@pytest.mark.parametrize("stamp_present", [False, True])
def test_packaged_dataset_seed_preserves_current_active_workflow(
    archive_context, monkeypatch, stamp_present
):
    from agi_env.runtime import agi_env_instance_initialization as initialization

    context = archive_context
    env = context.env
    env.dataset_archive = context.archive
    marker = _live_marker(context)
    if stamp_present:
        import os

        stamp = marker.parent / ".agilab_dataset_stamp"
        stamp.write_text(str(context.archive), encoding="utf-8")
        archive_ns = context.archive.stat().st_mtime_ns
        os.utime(stamp, ns=(archive_ns + 1_000_000_000, archive_ns + 1_000_000_000))
    extract = mock.Mock(side_effect=AssertionError("current workflow must not refresh"))
    monkeypatch.setattr(env, "unzip_data", extract)

    initialization._extract_packaged_dataset_if_needed(env, env_cls=AgiEnv)

    extract.assert_not_called()
    assert marker.read_text(encoding="utf-8") == "keep"
    assert not (context.legacy_root / "demo").exists()
