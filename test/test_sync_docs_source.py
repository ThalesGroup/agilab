from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path("tools/sync_docs_source.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "sync_docs_source_test_module", MODULE_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_stamp_payload(module, target: Path, payload: dict[str, object]) -> Path:
    stamp_path = module.stamp_path_for_target(target)
    stamp_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return stamp_path


def _write_v1_stamp(module, source: Path, target: Path) -> Path:
    source_state = module._legacy_manifest_state(source)
    target_state = module._legacy_manifest_state(target)
    assert source_state == target_state
    return _write_stamp_payload(
        module,
        target,
        {
            "format_version": module.LEGACY_FULL_TREE_STAMP_FORMAT_VERSION,
            "managed_target": module.STAMP_MANAGED_TARGET,
            "source_hint": module.STAMP_SOURCE_HINT,
            "source_digest_sha256": source_state["digest_sha256"],
            "target_digest_sha256": target_state["digest_sha256"],
            "file_count": target_state["file_count"],
            "sync_tool": module.STAMP_SYNC_TOOL,
        },
    )


def _write_v2_stamp(module, source: Path, target: Path) -> Path:
    source_state = module._manifest_state(source)
    target_state = module._manifest_state(target)
    assert source_state == target_state
    return _write_stamp_payload(
        module,
        target,
        {
            "format_version": module.UNSAFE_PARTIAL_STAMP_FORMAT_VERSION,
            "managed_target": module.STAMP_MANAGED_TARGET,
            "public_owned_exclusions": sorted(module.PUBLIC_OWNED_EXCLUSIONS),
            "source_hint": module.STAMP_SOURCE_HINT,
            "source_status": "verified",
            "source_digest_sha256": source_state["digest_sha256"],
            "target_digest_sha256": target_state["digest_sha256"],
            "file_count": target_state["file_count"],
            "sync_tool": module.STAMP_SYNC_TOOL,
        },
    )


def _symlink_or_skip(link: Path, target: Path, *, target_is_directory: bool) -> None:
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")


def test_build_manifest_ignores_junk_files(tmp_path: Path) -> None:
    module = _load_module()
    source = tmp_path / "source"
    (source / "guide.rst").parent.mkdir(parents=True)
    (source / "guide.rst").write_text("hello\n", encoding="utf-8")
    (source / ".DS_Store").write_text("junk\n", encoding="utf-8")
    (source / "__pycache__" / "ignored.pyc").parent.mkdir(parents=True)
    (source / "__pycache__" / "ignored.pyc").write_bytes(b"x")

    manifest = module.build_manifest(source)

    assert manifest == {"guide.rst": source / "guide.rst"}


def test_configured_canonical_source_honors_relative_agilab_docs_source(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    repo_root = tmp_path / "public-repo"
    repo_root.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(module.DOCS_SOURCE_ENV, "canonical-docs")
    monkeypatch.setenv(module.DOCS_REPOSITORY_ENV, "ignored-docs-repository")

    configuration = module.canonical_source_configuration(repo_root)

    assert configuration.path == (repo_root / "canonical-docs").resolve()
    assert configuration.origin == f"env:{module.DOCS_SOURCE_ENV}"
    assert configuration.required is True


def test_configured_canonical_source_resolves_relative_docs_repository(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    repo_root = tmp_path / "public-repo"
    repo_root.mkdir()
    monkeypatch.delenv(module.DOCS_SOURCE_ENV, raising=False)
    monkeypatch.setenv(module.DOCS_REPOSITORY_ENV, "../canonical-repo")

    configuration = module.canonical_source_configuration(repo_root)

    assert (
        configuration.path
        == (repo_root / "../canonical-repo" / "docs" / "source").resolve()
    )
    assert configuration.origin == f"env:{module.DOCS_REPOSITORY_ENV}"
    assert configuration.required is True


def test_default_canonical_source_uses_primary_checkout_for_linked_worktree(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    projects = tmp_path / "projects"
    primary_checkout = projects / "agilab"
    linked_worktree = projects / "agilab-worktrees" / "task"
    primary_checkout.mkdir(parents=True)
    linked_worktree.mkdir(parents=True)
    monkeypatch.delenv(module.DOCS_SOURCE_ENV, raising=False)
    monkeypatch.delenv(module.DOCS_REPOSITORY_ENV, raising=False)
    monkeypatch.setattr(
        module,
        "_primary_git_checkout_root",
        lambda repo_root: primary_checkout if repo_root == linked_worktree else None,
    )

    configuration = module.canonical_source_configuration(linked_worktree)

    assert configuration.path == projects / "thales_agilab" / "docs" / "source"
    assert configuration.origin == "default"
    assert configuration.required is False


def test_build_manifest_excludes_only_public_owned_docs_artifacts(
    tmp_path: Path,
) -> None:
    module = _load_module()
    root = tmp_path / "source"
    managed = root / "data" / "managed.json"
    managed.parent.mkdir(parents=True)
    managed.write_text("managed\n", encoding="utf-8")
    for rel_path in module.PUBLIC_OWNED_EXCLUSIONS:
        path = root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("public-owned\n", encoding="utf-8")

    manifest = module.build_manifest(root)

    assert manifest == {"data/managed.json": managed}


def test_build_manifest_rejects_source_file_symlink(tmp_path: Path) -> None:
    module = _load_module()
    source = tmp_path / "source"
    source.mkdir()
    outside = tmp_path / "private.txt"
    outside.write_text("private\n", encoding="utf-8")
    _symlink_or_skip(
        source / "published.rst",
        outside,
        target_is_directory=False,
    )

    with pytest.raises(ValueError, match="symlinks or junctions"):
        module.build_manifest(source)


def test_build_manifest_rejects_nested_target_directory_symlink(tmp_path: Path) -> None:
    module = _load_module()
    target = tmp_path / "target"
    outside = tmp_path / "outside"
    target.mkdir()
    outside.mkdir()
    _symlink_or_skip(
        target / "nested",
        outside,
        target_is_directory=True,
    )

    with pytest.raises(ValueError, match="symlinks or junctions"):
        module.build_manifest(target)


def test_build_manifest_rejects_unicode_normalization_collision(tmp_path: Path) -> None:
    module = _load_module()
    source = tmp_path / "source"
    source.mkdir()
    composed = source / "café.rst"
    decomposed = source / "cafe\u0301.rst"
    composed.write_text("composed\n", encoding="utf-8")
    try:
        with decomposed.open("x", encoding="utf-8") as handle:
            handle.write("decomposed\n")
    except FileExistsError:
        pytest.skip("filesystem aliases NFC and NFD path spellings")
    if composed.samefile(decomposed):
        pytest.skip("filesystem aliases NFC and NFD path spellings")

    with pytest.raises(ValueError, match="colliding portable case/Unicode paths"):
        module.build_manifest(source)


def test_build_manifest_rejects_casefold_collision(tmp_path: Path) -> None:
    module = _load_module()
    source = tmp_path / "source"
    source.mkdir()
    upper = source / "Guide.rst"
    lower = source / "guide.rst"
    upper.write_text("upper\n", encoding="utf-8")
    try:
        with lower.open("x", encoding="utf-8") as handle:
            handle.write("lower\n")
    except FileExistsError:
        pytest.skip("filesystem aliases casefold-equivalent path spellings")
    if upper.samefile(lower):
        pytest.skip("filesystem aliases casefold-equivalent path spellings")

    with pytest.raises(ValueError, match="colliding portable case/Unicode paths"):
        module.build_manifest(source)


def test_case_only_cross_tree_drift_requires_manual_two_step_rename(
    tmp_path: Path,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "Guide.rst").write_text("same\n", encoding="utf-8")
    (target / "guide.rst").write_text("same\n", encoding="utf-8")

    before = (target / "guide.rst").read_bytes()
    with pytest.raises(ValueError, match="manual two-step rename"):
        module.make_sync_plan(source, target, delete_extra=True)

    assert (target / "guide.rst").read_bytes() == before
    assert os.listdir(target) == ["guide.rst"]


def test_case_variant_of_public_owned_name_is_classified_consistently(
    tmp_path: Path,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "Release-Proof.rst").write_text("managed\n", encoding="utf-8")
    (target / "Release-Proof.rst").write_text("managed\n", encoding="utf-8")

    stamp_path = module.write_mirror_stamp(source, target)
    payload = json.loads(stamp_path.read_text(encoding="utf-8"))

    assert payload["file_count"] == 1
    assert payload["public_owned_file_count"] == 0


def test_make_sync_plan_reports_create_update_and_delete(tmp_path: Path) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    (source / "same.rst").parent.mkdir(parents=True)
    (target / "same.rst").parent.mkdir(parents=True)
    (source / "same.rst").write_text("same\n", encoding="utf-8")
    (target / "same.rst").write_text("same\n", encoding="utf-8")
    (source / "new.rst").write_text("new\n", encoding="utf-8")
    (source / "changed.rst").write_text("source\n", encoding="utf-8")
    (target / "changed.rst").write_text("target\n", encoding="utf-8")
    (target / "extra.rst").write_text("extra\n", encoding="utf-8")

    plan = module.make_sync_plan(source, target, delete_extra=True)

    assert plan.created == ["new.rst"]
    assert plan.updated == ["changed.rst"]
    assert plan.deleted == ["extra.rst"]


def test_apply_sync_plan_copies_and_deletes(tmp_path: Path) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    (source / "nested" / "guide.rst").parent.mkdir(parents=True)
    (target / "stale.rst").parent.mkdir(parents=True)
    (source / "nested" / "guide.rst").write_text("guide\n", encoding="utf-8")
    (target / "nested" / "guide.rst").parent.mkdir(parents=True, exist_ok=True)
    (target / "nested" / "guide.rst").write_text("old\n", encoding="utf-8")
    (target / "stale.rst").write_text("stale\n", encoding="utf-8")

    plan = module.make_sync_plan(source, target, delete_extra=True)
    module.apply_sync_plan(source, target, plan)

    assert (target / "nested" / "guide.rst").read_text(encoding="utf-8") == "guide\n"
    assert not (target / "stale.rst").exists()


def test_apply_delete_preserves_public_owned_artifacts_and_manages_adjacent_data(
    tmp_path: Path,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    for rel_path in module.PUBLIC_OWNED_EXCLUSIONS:
        source_path = source / rel_path
        target_path = target / rel_path
        source_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text("canonical-copy\n", encoding="utf-8")
        target_path.write_text("public-generated\n", encoding="utf-8")
    (source / "data" / "managed.json").write_text("new\n", encoding="utf-8")
    (target / "data" / "managed.json").write_text("old\n", encoding="utf-8")
    (target / "data" / "stale.json").write_text("stale\n", encoding="utf-8")

    plan = module.make_sync_plan(source, target, delete_extra=True)
    module.apply_sync_plan(source, target, plan)

    assert plan.updated == ["data/managed.json"]
    assert plan.deleted == ["data/stale.json"]
    for rel_path in module.PUBLIC_OWNED_EXCLUSIONS:
        assert (target / rel_path).read_text(encoding="utf-8") == "public-generated\n"
    assert (target / "data" / "managed.json").read_text(encoding="utf-8") == "new\n"
    assert not (target / "data" / "stale.json").exists()


def test_public_owned_artifact_changes_do_not_change_managed_digest(
    tmp_path: Path,
) -> None:
    module = _load_module()
    target = tmp_path / "target"
    target.mkdir()
    (target / "guide.rst").write_text("guide\n", encoding="utf-8")
    before = module._manifest_state(target)
    for rel_path in module.PUBLIC_OWNED_EXCLUSIONS:
        path = target / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("generated version one\n", encoding="utf-8")
    after_create = module._manifest_state(target)
    for rel_path in module.PUBLIC_OWNED_EXCLUSIONS:
        (target / rel_path).write_text("generated version two\n", encoding="utf-8")

    assert after_create == before
    assert module._manifest_state(target) == before


def test_v3_stamp_tracks_public_owned_digest_independently(tmp_path: Path) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "guide.rst").write_text("guide\n", encoding="utf-8")
    (target / "guide.rst").write_text("guide\n", encoding="utf-8")
    release_proof = target / "data" / "release_proof.toml"
    release_proof.parent.mkdir(parents=True)
    release_proof.write_text("[release]\n", encoding="utf-8")

    stamp_path = module.write_mirror_stamp(source, target)
    payload = json.loads(stamp_path.read_text(encoding="utf-8"))

    assert payload["format_version"] == module.STAMP_FORMAT_VERSION == 3
    assert payload["file_count"] == 1
    assert payload["public_owned_file_count"] == 1
    assert (
        payload["target_digest_sha256"]
        == module._manifest_state(target)["digest_sha256"]
    )
    assert (
        payload["public_owned_digest_sha256"]
        == module._public_owned_state(target)["digest_sha256"]
    )

    release_proof.write_text("[release]\nversion = 2\n", encoding="utf-8")
    ok, message = module.verify_target_mirror_integrity(target)

    assert ok is False
    assert "public-owned digest" in message


def test_make_sync_plan_normalizes_unicode_relative_paths(tmp_path: Path) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()

    source_name = "TP Prompt Ingénierie.pptx"
    target_name = "TP Prompt Inge\u0301nierie.pptx"
    (source / source_name).write_text("same\n", encoding="utf-8")
    (target / target_name).write_text("same\n", encoding="utf-8")

    plan = module.make_sync_plan(source, target, delete_extra=True)

    assert not plan.has_changes()


def test_apply_updates_normalization_variant_using_manifest_path(
    tmp_path: Path,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    source_path = source / "Ingénierie.rst"
    target_path = target / "Inge\u0301nierie.rst"
    source_path.write_text("canonical\n", encoding="utf-8")
    target_path.write_text("stale\n", encoding="utf-8")

    plan = module.make_sync_plan(source, target, delete_extra=True)
    module.apply_sync_plan(source, target, plan)

    actual_target = next(target.iterdir())
    assert actual_target.read_text(encoding="utf-8") == "canonical\n"
    assert len(list(target.iterdir())) == 1


def test_apply_deletes_normalization_variant_using_manifest_path(
    tmp_path: Path,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (target / "Inge\u0301nierie.rst").write_text("stale\n", encoding="utf-8")

    plan = module.make_sync_plan(source, target, delete_extra=True)
    module.apply_sync_plan(source, target, plan)

    assert list(target.iterdir()) == []


def test_transactional_snapshot_preserves_canonical_path_spelling(
    tmp_path: Path,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    canonical_name = "Guide-Équipe.rst"
    (source / canonical_name).write_text("canonical\n", encoding="utf-8")

    plan = module.make_sync_plan(source, target, delete_extra=True)
    module.apply_sync_plan_transactionally(source, target, plan)

    names = [path.name for path in target.iterdir()]
    assert names == [canonical_name]


def test_main_check_and_apply_modes(tmp_path: Path, capsys) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "guide.rst").write_text("guide\n", encoding="utf-8")

    exit_code = module.main(
        ["--source", str(source), "--target", str(target), "--check"]
    )

    assert exit_code == 1
    assert "create: 1" in capsys.readouterr().out

    exit_code = module.main(
        ["--source", str(source), "--target", str(target), "--apply"]
    )

    assert exit_code == 0
    assert (target / "guide.rst").read_text(encoding="utf-8") == "guide\n"
    stamp = target.parent / module.STAMP_FILE_NAME
    assert stamp.exists()
    payload = json.loads(stamp.read_text(encoding="utf-8"))
    assert payload["file_count"] == 1
    assert payload["managed_target"] == module._logical_target_identity(target)
    assert payload["format_version"] == module.STAMP_FORMAT_VERSION == 3
    assert payload["source_status"] == "verified"
    assert payload["source_digest_sha256"] == payload["target_digest_sha256"]
    assert payload["public_owned_file_count"] == 0
    assert (
        payload["public_owned_digest_sha256"]
        == module._public_owned_state(target)["digest_sha256"]
    )
    assert payload["public_owned_exclusions"] == sorted(module.PUBLIC_OWNED_EXCLUSIONS)


def test_apply_without_delete_fails_before_mutating_target_or_stamp(
    tmp_path: Path,
    capsys,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "guide.rst").write_text("canonical\n", encoding="utf-8")
    (source / "new.rst").write_text("new\n", encoding="utf-8")
    (target / "guide.rst").write_text("stale\n", encoding="utf-8")
    (target / "removed.rst").write_text("extra\n", encoding="utf-8")
    stamp_path = module.write_target_only_mirror_stamp(target)
    stamp_before = stamp_path.read_bytes()

    exit_code = module.main(
        ["--source", str(source), "--target", str(target), "--apply"]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "No changes were applied" in captured.err
    assert "rerun with --apply --delete" in captured.err
    assert (target / "guide.rst").read_text(encoding="utf-8") == "stale\n"
    assert not (target / "new.rst").exists()
    assert (target / "removed.rst").read_text(encoding="utf-8") == "extra\n"
    assert stamp_path.read_bytes() == stamp_before


def test_transactional_apply_rolls_back_after_partial_copy_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "created.rst").write_text("created\n", encoding="utf-8")
    (source / "updated.rst").write_text("updated-new\n", encoding="utf-8")
    (target / "updated.rst").write_text("updated-old\n", encoding="utf-8")
    (target / "deleted.rst").write_text("deleted-old\n", encoding="utf-8")
    stamp_path = module.write_target_only_mirror_stamp(target)
    stamp_before = stamp_path.read_bytes()
    plan = module.make_sync_plan(source, target, delete_extra=True)
    assert plan.created == ["created.rst"]
    assert plan.updated == ["updated.rst"]
    assert plan.deleted == ["deleted.rst"]
    original_stage = module._stage_copy_at

    def fail_on_updated_stage(src, parent, **kwargs):
        if Path(src) == source / "updated.rst":
            raise OSError("injected copy failure")
        return original_stage(src, parent, **kwargs)

    monkeypatch.setattr(module, "_stage_copy_at", fail_on_updated_stage)

    with pytest.raises(OSError, match="injected copy failure"):
        module.apply_sync_plan_transactionally(source, target, plan)

    assert not (target / "created.rst").exists()
    assert (target / "updated.rst").read_text(encoding="utf-8") == "updated-old\n"
    assert (target / "deleted.rst").read_text(encoding="utf-8") == "deleted-old\n"
    assert stamp_path.read_bytes() == stamp_before


def test_transactional_apply_rolls_back_when_stamp_write_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "created.rst").write_text("created\n", encoding="utf-8")
    (source / "updated.rst").write_text("updated-new\n", encoding="utf-8")
    (target / "updated.rst").write_text("updated-old\n", encoding="utf-8")
    (target / "deleted.rst").write_text("deleted-old\n", encoding="utf-8")
    stamp_path = module.write_target_only_mirror_stamp(target)
    stamp_before = stamp_path.read_bytes()
    plan = module.make_sync_plan(source, target, delete_extra=True)

    def fail_stamp_write(
        _stamp_path: Path, _payload: dict[str, object], **_kwargs
    ) -> None:
        raise OSError("injected stamp failure")

    monkeypatch.setattr(module, "_write_stamp_payload", fail_stamp_write)

    with pytest.raises(OSError, match="injected stamp failure"):
        module.apply_sync_plan_transactionally(source, target, plan)

    assert not (target / "created.rst").exists()
    assert (target / "updated.rst").read_text(encoding="utf-8") == "updated-old\n"
    assert (target / "deleted.rst").read_text(encoding="utf-8") == "deleted-old\n"
    assert stamp_path.read_bytes() == stamp_before


def test_rollback_preserves_concurrent_in_place_change_to_created_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "created.rst").write_text("canonical\n", encoding="utf-8")
    stamp_path = module.write_target_only_mirror_stamp(target)
    stamp_before = stamp_path.read_bytes()
    destination = target / "created.rst"
    plan = module.make_sync_plan(source, target, delete_extra=True)

    def mutate_then_fail(
        _stamp_path: Path, _payload: dict[str, object], **_kwargs
    ) -> None:
        destination.write_text("concurrent\n", encoding="utf-8")
        raise OSError("injected stamp failure")

    monkeypatch.setattr(module, "_write_stamp_payload", mutate_then_fail)

    with pytest.raises(RuntimeError, match="rollback was incomplete"):
        module.apply_sync_plan_transactionally(source, target, plan)

    assert destination.read_text(encoding="utf-8") == "concurrent\n"
    assert stamp_path.read_bytes() == stamp_before


def test_transactional_apply_preserves_concurrent_created_symlink_target(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    source_file = source / "created.rst"
    source_file.write_text("canonical\n", encoding="utf-8")
    outside = tmp_path / "outside.rst"
    outside.write_text("outside-original\n", encoding="utf-8")
    destination = target / "created.rst"
    plan = module.make_sync_plan(source, target, delete_extra=True)
    original_stage = module._stage_copy_at
    injected = False

    def inject_symlink_after_staging(src, parent, **kwargs):
        nonlocal injected
        result = original_stage(src, parent, **kwargs)
        if not injected and Path(src) == source_file:
            injected = True
            _symlink_or_skip(destination, outside, target_is_directory=False)
        return result

    monkeypatch.setattr(module, "_stage_copy_at", inject_symlink_after_staging)

    with pytest.raises(ValueError, match="appeared after planning"):
        module.apply_sync_plan_transactionally(source, target, plan)

    assert destination.is_symlink()
    assert outside.read_text(encoding="utf-8") == "outside-original\n"


def test_transactional_apply_preserves_concurrent_created_regular_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    source_file = source / "created.rst"
    source_file.write_text("canonical\n", encoding="utf-8")
    destination = target / "created.rst"
    plan = module.make_sync_plan(source, target, delete_extra=True)
    original_stage = module._stage_copy_at
    injected = False

    def inject_regular_file_after_staging(src, parent, **kwargs):
        nonlocal injected
        result = original_stage(src, parent, **kwargs)
        if not injected and Path(src) == source_file:
            injected = True
            destination.write_text("concurrent\n", encoding="utf-8")
        return result

    monkeypatch.setattr(module, "_stage_copy_at", inject_regular_file_after_staging)

    with pytest.raises(ValueError, match="appeared after planning"):
        module.apply_sync_plan_transactionally(source, target, plan)

    assert destination.read_text(encoding="utf-8") == "concurrent\n"


@pytest.mark.parametrize("mode", ["create", "update"])
def test_staging_fingerprint_failure_happens_before_target_publication(
    tmp_path: Path,
    monkeypatch,
    mode: str,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    destination = target / "guide.rst"
    (source / "guide.rst").write_text("canonical\n", encoding="utf-8")
    expected = None
    if mode == "update":
        destination.write_text("original\n", encoding="utf-8")
        expected = "original\n"
    stamp_path = module.write_target_only_mirror_stamp(target)
    stamp_before = stamp_path.read_bytes()
    plan = module.make_sync_plan(source, target, delete_extra=True)
    original_fingerprint = module._regular_file_fingerprint_at

    def fail_staging_fingerprint(parent, name):
        if str(name).endswith(".sync"):
            raise OSError("injected staging fingerprint failure")
        return original_fingerprint(parent, name)

    monkeypatch.setattr(
        module,
        "_regular_file_fingerprint_at",
        fail_staging_fingerprint,
    )

    with pytest.raises(OSError, match="injected staging fingerprint failure"):
        module.apply_sync_plan_transactionally(source, target, plan)

    if expected is None:
        assert not destination.exists()
    else:
        assert destination.read_text(encoding="utf-8") == expected
    assert stamp_path.read_bytes() == stamp_before


def test_live_source_change_after_snapshot_rolls_back_target_and_stamp(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    live_file = source / "guide.rst"
    target_file = target / "guide.rst"
    live_file.write_text("captured\n", encoding="utf-8")
    target_file.write_text("target-before\n", encoding="utf-8")
    stamp_path = module.write_target_only_mirror_stamp(target)
    stamp_before = stamp_path.read_bytes()
    original_apply = module._apply_sync_plan_safely

    def apply_then_mutate_live_source(*args, **kwargs):
        original_apply(*args, **kwargs)
        live_file.write_text("changed-after-snapshot\n", encoding="utf-8")

    monkeypatch.setattr(
        module,
        "_apply_sync_plan_safely",
        apply_then_mutate_live_source,
    )

    exit_code = module.main(
        [
            "--source",
            str(source),
            "--target",
            str(target),
            "--apply",
            "--delete",
            "--quiet",
        ]
    )

    assert exit_code == 1
    assert "changed after its sync snapshot" in capsys.readouterr().err
    assert target_file.read_text(encoding="utf-8") == "target-before\n"
    assert stamp_path.read_bytes() == stamp_before


def test_delete_uses_pinned_parent_when_path_is_swapped_to_symlink(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    if not module._supports_pinned_directory_operations():
        pytest.skip("pinned directory descriptors are unavailable")
    source = tmp_path / "source"
    target = tmp_path / "target"
    outside = tmp_path / "outside"
    source.mkdir()
    target.mkdir()
    outside.mkdir()
    nested = target / "nested"
    nested.mkdir()
    destination = nested / "guide.rst"
    destination.write_text("mirror-original\n", encoding="utf-8")
    outside_file = outside / "guide.rst"
    outside_file.write_text("outside-original\n", encoding="utf-8")
    module.write_target_only_mirror_stamp(target)
    plan = module.make_sync_plan(source, target, delete_extra=True)
    saved_parent = tmp_path / "saved-parent"
    original_unlink = module._unlink_at
    swapped = False

    def swap_parent_then_unlink(parent, name, *, missing_ok=False, on_success=None):
        nonlocal swapped
        if not swapped and parent.destination == destination:
            swapped = True
            nested.rename(saved_parent)
            os.symlink(outside, nested, target_is_directory=True)
        return original_unlink(
            parent,
            name,
            missing_ok=missing_ok,
            on_success=on_success,
        )

    monkeypatch.setattr(module, "_unlink_at", swap_parent_then_unlink)

    with pytest.raises(RuntimeError, match="rollback was incomplete"):
        module.apply_sync_plan_transactionally(source, target, plan)

    assert swapped is True
    assert outside_file.read_text(encoding="utf-8") == "outside-original\n"
    assert nested.is_symlink()


def test_deleted_rollback_does_not_clobber_concurrent_recreation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    destination = target / "guide.rst"
    destination.write_text("before-transaction\n", encoding="utf-8")
    module.write_target_only_mirror_stamp(target)
    plan = module.make_sync_plan(source, target, delete_extra=True)
    original_link = module._link_no_replace_at
    recreated = False

    def recreate_then_link(parent, staged, destination_name, **kwargs):
        nonlocal recreated
        if not recreated:
            recreated = True
            parent.destination.write_text(
                "concurrent-recreation\n",
                encoding="utf-8",
            )
        return original_link(parent, staged, destination_name, **kwargs)

    def fail_stamp_write(
        _stamp_path: Path, _payload: dict[str, object], **_kwargs
    ) -> None:
        raise OSError("force rollback")

    monkeypatch.setattr(module, "_link_no_replace_at", recreate_then_link)
    monkeypatch.setattr(module, "_write_stamp_payload", fail_stamp_write)

    with pytest.raises(RuntimeError, match="rollback was incomplete"):
        module.apply_sync_plan_transactionally(source, target, plan)

    assert recreated is True
    assert destination.read_text(encoding="utf-8") == "concurrent-recreation\n"


def test_stamp_capture_rejects_target_mutation_between_state_reads(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "guide.rst").write_text("same\n", encoding="utf-8")
    target_file = target / "guide.rst"
    target_file.write_text("same\n", encoding="utf-8")
    original_states = module._target_evidence_states_at_boundary
    calls = 0

    def mutate_after_first_state(boundary):
        nonlocal calls
        result = original_states(boundary)
        calls += 1
        if calls == 1:
            target_file.write_text("changed\n", encoding="utf-8")
        return result

    monkeypatch.setattr(
        module,
        "_target_evidence_states_at_boundary",
        mutate_after_first_state,
    )

    with pytest.raises(ValueError, match="changed while evidence was captured"):
        module.write_mirror_stamp(source, target)

    assert not module.stamp_path_for_target(target).exists()


def test_target_only_stamp_restores_prior_stamp_on_late_target_mutation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    target = tmp_path / "target"
    target.mkdir()
    target_file = target / "guide.rst"
    target_file.write_text("before\n", encoding="utf-8")
    stamp_path = module.write_target_only_mirror_stamp(target)
    stamp_before = stamp_path.read_bytes()
    original_write = module._write_stamp_payload
    mutated = False

    def mutate_target_then_write(path, payload, **kwargs):
        nonlocal mutated
        if not mutated:
            mutated = True
            target_file.write_text("after\n", encoding="utf-8")
        original_write(path, payload, **kwargs)

    monkeypatch.setattr(module, "_write_stamp_payload", mutate_target_then_write)

    with pytest.raises(ValueError, match="published mirror stamp failed verification"):
        module.write_target_only_mirror_stamp(target)

    assert mutated is True
    assert stamp_path.read_bytes() == stamp_before


def test_stage_copy_exception_after_return_cleans_owned_staging_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "created.rst").write_text("canonical\n", encoding="utf-8")
    stamp_path = module.write_target_only_mirror_stamp(target)
    stamp_before = stamp_path.read_bytes()
    plan = module.make_sync_plan(source, target, delete_extra=True)
    original_stage = module._stage_copy_at
    injected = False

    def stage_then_raise(*args, **kwargs):
        nonlocal injected
        artifact = original_stage(*args, **kwargs)
        if not injected:
            injected = True
            raise OSError("injected exception after staging return")
        return artifact

    monkeypatch.setattr(module, "_stage_copy_at", stage_then_raise)

    with pytest.raises(OSError, match="after staging return"):
        module.apply_sync_plan_transactionally(source, target, plan)

    assert list(target.iterdir()) == []
    assert stamp_path.read_bytes() == stamp_before
    assert not list(tmp_path.rglob("*.sync"))


def test_create_publication_exception_after_link_rolls_back_exactly(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "created.rst").write_text("canonical\n", encoding="utf-8")
    stamp_path = module.write_target_only_mirror_stamp(target)
    stamp_before = stamp_path.read_bytes()
    plan = module.make_sync_plan(source, target, delete_extra=True)
    original_link = module._link_no_replace_at
    injected = False

    def link_then_raise(*args, **kwargs):
        nonlocal injected
        result = original_link(*args, **kwargs)
        if not injected:
            injected = True
            raise OSError("injected exception after link")
        return result

    monkeypatch.setattr(module, "_link_no_replace_at", link_then_raise)

    with pytest.raises(OSError, match="after link"):
        module.apply_sync_plan_transactionally(source, target, plan)

    assert not (target / "created.rst").exists()
    assert stamp_path.read_bytes() == stamp_before
    assert not list(tmp_path.rglob("*.sync"))


def test_update_publication_exception_after_replace_rolls_back_exactly(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "guide.rst").write_text("new\n", encoding="utf-8")
    (target / "guide.rst").write_text("old\n", encoding="utf-8")
    stamp_path = module.write_target_only_mirror_stamp(target)
    stamp_before = stamp_path.read_bytes()
    plan = module.make_sync_plan(source, target, delete_extra=True)
    original_replace = module._replace_at
    injected = False

    def replace_then_raise(*args, **kwargs):
        nonlocal injected
        result = original_replace(*args, **kwargs)
        if not injected:
            injected = True
            raise OSError("injected exception after replace")
        return result

    monkeypatch.setattr(module, "_replace_at", replace_then_raise)

    with pytest.raises(OSError, match="after replace"):
        module.apply_sync_plan_transactionally(source, target, plan)

    assert (target / "guide.rst").read_text(encoding="utf-8") == "old\n"
    assert stamp_path.read_bytes() == stamp_before
    assert not list(tmp_path.rglob("*.sync"))


def test_delete_publication_exception_after_unlink_rolls_back_exactly(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (target / "gone.rst").write_text("old\n", encoding="utf-8")
    stamp_path = module.write_target_only_mirror_stamp(target)
    stamp_before = stamp_path.read_bytes()
    plan = module.make_sync_plan(source, target, delete_extra=True)
    original_unlink = module._unlink_at
    injected = False

    def unlink_then_raise(parent, name, *, missing_ok=False, on_success=None):
        nonlocal injected
        result = original_unlink(
            parent,
            name,
            missing_ok=missing_ok,
            on_success=on_success,
        )
        if not injected and str(name) == "gone.rst":
            injected = True
            raise OSError("injected exception after unlink")
        return result

    monkeypatch.setattr(module, "_unlink_at", unlink_then_raise)

    with pytest.raises(OSError, match="after unlink"):
        module.apply_sync_plan_transactionally(source, target, plan)

    assert (target / "gone.rst").read_text(encoding="utf-8") == "old\n"
    assert stamp_path.read_bytes() == stamp_before
    assert not list(tmp_path.rglob("*.sync"))


def test_staging_cleanup_exception_is_retried_by_transaction_rollback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "created.rst").write_text("canonical\n", encoding="utf-8")
    stamp_path = module.write_target_only_mirror_stamp(target)
    stamp_before = stamp_path.read_bytes()
    plan = module.make_sync_plan(source, target, delete_extra=True)
    original_unlink = module._unlink_at
    injected = False

    def fail_first_staging_cleanup(parent, name, *, missing_ok=False):
        nonlocal injected
        if not injected and str(name).endswith(".sync"):
            injected = True
            raise OSError("injected staging cleanup failure")
        return original_unlink(parent, name, missing_ok=missing_ok)

    monkeypatch.setattr(module, "_unlink_at", fail_first_staging_cleanup)

    with pytest.raises(OSError, match="staging cleanup failure"):
        module.apply_sync_plan_transactionally(source, target, plan)

    assert not (target / "created.rst").exists()
    assert stamp_path.read_bytes() == stamp_before
    assert not list(tmp_path.rglob("*.sync"))


def test_source_mutation_during_snapshot_fails_before_target_mutation(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    source_file = source / "guide.rst"
    target_file = target / "guide.rst"
    source_file.write_text("canonical-before\n", encoding="utf-8")
    target_file.write_text("target-before\n", encoding="utf-8")
    stamp_path = module.write_target_only_mirror_stamp(target)
    stamp_before = stamp_path.read_bytes()
    original_copy2 = module.shutil.copy2
    mutated = False

    def mutate_source_after_snapshot_copy(src, dst, *args, **kwargs):
        nonlocal mutated
        result = original_copy2(src, dst, *args, **kwargs)
        if not mutated and Path(src) == source_file:
            mutated = True
            source_file.write_text("canonical-after\n", encoding="utf-8")
        return result

    monkeypatch.setattr(module.shutil, "copy2", mutate_source_after_snapshot_copy)

    exit_code = module.main(
        [
            "--source",
            str(source),
            "--target",
            str(target),
            "--apply",
            "--delete",
            "--quiet",
        ]
    )

    assert exit_code == 1
    assert (
        "changed while its sync snapshot was being captured" in capsys.readouterr().err
    )
    assert target_file.read_text(encoding="utf-8") == "target-before\n"
    assert stamp_path.read_bytes() == stamp_before


@pytest.mark.parametrize(
    "configured_environment",
    ["AGILAB_DOCS_SOURCE", "DOCS_REPOSITORY"],
)
def test_main_missing_configured_source_fails_even_with_skip_missing_source(
    tmp_path: Path,
    monkeypatch,
    capsys,
    configured_environment: str,
) -> None:
    module = _load_module()
    target = tmp_path / "target"
    target.mkdir()
    (target / "guide.rst").write_text("guide\n", encoding="utf-8")
    assert module.main(["--target", str(target), "--write-target-only-stamp"]) == 0
    capsys.readouterr()
    missing_source = tmp_path / "explicitly-configured-missing-source"
    monkeypatch.delenv(module.DOCS_SOURCE_ENV, raising=False)
    monkeypatch.delenv(module.DOCS_REPOSITORY_ENV, raising=False)
    monkeypatch.setenv(configured_environment, str(missing_source))

    exit_code = module.main(
        [
            "--target",
            str(target),
            "--verify-stamp",
            "--skip-missing-source",
            "--quiet",
        ]
    )

    assert exit_code == 1
    output = capsys.readouterr().out
    assert "configured canonical docs source not found" in output
    assert f"env:{configured_environment}" in output


def test_main_unconfigured_missing_source_allows_explicit_degraded_mode(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    module = _load_module()
    target = tmp_path / "target"
    target.mkdir()
    (target / "guide.rst").write_text("guide\n", encoding="utf-8")
    module.write_target_only_mirror_stamp(target)
    missing_source = tmp_path / "conventional-missing-source"
    monkeypatch.setattr(
        module,
        "canonical_source_configuration",
        lambda: module.CanonicalSourceConfiguration(
            path=missing_source,
            origin="default",
            required=False,
        ),
    )

    exit_code = module.main(
        [
            "--target",
            str(target),
            "--verify-stamp",
            "--skip-missing-source",
            "--quiet",
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "target integrity only" in output
    assert "canonical drift NOT CHECKED" in output

    exit_code = module.main(
        [
            "--target",
            str(target),
            "--check",
            "--skip-missing-source",
            "--quiet",
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "target integrity only" in output
    assert "canonical drift NOT CHECKED" in output


def test_verify_stamp_passes_after_apply(tmp_path: Path, capsys) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "guide.rst").write_text("guide\n", encoding="utf-8")

    assert (
        module.main(["--source", str(source), "--target", str(target), "--apply"]) == 0
    )

    exit_code = module.main(
        [
            "--source",
            str(source),
            "--target",
            str(target),
            "--verify-stamp",
        ]
    )

    assert exit_code == 0
    assert "mirror stamp ok:" in capsys.readouterr().out


def test_verify_stamp_detects_canonical_source_drift(tmp_path: Path, capsys) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "guide.rst").write_text("guide\n", encoding="utf-8")
    assert (
        module.main(["--source", str(source), "--target", str(target), "--apply"]) == 0
    )
    capsys.readouterr()
    (source / "guide.rst").write_text("canonical changed\n", encoding="utf-8")

    exit_code = module.main(
        [
            "--source",
            str(source),
            "--target",
            str(target),
            "--verify-stamp",
        ]
    )

    assert exit_code == 1
    assert "canonical source drift" in capsys.readouterr().out


def test_verified_stamp_rejects_self_source_and_unsynced_trees(tmp_path: Path) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "guide.rst").write_text("source\n", encoding="utf-8")
    (target / "guide.rst").write_text("target\n", encoding="utf-8")

    with pytest.raises(ValueError, match="same directory"):
        module.build_mirror_stamp(target, target)
    with pytest.raises(ValueError, match="differ"):
        module.build_mirror_stamp(source, target)


@pytest.mark.parametrize("source_is_child", [True, False])
def test_main_rejects_overlapping_source_and_target_before_mutation(
    tmp_path: Path,
    capsys,
    source_is_child: bool,
) -> None:
    module = _load_module()
    if source_is_child:
        target = tmp_path / "target"
        source = target / "canonical-source"
    else:
        source = tmp_path / "canonical-source"
        target = source / "target"
    source.mkdir(parents=True)
    target.mkdir(parents=True, exist_ok=True)
    canonical = source / "guide.rst"
    canonical.write_text("canonical\n", encoding="utf-8")
    target_file = target / "existing.rst"
    target_file.write_text("target\n", encoding="utf-8")

    exit_code = module.main(
        [
            "--source",
            str(source),
            "--target",
            str(target),
            "--apply",
            "--delete",
            "--quiet",
        ]
    )

    assert exit_code == 1
    assert "same directory or overlap" in capsys.readouterr().err
    assert canonical.read_text(encoding="utf-8") == "canonical\n"
    assert target_file.read_text(encoding="utf-8") == "target\n"
    assert not module.stamp_path_for_target(target).exists()


def test_make_sync_plan_rejects_samefile_alias(tmp_path: Path) -> None:
    module = _load_module()
    source = tmp_path / "source"
    source.mkdir()
    alias = tmp_path / "target-alias"
    _symlink_or_skip(alias, source, target_is_directory=True)

    with pytest.raises(ValueError, match="same directory or overlap"):
        module.make_sync_plan(source, alias, delete_extra=True)


def test_target_only_stamp_requires_separate_canonical_alignment_check(
    tmp_path: Path,
    capsys,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "guide.rst").write_text("guide\n", encoding="utf-8")
    (target / "guide.rst").write_text("guide\n", encoding="utf-8")

    exit_code = module.main(
        ["--target", str(target), "--write-target-only-stamp", "--quiet"]
    )

    assert exit_code == 0
    assert capsys.readouterr().out == ""
    payload = json.loads(
        module.stamp_path_for_target(target).read_text(encoding="utf-8")
    )
    assert payload["source_status"] == "unavailable"
    assert payload["source_digest_sha256"] is None

    exit_code = module.main(
        [
            "--source",
            str(source),
            "--target",
            str(target),
            "--verify-stamp",
            "--quiet",
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "source_status=unavailable" in output
    assert "canonical drift NOT CHECKED" in output

    status, message = module.verify_canonical_mirror_alignment(target, source)

    assert status == "pass"
    assert "canonical source and managed public mirror are aligned" in message

    (source / "guide.rst").write_text("canonical changed\n", encoding="utf-8")
    exit_code = module.main(
        [
            "--source",
            str(source),
            "--target",
            str(target),
            "--verify-stamp",
            "--quiet",
        ]
    )
    assert exit_code == 0
    output = capsys.readouterr().out
    assert "source_status=unavailable" in output
    assert "canonical drift NOT CHECKED" in output

    status, message = module.verify_canonical_mirror_alignment(target, source)

    assert status == "fail"
    assert "canonical source drift" in message


def test_refresh_target_integrity_stamp_preserves_verified_evidence_for_exclusions(
    tmp_path: Path,
    capsys,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "guide.rst").write_text("guide\n", encoding="utf-8")
    (target / "guide.rst").write_text("guide\n", encoding="utf-8")
    stamp_path = module.write_mirror_stamp(source, target)
    payload_before = json.loads(stamp_path.read_text(encoding="utf-8"))
    release_proof = target / "data" / "release_proof.toml"
    release_proof.parent.mkdir(parents=True)
    release_proof.write_text("[release]\n", encoding="utf-8")

    exit_code = module.main(
        ["--target", str(target), "--refresh-target-integrity-stamp"]
    )

    assert exit_code == 0
    assert "mirror stamp refreshed" in capsys.readouterr().out
    payload = json.loads(stamp_path.read_text(encoding="utf-8"))
    assert payload["format_version"] == 3
    assert payload["source_status"] == "verified"
    assert payload["source_digest_sha256"] == payload["target_digest_sha256"]
    assert payload["source_digest_sha256"] == payload_before["source_digest_sha256"]
    assert payload["public_owned_file_count"] == 1
    assert (
        payload["public_owned_digest_sha256"]
        != payload_before["public_owned_digest_sha256"]
    )
    ok, _message = module.verify_target_mirror_integrity(target)
    assert ok is True


def test_release_refresh_refuses_unrelated_ui_robot_evidence_change(
    tmp_path: Path,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "guide.rst").write_text("guide\n", encoding="utf-8")
    (target / "guide.rst").write_text("guide\n", encoding="utf-8")
    ui_evidence = target / "data" / "ui_robot_evidence.json"
    ui_evidence.parent.mkdir(parents=True)
    ui_evidence.write_text('{"archive_download_url":"trusted"}\n', encoding="utf-8")
    stamp_path = module.write_mirror_stamp(source, target)
    stamp_before = stamp_path.read_bytes()

    ui_evidence.write_text('{"archive_download_url":"attacker"}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="ui_robot_evidence.json"):
        module.refresh_target_integrity_stamp(target)

    assert stamp_path.read_bytes() == stamp_before
    ok, _message = module.verify_target_mirror_integrity(target)
    assert ok is False


def test_refresh_target_integrity_stamp_refuses_changed_managed_target(
    tmp_path: Path,
    capsys,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "guide.rst").write_text("guide\n", encoding="utf-8")
    (target / "guide.rst").write_text("guide\n", encoding="utf-8")
    stamp_path = module.write_mirror_stamp(source, target)
    stamp_before = stamp_path.read_bytes()
    (target / "guide.rst").write_text(
        "release changed managed docs\n", encoding="utf-8"
    )

    exit_code = module.main(
        [
            "--target",
            str(target),
            "--refresh-target-integrity-stamp",
            "--quiet",
        ]
    )

    assert exit_code == 1
    assert "refusing to re-baseline changed managed docs" in capsys.readouterr().err
    assert stamp_path.read_bytes() == stamp_before


def test_refresh_target_integrity_stamp_preserves_valid_target_only_evidence(
    tmp_path: Path,
) -> None:
    module = _load_module()
    target = tmp_path / "target"
    target.mkdir()
    (target / "guide.rst").write_text("guide\n", encoding="utf-8")
    stamp_path = module.write_target_only_mirror_stamp(target)
    stamp_before = stamp_path.read_bytes()

    exit_code = module.main(
        [
            "--target",
            str(target),
            "--refresh-target-integrity-stamp",
            "--quiet",
        ]
    )

    assert exit_code == 0
    assert stamp_path.read_bytes() == stamp_before


def test_refresh_target_integrity_stamp_refuses_missing_stamp(
    tmp_path: Path,
    capsys,
) -> None:
    module = _load_module()
    target = tmp_path / "target"
    target.mkdir()
    (target / "guide.rst").write_text("guide\n", encoding="utf-8")
    stamp_path = module.stamp_path_for_target(target)
    assert not stamp_path.exists()

    exit_code = module.main(
        [
            "--target",
            str(target),
            "--refresh-target-integrity-stamp",
            "--quiet",
        ]
    )

    assert exit_code == 1
    assert "missing mirror stamp" in capsys.readouterr().err
    assert not stamp_path.exists()


def test_target_only_stamp_still_detects_target_mutation(
    tmp_path: Path,
    capsys,
) -> None:
    module = _load_module()
    target = tmp_path / "target"
    target.mkdir()
    (target / "guide.rst").write_text("guide\n", encoding="utf-8")
    assert module.main(["--target", str(target), "--write-target-only-stamp"]) == 0
    capsys.readouterr()
    (target / "guide.rst").write_text("changed\n", encoding="utf-8")

    exit_code = module.main(
        [
            "--source",
            str(tmp_path / "missing-source"),
            "--target",
            str(target),
            "--verify-stamp",
            "--skip-missing-source",
        ]
    )

    assert exit_code == 1
    assert "mirror stamp mismatch" in capsys.readouterr().out


def test_verify_stamp_detects_unmanaged_edit(tmp_path: Path, capsys) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "guide.rst").write_text("guide\n", encoding="utf-8")

    assert (
        module.main(["--source", str(source), "--target", str(target), "--apply"]) == 0
    )
    (target / "guide.rst").write_text("changed\n", encoding="utf-8")

    exit_code = module.main(
        [
            "--source",
            str(source),
            "--target",
            str(target),
            "--verify-stamp",
        ]
    )

    assert exit_code == 1
    assert "mirror stamp mismatch" in capsys.readouterr().out


def test_verify_stamp_reports_missing_stamp(tmp_path: Path, capsys) -> None:
    module = _load_module()
    target = tmp_path / "target"
    target.mkdir()
    (target / "guide.rst").write_text("guide\n", encoding="utf-8")

    exit_code = module.main(
        [
            "--source",
            str(tmp_path / "source"),
            "--target",
            str(target),
            "--verify-stamp",
        ]
    )

    assert exit_code == 1
    assert "missing mirror stamp" in capsys.readouterr().out


def test_verify_target_integrity_reports_missing_stamp(tmp_path: Path) -> None:
    module = _load_module()
    target = tmp_path / "target"
    target.mkdir()
    (target / "guide.rst").write_text("guide\n", encoding="utf-8")

    ok, message = module.verify_target_mirror_integrity(target)

    assert ok is False
    assert "missing mirror stamp" in message


def test_verify_target_integrity_rejects_regular_file_target(tmp_path: Path) -> None:
    module = _load_module()
    target = tmp_path / "target"
    target.write_text("not a directory\n", encoding="utf-8")

    ok, message = module.verify_target_mirror_integrity(target)

    assert ok is False
    assert "mirror target is not a directory" in message


def test_v3_stamp_is_bound_to_sibling_target_identity(tmp_path: Path) -> None:
    module = _load_module()
    target_a = tmp_path / "target-a"
    target_b = tmp_path / "target-b"
    target_a.mkdir()
    target_b.mkdir()
    for target in (target_a, target_b):
        (target / "guide.rst").write_text("same\n", encoding="utf-8")
    module.write_target_only_mirror_stamp(target_a)

    a_ok, _a_message = module.verify_target_mirror_integrity(target_a)
    b_ok, b_message = module.verify_target_mirror_integrity(target_b)

    assert a_ok is True
    assert b_ok is False
    assert "managed_target mismatch" in b_message


def test_verify_stamp_rejects_non_object_json(tmp_path: Path) -> None:
    module = _load_module()
    target = tmp_path / "target"
    target.mkdir()
    module.stamp_path_for_target(target).write_text("[]\n", encoding="utf-8")

    ok, message = module.verify_mirror_stamp(
        target,
        source=None,
        skip_missing_source=True,
    )

    assert ok is False
    assert "expected a JSON object" in message


def test_verify_stamp_rejects_invalid_utf8_without_traceback(tmp_path: Path) -> None:
    module = _load_module()
    target = tmp_path / "target"
    target.mkdir()
    module.stamp_path_for_target(target).write_bytes(b"\xff\xfe\x00")

    ok, message = module.verify_target_mirror_integrity(target)

    assert ok is False
    assert "invalid mirror stamp" in message


def test_v1_full_tree_stamp_remains_compatible(tmp_path: Path) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    for root in (source, target):
        (root / "guide.rst").write_text("guide\n", encoding="utf-8")
        release_proof = root / "data" / "release_proof.toml"
        release_proof.parent.mkdir(parents=True)
        release_proof.write_text("[release]\n", encoding="utf-8")
    _write_v1_stamp(module, source, target)

    ok, message = module.verify_mirror_stamp(
        target,
        source=source,
    )

    assert ok is True
    assert "legacy v1 mirror stamp integrity verified" in message
    assert "canonical source matches legacy v1 evidence" in message


def test_v1_divergent_source_and_target_is_target_integrity_only(
    tmp_path: Path,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "guide.rst").write_text("canonical-a\n", encoding="utf-8")
    (target / "guide.rst").write_text("mirror-b\n", encoding="utf-8")
    source_state = module._legacy_manifest_state(source)
    target_state = module._legacy_manifest_state(target)
    _write_stamp_payload(
        module,
        target,
        {
            "format_version": module.LEGACY_FULL_TREE_STAMP_FORMAT_VERSION,
            "managed_target": module.STAMP_MANAGED_TARGET,
            "source_hint": module.STAMP_SOURCE_HINT,
            "source_digest_sha256": source_state["digest_sha256"],
            "target_digest_sha256": target_state["digest_sha256"],
            "file_count": target_state["file_count"],
            "sync_tool": module.STAMP_SYNC_TOOL,
        },
    )

    target_ok, _message = module.verify_target_mirror_integrity(target)
    canonical_ok, message = module.verify_mirror_stamp(target, source)

    assert target_ok is True
    assert canonical_ok is False
    assert "valid only as target-integrity evidence" in message


def test_v2_stamp_requires_explicit_recovery_instead_of_blessing_public_evidence(
    tmp_path: Path,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "guide.rst").write_text("guide\n", encoding="utf-8")
    (target / "guide.rst").write_text("guide\n", encoding="utf-8")
    release_proof = target / "data" / "release_proof.toml"
    release_proof.parent.mkdir(parents=True)
    release_proof.write_text("[release]\n", encoding="utf-8")
    stamp_path = _write_v2_stamp(module, source, target)

    ok, message = module.verify_target_mirror_integrity(target)

    assert ok is False
    assert "legacy v2 mirror stamp does not cover public-owned evidence" in message
    assert "--apply --delete" in message
    assert "--write-target-only-stamp" in message
    assert "--refresh-target-integrity-stamp" not in message
    stamp_before = stamp_path.read_bytes()
    with pytest.raises(ValueError, match="no complete per-file public evidence"):
        module.refresh_target_integrity_stamp(target)
    assert stamp_path.read_bytes() == stamp_before


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("managed_target", "other/source"),
        ("source_hint", "untrusted/source"),
        ("sync_tool", "tools/other_sync.py"),
    ],
)
def test_verify_stamp_rejects_false_identity_metadata(
    tmp_path: Path,
    field: str,
    replacement: str,
) -> None:
    module = _load_module()
    target = tmp_path / "target"
    target.mkdir()
    (target / "guide.rst").write_text("guide\n", encoding="utf-8")
    stamp_path = module.write_target_only_mirror_stamp(target)
    payload = json.loads(stamp_path.read_text(encoding="utf-8"))
    payload[field] = replacement
    stamp_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    ok, message = module.verify_mirror_stamp(
        target,
        source=None,
        skip_missing_source=True,
    )

    assert ok is False
    assert f"{field} mismatch" in message


def test_structured_target_and_canonical_checks_do_not_call_missing_source_pass(
    tmp_path: Path,
) -> None:
    module = _load_module()
    target = tmp_path / "target"
    target.mkdir()
    (target / "guide.rst").write_text("guide\n", encoding="utf-8")
    module.write_target_only_mirror_stamp(target)

    target_ok, target_message = module.verify_target_mirror_integrity(target)
    canonical_status, canonical_message = module.verify_canonical_mirror_alignment(
        target,
        tmp_path / "missing-canonical",
    )

    assert target_ok is True
    assert "target integrity verified" in target_message
    assert canonical_status == "skipped"
    assert "canonical drift NOT CHECKED" in canonical_message


def test_stamp_symlink_is_rejected_by_verify_write_and_refresh(
    tmp_path: Path,
) -> None:
    module = _load_module()
    target = tmp_path / "target"
    target.mkdir()
    (target / "guide.rst").write_text("guide\n", encoding="utf-8")
    stamp_path = module.write_target_only_mirror_stamp(target)
    external_stamp = tmp_path / "external-stamp.json"
    stamp_path.rename(external_stamp)
    external_before = external_stamp.read_bytes()
    _symlink_or_skip(stamp_path, external_stamp, target_is_directory=False)

    ok, message = module.verify_target_mirror_integrity(target)
    assert ok is False
    assert "not a regular file" in message
    with pytest.raises(ValueError, match="not a regular file"):
        module.write_target_only_mirror_stamp(target)
    with pytest.raises(ValueError, match="not a regular file"):
        module.refresh_target_integrity_stamp(target)

    assert stamp_path.is_symlink()
    assert external_stamp.read_bytes() == external_before


def test_non_posix_apply_fails_before_mutation_and_help_names_boundary(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "guide.rst").write_text("new\n", encoding="utf-8")
    target_file = target / "guide.rst"
    target_file.write_text("old\n", encoding="utf-8")
    stamp_path = module.write_target_only_mirror_stamp(target)
    stamp_before = stamp_path.read_bytes()
    plan = module.make_sync_plan(source, target, delete_extra=True)
    monkeypatch.setattr(
        module,
        "_supports_pinned_directory_operations",
        lambda: False,
    )

    with pytest.raises(ValueError, match="check and verification remain available"):
        module.apply_sync_plan_transactionally(source, target, plan)

    assert target_file.read_text(encoding="utf-8") == "old\n"
    assert stamp_path.read_bytes() == stamp_before
    assert "Windows supports check and verification modes only" in " ".join(
        module.build_parser().format_help().split()
    )


def test_apply_does_not_bootstrap_missing_target_through_symlinked_ancestor(
    tmp_path: Path,
    capsys,
) -> None:
    module = _load_module()
    source = tmp_path / "canonical"
    repo = tmp_path / "repo"
    outside = tmp_path / "outside"
    source.mkdir()
    repo.mkdir()
    outside.mkdir()
    (source / "guide.rst").write_text("canonical\n", encoding="utf-8")
    docs_alias = repo / "docs"
    _symlink_or_skip(docs_alias, outside, target_is_directory=True)
    target = docs_alias / "source"

    exit_code = module.main(
        [
            "--source",
            str(source),
            "--target",
            str(target),
            "--apply",
            "--delete",
            "--quiet",
        ]
    )

    assert exit_code == 1
    assert "automatic bootstrap is disabled" in capsys.readouterr().err
    assert not (outside / "source").exists()
    assert not module.stamp_path_for_target(target).exists()


def test_full_apply_refuses_to_rebaseline_tampered_ui_evidence(
    tmp_path: Path,
    capsys,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "guide.rst").write_text("same\n", encoding="utf-8")
    (target / "guide.rst").write_text("same\n", encoding="utf-8")
    evidence = target / "data" / "ui_robot_evidence.json"
    evidence.parent.mkdir()
    evidence.write_text('{"status": "verified"}\n', encoding="utf-8")
    stamp_path = module.write_mirror_stamp(source, target)
    stamp_before = stamp_path.read_bytes()
    evidence.write_text('{"status": "tampered"}\n', encoding="utf-8")

    exit_code = module.main(
        [
            "--source",
            str(source),
            "--target",
            str(target),
            "--apply",
            "--delete",
            "--quiet",
        ]
    )

    assert exit_code == 1
    assert "data/ui_robot_evidence.json" in capsys.readouterr().err
    assert evidence.read_text(encoding="utf-8") == '{"status": "tampered"}\n'
    assert stamp_path.read_bytes() == stamp_before


def test_verified_stamp_writer_rejects_target_only_payload_substitution(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "guide.rst").write_text("same\n", encoding="utf-8")
    (target / "guide.rst").write_text("same\n", encoding="utf-8")
    original_write = module._write_stamp_payload

    def substitute_payload(path, payload, *, boundary):
        original_write(path, payload, boundary=boundary)
        substitute = module._build_target_only_stamp_at_boundary(boundary)
        original_write(path, substitute, boundary=boundary)

    monkeypatch.setattr(module, "_write_stamp_payload", substitute_payload)

    with pytest.raises(RuntimeError, match="substituted stamp"):
        module.write_mirror_stamp(source, target)

    payload = json.loads(module.stamp_path_for_target(target).read_text("utf-8"))
    assert payload["source_status"] == "unavailable"


def test_refresh_rejects_target_only_payload_substitution(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "guide.rst").write_text("same\n", encoding="utf-8")
    (target / "guide.rst").write_text("same\n", encoding="utf-8")
    release_proof = target / "release-proof.rst"
    release_proof.write_text("before\n", encoding="utf-8")
    module.write_mirror_stamp(source, target)
    release_proof.write_text("after\n", encoding="utf-8")
    original_write = module._write_stamp_payload

    def substitute_payload(path, payload, *, boundary):
        original_write(path, payload, boundary=boundary)
        substitute = module._build_target_only_stamp_at_boundary(boundary)
        original_write(path, substitute, boundary=boundary)

    monkeypatch.setattr(module, "_write_stamp_payload", substitute_payload)

    with pytest.raises(RuntimeError, match="substituted stamp"):
        module.refresh_target_integrity_stamp(target)

    payload = json.loads(module.stamp_path_for_target(target).read_text("utf-8"))
    assert payload["source_status"] == "unavailable"


@pytest.mark.parametrize("operation", ["verified", "refresh"])
def test_concurrent_stamp_replacement_during_verification_is_preserved(
    tmp_path: Path,
    monkeypatch,
    operation: str,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "guide.rst").write_text("same\n", encoding="utf-8")
    (target / "guide.rst").write_text("same\n", encoding="utf-8")
    stamp_path = module.write_target_only_mirror_stamp(target)
    old_stamp = stamp_path.read_bytes()
    if operation == "refresh":
        module.write_mirror_stamp(source, target)
        (target / "release-proof.rst").write_text("release\n", encoding="utf-8")
    original_write = module._write_stamp_payload
    concurrent_bytes: bytes | None = None

    def replace_then_fail(boundary, payload, *, source, **_kwargs):
        nonlocal concurrent_bytes
        original_write(
            module.stamp_path_for_target(boundary.target),
            payload,
            boundary=boundary,
        )
        concurrent_bytes = module._render_stamp_payload(payload)
        raise OSError("injected failure after concurrent replacement")

    monkeypatch.setattr(module, "_verify_payload_at_boundary", replace_then_fail)

    with pytest.raises(RuntimeError, match="rollback was incomplete"):
        if operation == "verified":
            module.write_mirror_stamp(source, target)
        else:
            module.refresh_target_integrity_stamp(target)

    assert concurrent_bytes is not None
    assert stamp_path.read_bytes() == concurrent_bytes
    assert stamp_path.read_bytes() != old_stamp


def test_nested_transaction_does_not_remove_concurrent_stamp(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "guide.rst").write_text("same\n", encoding="utf-8")
    outer_plan = module.make_sync_plan(source, target, delete_extra=True)
    inner_plan = module.make_sync_plan(source, target, delete_extra=True)
    original_apply = module._apply_sync_plan_safely
    nested = False
    concurrent_stamp: bytes | None = None

    def run_inner_before_outer(*args, **kwargs):
        nonlocal nested, concurrent_stamp
        if not nested:
            nested = True
            module.apply_sync_plan_transactionally(source, target, inner_plan)
            concurrent_stamp = module.stamp_path_for_target(target).read_bytes()
        return original_apply(*args, **kwargs)

    monkeypatch.setattr(module, "_apply_sync_plan_safely", run_inner_before_outer)

    with pytest.raises(RuntimeError, match="rollback was incomplete"):
        module.apply_sync_plan_transactionally(source, target, outer_plan)

    assert concurrent_stamp is not None
    assert module.stamp_path_for_target(target).read_bytes() == concurrent_stamp
    assert (target / "guide.rst").read_text(encoding="utf-8") == "same\n"


@pytest.mark.parametrize("operation", ["target-only", "verified"])
def test_stamp_publication_rejects_target_ancestor_swap(
    tmp_path: Path,
    monkeypatch,
    operation: str,
) -> None:
    module = _load_module()
    repo = tmp_path / "repo"
    docs = repo / "docs"
    target = docs / "source"
    source = tmp_path / "canonical"
    outside_docs = tmp_path / "outside-docs"
    outside_target = outside_docs / "source"
    target.mkdir(parents=True)
    source.mkdir()
    outside_target.mkdir(parents=True)
    (target / "guide.rst").write_text("same\n", encoding="utf-8")
    (source / "guide.rst").write_text("same\n", encoding="utf-8")
    (outside_target / "guide.rst").write_text("outside\n", encoding="utf-8")
    saved_docs = repo / "saved-docs"
    swapped = False

    if operation == "target-only":
        original_build = module._build_target_only_stamp_at_boundary

        def build_then_swap(boundary):
            nonlocal swapped
            payload = original_build(boundary)
            docs.rename(saved_docs)
            os.symlink(outside_docs, docs, target_is_directory=True)
            swapped = True
            return payload

        monkeypatch.setattr(
            module,
            "_build_target_only_stamp_at_boundary",
            build_then_swap,
        )
    else:
        original_build = module._build_mirror_stamp_at_boundary

        def build_then_swap(source_path, boundary, **kwargs):
            nonlocal swapped
            payload = original_build(source_path, boundary, **kwargs)
            docs.rename(saved_docs)
            os.symlink(outside_docs, docs, target_is_directory=True)
            swapped = True
            return payload

        monkeypatch.setattr(
            module,
            "_build_mirror_stamp_at_boundary",
            build_then_swap,
        )

    with pytest.raises(ValueError, match="ancestry changed"):
        if operation == "target-only":
            module.write_target_only_mirror_stamp(target)
        else:
            module.write_mirror_stamp(source, target)

    assert swapped is True
    assert not (outside_docs / module.STAMP_FILE_NAME).exists()
    assert not (saved_docs / module.STAMP_FILE_NAME).exists()
    assert (outside_target / "guide.rst").read_text(encoding="utf-8") == "outside\n"


def test_apply_uses_pinned_root_and_rolls_back_after_target_ancestor_swap(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    repo = tmp_path / "repo"
    docs = repo / "docs"
    target = docs / "source"
    source = tmp_path / "canonical"
    outside_docs = tmp_path / "outside-docs"
    outside_target = outside_docs / "source"
    target.mkdir(parents=True)
    source.mkdir()
    outside_target.mkdir(parents=True)
    (source / "created.rst").write_text("canonical\n", encoding="utf-8")
    (outside_target / "outside.rst").write_text("outside\n", encoding="utf-8")
    plan = module.make_sync_plan(source, target, delete_extra=True)
    original_stage = module._stage_copy_at
    saved_docs = repo / "saved-docs"
    swapped = False

    def stage_then_swap(*args, **kwargs):
        nonlocal swapped
        artifact = original_stage(*args, **kwargs)
        if not swapped:
            docs.rename(saved_docs)
            os.symlink(outside_docs, docs, target_is_directory=True)
            swapped = True
        return artifact

    monkeypatch.setattr(module, "_stage_copy_at", stage_then_swap)

    with pytest.raises(ValueError, match="ancestry changed"):
        module.apply_sync_plan_transactionally(source, target, plan)

    assert swapped is True
    assert not (outside_target / "created.rst").exists()
    assert not (saved_docs / "source" / "created.rst").exists()
    assert (outside_target / "outside.rst").read_text(encoding="utf-8") == "outside\n"
    assert not (outside_docs / module.STAMP_FILE_NAME).exists()
    assert not (saved_docs / module.STAMP_FILE_NAME).exists()


@pytest.mark.parametrize("overlap", ["same", "source-parent", "target-parent"])
def test_write_verified_stamp_rejects_same_or_overlapping_trees(
    tmp_path: Path,
    overlap: str,
) -> None:
    module = _load_module()
    if overlap == "same":
        source = target = tmp_path / "tree"
        source.mkdir()
    elif overlap == "source-parent":
        source = tmp_path / "source"
        target = source / "target"
        target.mkdir(parents=True)
    else:
        target = tmp_path / "target"
        source = target / "source"
        source.mkdir(parents=True)
    (source / "guide.rst").write_text("same\n", encoding="utf-8")
    if source != target:
        (target / "guide.rst").write_text("same\n", encoding="utf-8")

    with pytest.raises(ValueError, match="same directory or overlap"):
        module.write_mirror_stamp(source, target)

    assert not module.stamp_path_for_target(target).exists()


def test_public_evidence_change_after_apply_is_not_blessed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    source_file = source / "guide.rst"
    target_file = target / "guide.rst"
    source_file.write_text("old\n", encoding="utf-8")
    target_file.write_text("old\n", encoding="utf-8")
    evidence = target / "data" / "ui_robot_evidence.json"
    evidence.parent.mkdir()
    evidence.write_text('{"status": "verified"}\n', encoding="utf-8")
    stamp_path = module.write_mirror_stamp(source, target)
    stamp_before = stamp_path.read_bytes()
    source_file.write_text("new\n", encoding="utf-8")
    plan = module.make_sync_plan(source, target, delete_extra=True)
    original_apply = module._apply_sync_plan_safely

    def apply_then_tamper(*args, **kwargs):
        original_apply(*args, **kwargs)
        evidence.write_text('{"status": "tampered"}\n', encoding="utf-8")

    monkeypatch.setattr(module, "_apply_sync_plan_safely", apply_then_tamper)

    with pytest.raises(ValueError, match="public-owned evidence changed"):
        module.apply_sync_plan_transactionally(source, target, plan)

    assert target_file.read_text(encoding="utf-8") == "old\n"
    assert evidence.read_text(encoding="utf-8") == '{"status": "tampered"}\n'
    assert stamp_path.read_bytes() == stamp_before


def test_create_pre_effect_eexist_preserves_unowned_equal_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "created.rst").write_text("canonical\n", encoding="utf-8")
    stamp_path = module.write_target_only_mirror_stamp(target)
    stamp_before = stamp_path.read_bytes()
    plan = module.make_sync_plan(source, target, delete_extra=True)

    def concurrent_equal_link(parent, staged, destination_name, **_kwargs):
        os.link(
            staged,
            destination_name,
            src_dir_fd=parent.directory_fd,
            dst_dir_fd=parent.directory_fd,
            follow_symlinks=False,
        )
        raise FileExistsError("injected pre-effect EEXIST")

    monkeypatch.setattr(module, "_link_no_replace_at", concurrent_equal_link)

    with pytest.raises(ValueError, match="appeared after planning"):
        module.apply_sync_plan_transactionally(source, target, plan)

    assert (target / "created.rst").read_text(encoding="utf-8") == "canonical\n"
    assert stamp_path.read_bytes() == stamp_before


def test_update_pre_effect_failure_preserves_unowned_equal_replacement(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "guide.rst").write_text("new\n", encoding="utf-8")
    destination = target / "guide.rst"
    destination.write_text("old\n", encoding="utf-8")
    stamp_path = module.write_target_only_mirror_stamp(target)
    stamp_before = stamp_path.read_bytes()
    plan = module.make_sync_plan(source, target, delete_extra=True)

    def concurrent_equal_replace(parent, staged, destination_name, **_kwargs):
        os.unlink(destination_name, dir_fd=parent.directory_fd)
        os.link(
            staged,
            destination_name,
            src_dir_fd=parent.directory_fd,
            dst_dir_fd=parent.directory_fd,
            follow_symlinks=False,
        )
        raise OSError("injected pre-effect replace failure")

    monkeypatch.setattr(module, "_replace_at", concurrent_equal_replace)

    with pytest.raises(OSError, match="pre-effect replace failure"):
        module.apply_sync_plan_transactionally(source, target, plan)

    assert destination.read_text(encoding="utf-8") == "new\n"
    assert stamp_path.read_bytes() == stamp_before


def test_delete_pre_effect_enoent_does_not_recreate_unowned_absence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    destination = target / "gone.rst"
    destination.write_text("old\n", encoding="utf-8")
    stamp_path = module.write_target_only_mirror_stamp(target)
    stamp_before = stamp_path.read_bytes()
    plan = module.make_sync_plan(source, target, delete_extra=True)

    def concurrent_absence(parent, name, **_kwargs):
        os.unlink(name, dir_fd=parent.directory_fd)
        raise FileNotFoundError("injected pre-effect ENOENT")

    monkeypatch.setattr(module, "_unlink_at", concurrent_absence)

    with pytest.raises(FileNotFoundError, match="pre-effect ENOENT"):
        module.apply_sync_plan_transactionally(source, target, plan)

    assert not destination.exists()
    assert stamp_path.read_bytes() == stamp_before


def test_verified_source_is_rechecked_after_final_target_verification(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    source_file = source / "guide.rst"
    source_file.write_text("same\n", encoding="utf-8")
    (target / "guide.rst").write_text("same\n", encoding="utf-8")
    module.write_mirror_stamp(source, target)
    original_verify = module._verify_target_stamp
    calls = 0

    def mutate_source_after_final_target_check(target_path):
        nonlocal calls
        result = original_verify(target_path)
        calls += 1
        if calls == 2:
            source_file.write_text("changed\n", encoding="utf-8")
        return result

    monkeypatch.setattr(
        module, "_verify_target_stamp", mutate_source_after_final_target_check
    )

    ok, message = module.verify_mirror_stamp(target, source)

    assert ok is False
    assert "source changed during stamp verification" in message


def test_alignment_rejects_source_change_after_plan(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    source_file = source / "guide.rst"
    source_file.write_text("same\n", encoding="utf-8")
    (target / "guide.rst").write_text("same\n", encoding="utf-8")
    module.write_mirror_stamp(source, target)
    original_plan = module.make_sync_plan

    def plan_then_mutate(*args, **kwargs):
        plan = original_plan(*args, **kwargs)
        source_file.write_text("changed\n", encoding="utf-8")
        return plan

    monkeypatch.setattr(module, "make_sync_plan", plan_then_mutate)

    result = module.canonical_mirror_alignment_result(target, source)

    assert result.status == "fail"
    assert result.checked is False
    assert "source changed during alignment verification" in result.message


def test_target_verification_rejects_stamp_change_during_tree_capture(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    target = tmp_path / "target"
    target.mkdir()
    (target / "guide.rst").write_text("same\n", encoding="utf-8")
    stamp_path = module.write_target_only_mirror_stamp(target)
    original_states = module._stable_target_evidence_states
    mutated = False

    def capture_then_mutate(root):
        nonlocal mutated
        result = original_states(root)
        if not mutated:
            mutated = True
            stamp_path.write_text("{}\n", encoding="utf-8")
        return result

    monkeypatch.setattr(module, "_stable_target_evidence_states", capture_then_mutate)

    ok, message = module.verify_target_mirror_integrity(target)

    assert ok is False
    assert "stamp changed while target evidence was verified" in message


def test_failed_deep_create_removes_transaction_owned_directories(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    nested_source = source / "deep" / "nested" / "guide.rst"
    nested_source.parent.mkdir(parents=True)
    nested_source.write_text("canonical\n", encoding="utf-8")
    stamp_path = module.write_target_only_mirror_stamp(target)
    stamp_before = stamp_path.read_bytes()
    plan = module.make_sync_plan(source, target, delete_extra=True)

    def fail_stamp(*_args, **_kwargs):
        raise OSError("injected stamp failure")

    monkeypatch.setattr(module, "_write_stamp_payload", fail_stamp)

    with pytest.raises(OSError, match="injected stamp failure"):
        module.apply_sync_plan_transactionally(source, target, plan)

    assert list(target.iterdir()) == []
    assert stamp_path.read_bytes() == stamp_before


def test_failed_deep_create_preserves_preexisting_parent_only(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (target / "deep").mkdir()
    nested_source = source / "deep" / "nested" / "guide.rst"
    nested_source.parent.mkdir(parents=True)
    nested_source.write_text("canonical\n", encoding="utf-8")
    module.write_target_only_mirror_stamp(target)
    plan = module.make_sync_plan(source, target, delete_extra=True)
    monkeypatch.setattr(
        module,
        "_write_stamp_payload",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("stamp failure")),
    )

    with pytest.raises(OSError, match="stamp failure"):
        module.apply_sync_plan_transactionally(source, target, plan)

    assert (target / "deep").is_dir()
    assert list((target / "deep").iterdir()) == []


def test_concurrent_content_in_created_directory_is_preserved_and_reported(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    nested_source = source / "deep" / "guide.rst"
    nested_source.parent.mkdir()
    nested_source.write_text("canonical\n", encoding="utf-8")
    stamp_path = module.write_target_only_mirror_stamp(target)
    stamp_before = stamp_path.read_bytes()
    plan = module.make_sync_plan(source, target, delete_extra=True)
    concurrent = target / "deep" / "concurrent.txt"

    def add_concurrent_then_fail(*_args, **_kwargs):
        concurrent.write_text("keep\n", encoding="utf-8")
        raise OSError("stamp failure")

    monkeypatch.setattr(module, "_write_stamp_payload", add_concurrent_then_fail)

    with pytest.raises(RuntimeError, match="became nonempty concurrently"):
        module.apply_sync_plan_transactionally(source, target, plan)

    assert concurrent.read_text(encoding="utf-8") == "keep\n"
    assert not (target / "deep" / "guide.rst").exists()
    assert stamp_path.read_bytes() == stamp_before


@pytest.mark.parametrize(
    ("operation", "expected_mode"),
    [("update", 0o600), ("delete", 0o700)],
)
def test_failed_transaction_restores_prior_file_mode(
    tmp_path: Path,
    monkeypatch,
    operation: str,
    expected_mode: int,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    destination = target / "guide.rst"
    destination.write_text("old\n", encoding="utf-8")
    destination.chmod(expected_mode)
    if operation == "update":
        (source / "guide.rst").write_text("new\n", encoding="utf-8")
    module.write_target_only_mirror_stamp(target)
    plan = module.make_sync_plan(source, target, delete_extra=True)
    monkeypatch.setattr(
        module,
        "_write_stamp_payload",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("stamp failure")),
    )

    with pytest.raises(OSError, match="stamp failure"):
        module.apply_sync_plan_transactionally(source, target, plan)

    assert destination.read_text(encoding="utf-8") == "old\n"
    assert destination.stat().st_mode & 0o777 == expected_mode


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO creation is POSIX-only")
def test_special_files_are_rejected_and_cannot_hide_from_target_evidence(
    tmp_path: Path,
) -> None:
    module = _load_module()
    target = tmp_path / "target"
    target.mkdir()
    (target / "guide.rst").write_text("same\n", encoding="utf-8")
    fifo = target / "hidden.fifo"
    os.mkfifo(fifo)

    with pytest.raises(ValueError, match="special filesystem entries"):
        module.write_target_only_mirror_stamp(target)

    fifo.unlink()
    module.write_target_only_mirror_stamp(target)
    os.mkfifo(fifo)

    ok, message = module.verify_target_mirror_integrity(target)

    assert ok is False
    assert "special filesystem entries" in message


def test_check_mode_rejects_source_change_during_planning(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    source_file = source / "guide.rst"
    source_file.write_text("same\n", encoding="utf-8")
    (target / "guide.rst").write_text("same\n", encoding="utf-8")
    original_plan = module.make_sync_plan

    def plan_then_mutate(*args, **kwargs):
        plan = original_plan(*args, **kwargs)
        source_file.write_text("changed\n", encoding="utf-8")
        return plan

    monkeypatch.setattr(module, "make_sync_plan", plan_then_mutate)

    exit_code = module.main(
        ["--source", str(source), "--target", str(target), "--check", "--delete"]
    )

    assert exit_code == 1
    assert "source changed while planning" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("mode", "diagnostic"),
    [
        ("--write-target-only-stamp", "mirror stamp not written"),
        ("--refresh-target-integrity-stamp", "mirror stamp not refreshed"),
    ],
)
def test_stamp_cli_modes_convert_runtime_failures_to_diagnostics(
    tmp_path: Path,
    monkeypatch,
    capsys,
    mode: str,
    diagnostic: str,
) -> None:
    module = _load_module()
    target = tmp_path / "target"
    target.mkdir()
    if mode == "--write-target-only-stamp":
        monkeypatch.setattr(
            module,
            "write_target_only_mirror_stamp",
            lambda _target: (_ for _ in ()).throw(RuntimeError("concurrent stamp")),
        )
    else:
        monkeypatch.setattr(
            module,
            "refresh_target_integrity_stamp",
            lambda _target: (_ for _ in ()).throw(RuntimeError("concurrent stamp")),
        )

    exit_code = module.main(["--target", str(target), mode])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert diagnostic in captured.err
    assert "concurrent stamp" in captured.err


def test_mkdir_post_effect_failure_rolls_back_owned_directory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    nested_source = source / "deep" / "guide.rst"
    nested_source.parent.mkdir()
    nested_source.write_text("canonical\n", encoding="utf-8")
    stamp_path = module.write_target_only_mirror_stamp(target)
    stamp_before = stamp_path.read_bytes()
    plan = module.make_sync_plan(source, target, delete_extra=True)
    original_mkdir = module._mkdir_at
    injected = False

    def mkdir_then_raise(parent_fd, component, *, on_success):
        nonlocal injected
        result = original_mkdir(
            parent_fd,
            component,
            on_success=on_success,
        )
        if not injected and component == "deep":
            injected = True
            raise OSError("injected post-effect mkdir failure")
        return result

    monkeypatch.setattr(module, "_mkdir_at", mkdir_then_raise)

    with pytest.raises(OSError, match="post-effect mkdir failure"):
        module.apply_sync_plan_transactionally(source, target, plan)

    assert injected is True
    assert list(target.iterdir()) == []
    assert stamp_path.read_bytes() == stamp_before


def test_mkdir_pre_effect_failure_preserves_concurrent_directory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    nested_source = source / "deep" / "guide.rst"
    nested_source.parent.mkdir()
    nested_source.write_text("canonical\n", encoding="utf-8")
    stamp_path = module.write_target_only_mirror_stamp(target)
    stamp_before = stamp_path.read_bytes()
    plan = module.make_sync_plan(source, target, delete_extra=True)

    def concurrent_create_then_permission_error(
        parent_fd,
        component,
        *,
        on_success,
    ):
        del on_success
        os.mkdir(component, mode=0o755, dir_fd=parent_fd)
        raise PermissionError("injected pre-effect mkdir failure")

    monkeypatch.setattr(
        module,
        "_mkdir_at",
        concurrent_create_then_permission_error,
    )

    with pytest.raises(PermissionError, match="pre-effect mkdir failure"):
        module.apply_sync_plan_transactionally(source, target, plan)

    assert (target / "deep").is_dir()
    assert list((target / "deep").iterdir()) == []
    assert stamp_path.read_bytes() == stamp_before


def test_created_directory_identity_replacement_is_preserved_and_reported(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    nested_source = source / "deep" / "guide.rst"
    nested_source.parent.mkdir()
    nested_source.write_text("canonical\n", encoding="utf-8")
    stamp_path = module.write_target_only_mirror_stamp(target)
    stamp_before = stamp_path.read_bytes()
    plan = module.make_sync_plan(source, target, delete_extra=True)
    moved_owned = target / "moved-owned"

    def replace_directory_then_fail(*_args, **_kwargs):
        (target / "deep").rename(moved_owned)
        (target / "deep").mkdir()
        raise OSError("stamp failure")

    monkeypatch.setattr(module, "_write_stamp_payload", replace_directory_then_fail)

    with pytest.raises(RuntimeError, match="identity changed concurrently"):
        module.apply_sync_plan_transactionally(source, target, plan)

    assert (target / "deep").is_dir()
    assert not list((target / "deep").iterdir())
    assert (moved_owned / "guide.rst").read_text(encoding="utf-8") == "canonical\n"
    assert stamp_path.read_bytes() == stamp_before


@pytest.mark.parametrize("mutation", ["target", "stamp"])
def test_noop_refresh_revalidates_target_and_exact_stamp(
    tmp_path: Path,
    monkeypatch,
    mutation: str,
) -> None:
    module = _load_module()
    target = tmp_path / "target"
    target.mkdir()
    target_file = target / "guide.rst"
    target_file.write_text("same\n", encoding="utf-8")
    stamp_path = module.write_target_only_mirror_stamp(target)
    original_verify = module._verify_payload_at_boundary
    injected = False

    def mutate_before_revalidation(boundary, payload, **kwargs):
        nonlocal injected
        if not injected:
            injected = True
            if mutation == "target":
                target_file.write_text("changed\n", encoding="utf-8")
            else:
                stamp_path.write_text("{}\n", encoding="utf-8")
        return original_verify(boundary, payload, **kwargs)

    monkeypatch.setattr(
        module,
        "_verify_payload_at_boundary",
        mutate_before_revalidation,
    )

    with pytest.raises(ValueError, match="changed or became stale"):
        module.refresh_target_integrity_stamp(target)

    assert injected is True


def test_alignment_rejects_revalidated_target_change_after_plan(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "guide.rst").write_text("same\n", encoding="utf-8")
    target_file = target / "guide.rst"
    target_file.write_text("same\n", encoding="utf-8")
    module.write_mirror_stamp(source, target)
    original_verify = module.verify_target_mirror_integrity
    mutated = False

    def replace_target_with_independently_valid_state(target_path):
        nonlocal mutated
        if not mutated:
            mutated = True
            target_file.write_text("changed\n", encoding="utf-8")
            module.write_target_only_mirror_stamp(target)
        return original_verify(target_path)

    monkeypatch.setattr(
        module,
        "verify_target_mirror_integrity",
        replace_target_with_independently_valid_state,
    )

    result = module.canonical_mirror_alignment_result(target, source)

    assert result.status == "fail"
    assert result.checked is False
    assert "target changed during alignment verification" in result.message
