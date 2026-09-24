"""Filesystem pollution and fallback contracts for worker data paths."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from agi_node.agi_dispatcher import base_worker_path_support as paths


def raises(error):
    def call(*args, **kwargs):
        raise error

    return call


def test_workflow_share_root_ignores_invalid_hint_then_resolves_relative_hint(tmp_path):
    env = SimpleNamespace(
        AGILAB_WORKFLOW_DATA_ROOT=object(),
        agi_workflow_data_root="sessions/run",
        home_abs=tmp_path,
        envars={},
    )
    assert paths.share_root_path(env) == tmp_path / "sessions/run"


@pytest.mark.parametrize("worker", [True, False])
def test_physical_root_survives_broken_method_and_invalid_absolute_hint(
    tmp_path, monkeypatch, worker
):
    monkeypatch.setattr(
        Path, "home", classmethod(lambda cls: tmp_path / "runtime-home")
    )
    env = SimpleNamespace(
        share_root_path=raises(OSError("offline")),
        agi_share_path_abs=object(),
        agi_share_path="cluster",
        home_abs=tmp_path / "manager-home",
        is_worker_env=worker,
    )
    expected = tmp_path / ("runtime-home" if worker else "manager-home") / "cluster"
    assert paths.physical_share_root_path(env) == expected
    env.agi_share_path = object()
    assert paths.physical_share_root_path(env) is None


@pytest.mark.parametrize("exception", [OSError, TypeError, ValueError])
def test_normalization_fallback_preserves_original_path(tmp_path, exception):
    assert (
        paths.normalized_path(
            tmp_path / "data", normalize_path_fn=raises(exception("bad config"))
        )
        == tmp_path / "data"
    )


def test_invalid_share_alias_fields_do_not_hide_valid_hint(tmp_path):
    env = SimpleNamespace(
        AGILAB_SHARE_HINT="group/custom",
        AGILAB_SHARE_REL=object(),
        agi_share_path=object(),
    )
    assert {"group", "custom", "data", "clustershare", "datashare"}.issubset(
        paths.collect_share_aliases(env, tmp_path / "share")
    )


def test_prefix_inventory_ignores_invalid_fields_and_deduplicates(tmp_path):
    env = SimpleNamespace(
        agi_share_path=object(),
        AGILAB_SHARE_REL="cluster/team",
        agi_share_path_abs=tmp_path / "cluster/team",
        home_abs=tmp_path,
    )
    assert paths._relative_share_prefixes(
        env, tmp_path / "cluster/team", home_factory=lambda: tmp_path
    ) == [Path("cluster/team")]
    assert (
        paths._resolve_relative_data_path(
            Path("team/data"),
            tmp_path / "cluster/team",
            env,
            home_factory=lambda: tmp_path,
        )
        == tmp_path / "cluster/team/data"
    )


def test_path_existence_errors_are_conservative(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "exists", raises(PermissionError("unreadable")))
    assert paths._path_exists(tmp_path) is False


@pytest.mark.parametrize("failure", ["parent-stat", "samefile"])
def test_containment_does_not_authorize_unprovable_filesystem_alias(
    tmp_path, monkeypatch, failure
):
    root = tmp_path / "trusted"
    outside = tmp_path / "other"
    root.mkdir()
    outside.mkdir()
    original_exists = Path.exists
    if failure == "parent-stat":
        monkeypatch.setattr(
            Path,
            "exists",
            lambda path: (_ for _ in ()).throw(PermissionError())
            if path == root
            else original_exists(path),
        )
    else:
        monkeypatch.setattr(Path, "samefile", raises(OSError("alias unavailable")))
    assert paths._path_is_relative_to(outside / "result", root) is False
    with pytest.raises(ValueError, match="is not inside"):
        paths._relative_path_under(outside / "result", root)


def test_resolution_fallback_normalizes_dot_segments_when_resolve_fails(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(Path, "resolve", raises(OSError("unavailable")))
    assert paths._safe_resolved_path(tmp_path / "a" / ".." / "b") == tmp_path / "b"


def test_share_output_rejects_missing_path_or_resolver():
    with pytest.raises(ValueError, match="must be provided"):
        paths.resolve_share_output_path(None, None)
    with pytest.raises(ValueError, match="canonical resolve_share_path"):
        paths.resolve_share_output_path(None, "result")


def test_generated_artifact_symlink_cannot_escape_output_root(tmp_path):
    source, output, outside = [
        tmp_path / name for name in ("source", "output", "outside")
    ]
    for directory in (source, output, outside):
        directory.mkdir()
    (output / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="escapes data_out"):
        paths.resolve_generated_artifact_path(source, output, "escape/result")
    (output / "read-only").symlink_to(source, target_is_directory=True)
    with pytest.raises(ValueError):
        paths.resolve_generated_artifact_path(source, output, "read-only/result")
    with pytest.raises(ValueError, match="must be provided"):
        paths.resolve_generated_artifact_path(source, output, None)


@pytest.mark.parametrize("input_form", ["relative", "absolute", "dot"])
def test_generated_artifact_rejects_overlapping_read_only_roots(tmp_path, input_form):
    source = tmp_path / "source"
    output = source / "generated"
    value = {"relative": "result", "absolute": source / "result", "dot": "."}[
        input_form
    ]
    with pytest.raises(ValueError, match="read-only"):
        paths.resolve_generated_artifact_path(source, output, value)


def test_artifact_fallback_uses_env_home_when_share_method_fails(tmp_path):
    env = SimpleNamespace(
        home_abs=tmp_path / "operator",
        share_root_path=raises(ValueError("invalid config")),
    )
    result = paths.resolve_artifact_dir(
        env, ".", target="", home_factory=lambda: tmp_path / "polluted"
    )
    assert result == tmp_path / "operator/export"


def test_permission_probe_failure_removes_only_its_own_probe(tmp_path, monkeypatch):
    existing = tmp_path / "user-file"
    existing.write_text("preserve")
    original_touch = Path.touch
    probes = []

    def touch(path, *args, **kwargs):
        if path.name.startswith(".agi_perm_"):
            probes.append(path)
            original_touch(path, *args, **kwargs)
            raise OSError("disk full")
        return original_touch(path, *args, **kwargs)

    monkeypatch.setattr(Path, "touch", touch)
    assert paths.can_create_path(tmp_path / "result.csv") is False
    assert probes and not probes[0].exists()
    assert existing.read_text() == "preserve"


def test_candidate_roots_keep_normalized_path_on_resolve_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "resolve", raises(OSError("mount offline")))
    root = tmp_path / "dataset"
    assert paths.candidate_named_dataset_roots(
        None,
        root,
        namespace=None,
        normalized_path_fn=Path,
        share_root_path_fn=lambda _: None,
    ) == [root]
